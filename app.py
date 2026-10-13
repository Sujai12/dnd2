import os, sqlite3
from pathlib import Path
from functools import wraps
from flask import Flask, g, session, request, redirect, url_for, render_template, flash
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth

ROOT = Path(__file__).resolve().parent
DB = os.environ.get("DATABASE_PATH", str(ROOT / "app.db"))
app = Flask(__name__)
app.config.update(SECRET_KEY=os.environ.get("SECRET_KEY", "local-dev-key-change-before-deploying"),
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1")
oauth = OAuth(app)
if os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"):
    oauth.register(name="google", client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"})

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(_e=None):
    con = g.pop("db", None)
    if con: con.close()

def init_db():
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE COLLATE NOCASE NOT NULL, password_hash TEXT, google_sub TEXT UNIQUE);
    CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, title TEXT NOT NULL, due_date TEXT, priority TEXT NOT NULL DEFAULT 'Normal', done INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS habits(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS focus(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, minutes INTEGER NOT NULL, note TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS distractions(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, label TEXT NOT NULL, minutes INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    con.commit(); con.close()

def user_now():
    if session.get("uid"):
        return db().execute("SELECT id,name,email,google_sub FROM users WHERE id=?", (session["uid"],)).fetchone()
    return None

@app.before_request
def load_user(): g.user = user_now()

def required(fn):
    @wraps(fn)
    def inner(*a, **kw):
        if not g.user:
            flash("Please sign in to open your private workspace.", "info")
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return inner

def local_next(value):
    return value if value and value.startswith("/") and not value.startswith("//") else url_for("dashboard")

@app.route("/")
def home(): return redirect(url_for("dashboard")) if g.user else render_template("home.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if g.user: return redirect(url_for("dashboard"))
    if request.method == "POST":
        name=request.form.get("name","").strip()[:80]; email=request.form.get("email","").strip().lower()[:254]; pw=request.form.get("password","")
        if not name or "@" not in email: flash("Enter your name and a valid email.", "error")
        elif len(pw)<10: flash("Use a password of at least 10 characters.", "error")
        else:
            try:
                cur=db().execute("INSERT INTO users(name,email,password_hash) VALUES(?,?,?)",(name,email,generate_password_hash(pw)))
                db().commit(); session.clear(); session["uid"]=cur.lastrowid; session.permanent=True
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError: flash("That email already has an account. Please log in.", "error")
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET","POST"])
def login():
    if g.user: return redirect(url_for("dashboard"))
    if request.method=="POST":
        email=request.form.get("email","").strip().lower(); pw=request.form.get("password","")
        u=db().execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
        if u and u["password_hash"] and check_password_hash(u["password_hash"],pw):
            session.clear(); session["uid"]=u["id"]; session.permanent=True
            return redirect(local_next(request.args.get("next")))
        flash("Email or password was not recognized.", "error")
    return render_template("auth.html", mode="login")

@app.route("/auth/google")
def google_login():
    if "google" not in oauth:
        flash("Google sign-in is not configured. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.", "info")
        return redirect(url_for("login"))
    return oauth.google.authorize_redirect(url_for("google_callback",_external=True))

@app.route("/auth/google/callback")
def google_callback():
    if "google" not in oauth: return redirect(url_for("login"))
    try:
        token=oauth.google.authorize_access_token(); info=token.get("userinfo") or oauth.google.userinfo()
        email=(info.get("email") or "").lower().strip(); sub=info.get("sub")
        if not email or not info.get("email_verified"): flash("Google did not provide a verified email.", "error"); return redirect(url_for("login"))
        u=db().execute("SELECT * FROM users WHERE google_sub=?",(sub,)).fetchone()
        if not u:
            existing=db().execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
            if existing:
                flash("This email already has a password account. Log in with that account first.", "info"); return redirect(url_for("login"))
            cur=db().execute("INSERT INTO users(name,email,google_sub) VALUES(?,?,?)",((info.get("name") or email.split("@")[0])[:80],email,sub))
            db().commit(); uid=cur.lastrowid
        else: uid=u["id"]
        session.clear(); session["uid"]=uid; session.permanent=True
        return redirect(url_for("dashboard"))
    except Exception:
        app.logger.exception("Google OAuth error"); flash("Google sign-in failed. Please try again.", "error"); return redirect(url_for("login"))

@app.route("/logout", methods=["POST"])
def logout(): session.clear(); return redirect(url_for("home"))

@app.route("/dashboard")
@required
def dashboard():
    uid=g.user["id"]; con=db()
    stats={
      "tasks":con.execute("SELECT COUNT(*) n FROM tasks WHERE user_id=? AND done=0",(uid,)).fetchone()["n"],
      "habits":con.execute("SELECT COUNT(*) n FROM habits WHERE user_id=? AND done=1",(uid,)).fetchone()["n"],
      "focus":con.execute("SELECT COALESCE(SUM(minutes),0) n FROM focus WHERE user_id=? AND date(created_at)=date('now','localtime')",(uid,)).fetchone()["n"],
      "distractions":con.execute("SELECT COALESCE(SUM(minutes),0) n FROM distractions WHERE user_id=? AND date(created_at)=date('now','localtime')",(uid,)).fetchone()["n"]}
    tasks=con.execute("SELECT * FROM tasks WHERE user_id=? ORDER BY done,due_date IS NULL,due_date,id DESC LIMIT 6",(uid,)).fetchall()
    return render_template("dashboard.html", stats=stats, tasks=tasks)

@app.route("/tasks", methods=["GET","POST"])
@required
def tasks():
    uid=g.user["id"]; con=db()
    if request.method=="POST":
        action=request.form.get("action")
        if action=="add":
            title=request.form.get("title","").strip()[:160]; due=request.form.get("due_date") or None; pri=request.form.get("priority","Normal")
            if title and pri in ("Low","Normal","High"): con.execute("INSERT INTO tasks(user_id,title,due_date,priority) VALUES(?,?,?,?)",(uid,title,due,pri)); con.commit()
        elif action=="toggle": con.execute("UPDATE tasks SET done=1-done WHERE id=? AND user_id=?",(request.form.get("id"),uid)); con.commit()
        elif action=="delete": con.execute("DELETE FROM tasks WHERE id=? AND user_id=?",(request.form.get("id"),uid)); con.commit()
        return redirect(url_for("tasks"))
    return render_template("tasks.html", tasks=con.execute("SELECT * FROM tasks WHERE user_id=? ORDER BY done,due_date IS NULL,due_date,id DESC",(uid,)).fetchall())

@app.route("/habits", methods=["GET","POST"])
@required
def habits():
    uid=g.user["id"]; con=db()
    if request.method=="POST":
        action=request.form.get("action")
        if action=="add":
            title=request.form.get("title","").strip()[:120]
            if title: con.execute("INSERT INTO habits(user_id,title) VALUES(?,?)",(uid,title)); con.commit()
        elif action=="toggle": con.execute("UPDATE habits SET done=1-done WHERE id=? AND user_id=?",(request.form.get("id"),uid)); con.commit()
        elif action=="delete": con.execute("DELETE FROM habits WHERE id=? AND user_id=?",(request.form.get("id"),uid)); con.commit()
        return redirect(url_for("habits"))
    return render_template("habits.html", habits=con.execute("SELECT * FROM habits WHERE user_id=? ORDER BY id DESC",(uid,)).fetchall())

@app.route("/focus", methods=["GET","POST"])
@required
def focus():
    uid=g.user["id"]; con=db()
    if request.method=="POST":
        try: mins=int(request.form.get("minutes","0"))
        except ValueError: mins=0
        note=request.form.get("note","").strip()[:160]
        if 1<=mins<=240: con.execute("INSERT INTO focus(user_id,minutes,note) VALUES(?,?,?)",(uid,mins,note)); con.commit(); flash("Focus session saved.", "success")
        else: flash("Minutes must be from 1 to 240.", "error")
        return redirect(url_for("focus"))
    recent=con.execute("SELECT * FROM focus WHERE user_id=? ORDER BY id DESC LIMIT 20",(uid,)).fetchall()
    return render_template("focus.html", recent=recent)

@app.route("/distractions", methods=["GET","POST"])
@required
def distractions():
    uid=g.user["id"]; con=db()
    if request.method=="POST":
        label=request.form.get("label","").strip()[:120]
        try: mins=int(request.form.get("minutes","0"))
        except ValueError: mins=-1
        if label and 0<=mins<=1440: con.execute("INSERT INTO distractions(user_id,label,minutes) VALUES(?,?,?)",(uid,label,mins)); con.commit()
        else: flash("Enter a label and valid minutes.", "error")
        return redirect(url_for("distractions"))
    return render_template("distractions.html", entries=con.execute("SELECT * FROM distractions WHERE user_id=? ORDER BY id DESC LIMIT 50",(uid,)).fetchall())

@app.route("/analytics")
@required
def analytics():
    uid=g.user["id"]; con=db()
    values={
      "focus":con.execute("SELECT COALESCE(SUM(minutes),0) n FROM focus WHERE user_id=?",(uid,)).fetchone()["n"],
      "distractions":con.execute("SELECT COALESCE(SUM(minutes),0) n FROM distractions WHERE user_id=?",(uid,)).fetchone()["n"],
      "complete":con.execute("SELECT COUNT(*) n FROM tasks WHERE user_id=? AND done=1",(uid,)).fetchone()["n"],
      "total":con.execute("SELECT COUNT(*) n FROM tasks WHERE user_id=?",(uid,)).fetchone()["n"],
      "habits":con.execute("SELECT COUNT(*) n FROM habits WHERE user_id=? AND done=1",(uid,)).fetchone()["n"]}
    days=con.execute("SELECT date(created_at) day,SUM(minutes) minutes FROM focus WHERE user_id=? AND created_at>=datetime('now','-6 days') GROUP BY date(created_at) ORDER BY day",(uid,)).fetchall()
    return render_template("analytics.html", v=values, days=days)

@app.route("/coach", methods=["GET","POST"])
@required
def coach():
    answer=None
    if request.method=="POST":
        q=request.form.get("goal","").lower()
        if any(x in q for x in ("stress","anxious","overwhelmed")): answer="Pause, take a few comfortable breaths, and choose one small next task. If these feelings persist, talk to someone you trust."
        elif any(x in q for x in ("phone","scroll","social","distraction")): answer="Put your phone out of reach for one short focus block, close unrelated tabs, and write down the next tiny action."
        elif any(x in q for x in ("sleep","tired","fatigue")): answer="A short break, water, and a consistent sleep routine may help. If you are very tired, rest instead of forcing a long session."
        else: answer="Make the next step small and specific. Try a short focus block, then review how it went. This is a rule-based demo coach, not a live AI service."
    return render_template("coach.html", answer=answer)

@app.route("/settings", methods=["GET","POST"])
@required
def settings():
    if request.method=="POST":
        name=request.form.get("name","").strip()[:80]
        if name: db().execute("UPDATE users SET name=? WHERE id=?",(name,g.user["id"])); db().commit(); flash("Profile updated.", "success")
        return redirect(url_for("settings"))
    profile=db().execute("SELECT name,email,google_sub FROM users WHERE id=?",(g.user["id"],)).fetchone()
    return render_template("settings.html", profile=profile)

@app.errorhandler(404)
def not_found(_): return render_template("error.html", code=404),404

init_db()
if __name__=="__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG")=="1")
