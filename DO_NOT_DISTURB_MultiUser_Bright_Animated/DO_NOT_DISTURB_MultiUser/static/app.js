(()=>{document.querySelectorAll("form[data-confirm]").forEach(f=>f.addEventListener("submit",e=>{if(!confirm(f.dataset.confirm||"Are you sure?"))e.preventDefault()}));const c=document.querySelector("#clock");if(!c)return;const st=document.querySelector("#status"),mi=document.querySelector("#minutes"),start=document.querySelector("#start");let total=1500,left=total,timer=null,running=false;function draw(){c.textContent=String(Math.floor(left/60)).padStart(2,"0")+":"+String(left%60).padStart(2,"0");mi.value=Math.max(1,Math.ceil((total-left)/60))}function stop(){clearInterval(timer);timer=null;running=false;start.textContent="Start focus"}start.onclick=()=>{if(running){stop();st.textContent="Paused. Resume when ready.";return}if(left<=0){left=total;draw()}running=true;start.textContent="Pause";st.textContent="One thing at a time.";timer=setInterval(()=>{left--;draw();if(left<=0){stop();st.textContent="Complete. Save it below if you focused.";mi.value=Math.round(total/60)}},1000)};document.querySelector("#reset").onclick=()=>{stop();left=total;draw();st.textContent="Ready when you are"};document.querySelectorAll(".preset").forEach(b=>b.onclick=()=>{stop();total=Number(b.dataset.min)*60;left=total;draw();st.textContent="Ready for a focus block?"});draw()})();


/* Small motion details for a more playful interface */
document.addEventListener("DOMContentLoaded",()=>{
  document.querySelectorAll(".card,.features article,.stats article").forEach((el,i)=>{
    el.style.animationDelay=(Math.min(i,8)*55)+"ms";
    el.classList.add("motion-ready");
  });
  document.querySelectorAll("button,.btn,.ghost").forEach(el=>{
    el.addEventListener("pointerdown",()=>{el.style.transform="scale(.97)";});
    ["pointerup","pointerleave","blur"].forEach(evt=>el.addEventListener(evt,()=>{el.style.transform="";}));
  });
});
