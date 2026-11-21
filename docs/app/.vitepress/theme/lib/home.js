import { esc, lerp, clamp, ease, css, reducedMotion, whileVisible, onThemeChange, logoParts, bag } from "./core.js";
import { taskFigure } from "./figures.js";

export function mountHome(root){
  const $=(s,r=root)=>r.querySelector(s), $$=(s,r=root)=>[...r.querySelectorAll(s)];
  const reduce=reducedMotion(), B_=bag();
const wheelState={om:0};
function wheel(){
  const el=$("#wheel"),p=logoParts(),MAX=30;
  el.innerHTML=`<svg viewBox="0 0 512 512" aria-hidden="true">
    <g id="w-rot">
      <g class="in h">${p.handles}</g>
      <g class="in" style="animation-delay:.05s">${p.ring}</g>
      <g class="in" style="animation-delay:.18s">${p.hex}${p.inner}</g>
      <g class="in" style="animation-delay:.3s">${p.nodes}</g>
    </g>
    <g id="w-sp">${p.spiral}</g></svg>`;
  const sp=$(".sp",el);sp.style.setProperty("--len",sp.getTotalLength());
  const rot=$("#w-rot",el),spg=$("#w-sp",el),nodes=$$(".hn",el),R0=nodes.map(n=>+n.getAttribute("r"));
  let th=0,spA=0,drag=false,last=0,lastT=0,touched=false,prev=0;
  if(!reduce)B_.timeout(()=>{if(!touched)wheelState.om=9},1700);
  const ang=e=>{const r=el.getBoundingClientRect();return Math.atan2(e.clientY-(r.top+r.height/2),e.clientX-(r.left+r.width/2))*180/Math.PI};
  el.addEventListener("pointerdown",e=>{drag=true;touched=true;last=ang(e);lastT=performance.now();el.setPointerCapture(e.pointerId);el.classList.add("grab");wheelState.om=0});
  el.addEventListener("pointermove",e=>{if(!drag)return;const a=ang(e),now=performance.now();let d=a-last;if(d>180)d-=360;if(d<-180)d+=360;
    th+=d;const dt=Math.max(8,now-lastT);wheelState.om=clamp(lerp(wheelState.om,d/dt*16.7,.5),-MAX,MAX);last=a;lastT=now});
  // let go after holding still: it stays still
  const up=()=>{if(drag&&performance.now()-lastT>60)wheelState.om=0;drag=false;el.classList.remove("grab")};
  el.addEventListener("pointerup",up);el.addEventListener("pointercancel",up);
  el.addEventListener("keydown",e=>{const d=e.key==="ArrowRight"||e.key==="ArrowUp"?4:e.key==="ArrowLeft"||e.key==="ArrowDown"?-4:0;if(d){touched=true;wheelState.om=clamp(wheelState.om+d,-MAX,MAX);e.preventDefault()}});
  B_.add(whileVisible(el,t=>{
    const k=Math.min(3,(t-(prev||t))/16.7)||1;prev=t;
    if(+($("#stage").dataset.cover||0)>.98)return;
    if(!drag){th+=wheelState.om*k;wheelState.om*=Math.pow(.968,k);if(Math.abs(wheelState.om)<.01)wheelState.om=0}
    spA+=reduce?0:(-wheelState.om*.55-.12)*k;
    rot.setAttribute("transform",`rotate(${th.toFixed(2)} 256 256)`);
    spg.setAttribute("transform",`rotate(${spA.toFixed(2)} 256 256)`);
    const g=clamp(Math.abs(wheelState.om)/10);nodes.forEach((n,i)=>n.setAttribute("r",(R0[i]*(1+g*.35*(.6+.4*Math.sin(th/20+i)))).toFixed(2)));
    el.setAttribute("aria-valuenow",String(Math.round(((th%360)+360)%360)));
  }));
}

/* ---------- hero background: benzene lattice whose rings light up with circulating electrons (click one), and a DNA helix under the buttons ---------- */

function heroBg(){
  const stage=$("#stage"),cv=$("#bg"),ctx=cv.getContext("2d"),hero=$("#hero");
  let W=0,H=0,dpr=1,lat=null,col={},ph=0,seqOff=0,rings=[],lastRing=0,hover=null,helixY=0,fx=0,fy=0,tNow=0;
  // M P O I E S I S stop: O is pyrrolysine, coded by TAG
  const SEQ="ATGCCGTAGATTGAATCTATTTCTTAA",AMINO=["M","P","O","I","E","S","I","S","*"];
  let helixHot=false,hotA=0,Acur=30,lastF=0,fliers=[];
  const S=26,HW=Math.sqrt(3)*S,RH=1.5*S;
  const colors=()=>{col={line:css("--line-strong"),blue:css("--blue"),coral:css("--coral"),muted:css("--muted")}};
  const vtx=(x,y,i)=>{const a=Math.PI/180*(60*i-30);return[x+S*Math.cos(a),y+S*Math.sin(a)]};
  function hexPath(c,x,y,r=S){c.beginPath();for(let i=0;i<6;i++){const a=Math.PI/180*(60*i-30);c.lineTo(x+r*Math.cos(a),y+r*Math.sin(a))}c.closePath()}
  const center=(r,c)=>[c*HW+(r%2?HW/2:0),r*RH];
  function nearest(x,y){let best=null,bd=1e9;const r0=Math.round(y/RH);
    for(let r=r0-1;r<=r0+1;r++){const c=Math.round((x-(r%2?HW/2:0))/HW),[cx,cy]=center(r,c),d=(cx-x)**2+(cy-y)**2;if(d<bd){bd=d;best={r,c,x:cx,y:cy}}}return best}
  function buildLattice(){
    lat=document.createElement("canvas");lat.width=Math.max(1,W*dpr);lat.height=Math.max(1,H*dpr);const c=lat.getContext("2d");c.scale(dpr,dpr);
    c.strokeStyle=col.line;c.lineWidth=1;c.globalAlpha=.65;
    for(let r=0;r*RH<H+S;r++)for(let k=-1;k*HW<W+HW;k++){const[x,y]=center(r,k);hexPath(c,x,y);c.stroke()}
    c.globalCompositeOperation="destination-in";c.globalAlpha=1;
    const g=c.createRadialGradient(fx,fy,30,fx,fy,Math.max(W,H)*.6);
    g.addColorStop(0,"rgba(0,0,0,1)");g.addColorStop(.5,"rgba(0,0,0,.4)");g.addColorStop(1,"rgba(0,0,0,0)");c.fillStyle=g;c.fillRect(0,0,W,H);
  }
  function size(){
    const r=stage.getBoundingClientRect();if(!r.width)return;dpr=Math.min(2,devicePixelRatio||1);W=r.width;H=r.height;cv.width=W*dpr;cv.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);
    const w=$("#wheel").getBoundingClientRect(),a=$("#hero-actions").getBoundingClientRect();
    fx=w.left-r.left+w.width/2;fy=w.top-r.top+w.height/2;
    helixY=Math.max(a.bottom,W>760?w.bottom-30:0)-r.top+72;
    colors();buildLattice();if(reduce)frame(performance.now());
  }
  
  // a ring is a task landing on a node: pending (dashed), running (electrons), done (blue). One you click just runs.
  const ring=(x,y,strong,delay=0,sp)=>{if(strong){const st=rings.filter(r=>r.strong);if(st.length>=3)rings.splice(rings.indexOf(st[0]),1)}
    rings.push({x,y,strong,sp:sp||(strong?.45:.2),t0:tNow+delay,dur:strong?6200:5600})};
  function drawRing(p,now){
    const k=(now-p.t0)/p.dur;if(k<0)return;
    const phase=p.strong?"run":k<.14?"pend":k<.8?"run":"done";
    const a=p.strong?(k<.06?k/.06:1-(k-.06)/.94):phase==="pend"?k/.14:phase==="done"?1-(k-.8)/.2:1;
    if(phase==="pend"){ctx.globalAlpha=a*.75;ctx.setLineDash([4,4]);ctx.strokeStyle=col.coral;ctx.lineWidth=1.2;hexPath(ctx,p.x,p.y);ctx.stroke();ctx.setLineDash([]);return}
    if(phase==="done"){ctx.globalAlpha=a*.16;ctx.fillStyle=col.blue;hexPath(ctx,p.x,p.y);ctx.fill();ctx.globalAlpha=a*.6;ctx.strokeStyle=col.blue;ctx.lineWidth=1.2;hexPath(ctx,p.x,p.y);ctx.stroke();return}
    if(p.strong){ctx.globalAlpha=a*.1;ctx.fillStyle=col.coral;hexPath(ctx,p.x,p.y);ctx.fill()}
    ctx.globalAlpha=a*(p.strong?.95:.55);ctx.strokeStyle=col.coral;ctx.lineWidth=p.strong?2:1.2;hexPath(ctx,p.x,p.y);ctx.stroke();
    ctx.globalAlpha=a*(p.strong?.55:.3);ctx.strokeStyle=col.blue;ctx.lineWidth=1;ctx.beginPath();ctx.arc(p.x,p.y,S*.52,0,7);ctx.stroke();
    const n=p.strong?3:2,speed=p.sp,dir=Math.sign(speed)||1,t=(now-p.t0)/1000;
    for(let e=0;e<n;e++)for(let tr=0;tr<6;tr++){const u=((t*speed*6-dir*tr*.07+e*6/n)%6+6)%6,i=Math.floor(u),f=u-i,[x1,y1]=vtx(p.x,p.y,i),[x2,y2]=vtx(p.x,p.y,(i+1)%6);
      ctx.globalAlpha=a*(1-tr/6)*(tr?.5:1);ctx.fillStyle=col.coral;ctx.beginPath();ctx.arc(lerp(x1,x2,f),lerp(y1,y2,f),(p.strong?3:2.1)*(1-tr/10),0,7);ctx.fill()}
  }
  function frame(now){
    tNow=now;if(!W)return;
    const k=Math.min(3,(now-(lastF||now))/16.7)||1;lastF=now;
    if(+(stage.dataset.cover||0)>.98)return;
    ctx.clearRect(0,0,W,H);ctx.globalAlpha=1;ctx.drawImage(lat,0,0,W,H);
    if(hover){ctx.globalAlpha=.55;ctx.strokeStyle=col.blue;ctx.lineWidth=1.2;hexPath(ctx,hover.x,hover.y);ctx.stroke()}
    // turning the wheel throws tasks from the hub onto nodes, the way it turns; at rest only the odd one
    const om=wheelState.om,spin=Math.abs(om),busy=spin>.5;
    if(!reduce&&now-lastRing>(busy?Math.max(320,2600/spin):6000)&&rings.length<(busy?9:1)){lastRing=now;
      const ang=Math.random()*Math.PI*2,rad=(.22+Math.random()*(busy?Math.min(1,.45+spin/14):.6))*Math.min(W,H)*.62,h=nearest(fx+Math.cos(ang)*rad,fy+Math.sin(ang)*rad);
      if(h&&!rings.some(r=>r.x===h.x&&r.y===h.y)){const fly=busy?520:0;if(busy)fliers.push({x:h.x,y:h.y,t0:now,dur:fly});ring(h.x,h.y,false,fly,(busy?.22+Math.min(spin,20)*.012:.2)*(om<0?-1:1))}}
    rings=rings.filter(p=>now-p.t0<p.dur);for(const p of rings)drawRing(p,now);
    fliers=fliers.filter(f=>now-f.t0<f.dur);
    for(const f of fliers){const u=ease(clamp((now-f.t0)/f.dur));for(let tr=0;tr<5;tr++){const v=clamp(u-tr*.05),x=lerp(fx,f.x,v),y=lerp(fy,f.y,v)-Math.sin(Math.PI*v)*28;
      ctx.globalAlpha=(1-tr/5)*.9;ctx.fillStyle=col.coral;ctx.beginPath();ctx.arc(x,y,3.4*(1-tr/7),0,7);ctx.fill()}}
    // DNA double helix under the buttons; hover it and it reads out POIESIS, one codon per letter
    hotA=lerp(hotA,helixHot?1:0,reduce?1:.14*k);
    if(!helixHot&&!reduce){ph+=(.012+spin*.004)*k;seqOff+=(.18+spin*.08)*k}
    const y0=helixY,A=Acur=Math.min(30,W*.05),kk=2*Math.PI/260,fade=x=>clamp(x/(W*.2))*clamp((W-x)/(W*.2)),shift=Math.floor(seqOff/17),off=seqOff%17;
    for(let i=0;;i++){const x=-17-off+i*17;if(x>W+20)break;const t=x*kk+ph,f=fade(x);if(f<=0)continue;const b=SEQ[(i+shift)%SEQ.length],gc=b==="G"||b==="C",z=Math.cos(t);
      ctx.globalAlpha=f*(.12+.22*(z+1)/2);ctx.strokeStyle=gc?col.coral:col.blue;ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(x,y0+A*Math.sin(t));ctx.lineTo(x,y0-A*Math.sin(t));ctx.stroke()}
    for(const sg of[1,-1]){ctx.lineWidth=2;ctx.strokeStyle=sg>0?col.blue:col.coral;let pv=null;
      for(let x=-20;x<W+20;x+=5){const t=x*kk+ph,y=y0+sg*A*Math.sin(t),z=sg*Math.cos(t),f=fade(x);
        if(pv&&f>0){ctx.globalAlpha=f*(.18+.5*(z+1)/2);ctx.beginPath();ctx.moveTo(pv[0],pv[1]);ctx.lineTo(x,y);ctx.stroke()}pv=[x,y]}}
    ctx.font="11px 'JetBrains Mono', monospace";ctx.textAlign="center";
    for(let i=0;;i++){const x=-17-off+i*17;if(x>W+20)break;const f=fade(x);if(f<=0)continue;const g=(i+shift)%SEQ.length;
      ctx.globalAlpha=f*(.24+.5*hotA);ctx.fillStyle=col.muted;ctx.fillText(SEQ[g],x,y0+A+26);
      if(hotA>.02&&g%3===0&&AMINO[g/3]!=="*"&&AMINO[g/3]!=="M"){const xc=x+17,aa=AMINO[g/3];
        ctx.globalAlpha=f*hotA*.6;ctx.strokeStyle=col.muted;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x-6,y0+A+32);ctx.lineTo(x-6,y0+A+36);ctx.lineTo(x+40,y0+A+36);ctx.lineTo(x+40,y0+A+32);ctx.stroke();
        ctx.globalAlpha=f*hotA;ctx.fillStyle=aa==="O"?col.coral:col.blue;ctx.font="600 14px 'JetBrains Mono', monospace";ctx.fillText(aa,xc,y0+A+54);ctx.font="11px 'JetBrains Mono', monospace"}}
    ctx.textAlign="start";ctx.globalAlpha=1;
  }
  // the empty background is a plaything; the helix band reads out
  const onLattice=e=>!e.target.closest("a,button,h1,p,.wheel");
  stage.addEventListener("pointermove",e=>{if(!W)return;const r=stage.getBoundingClientRect(),y=e.clientY-r.top,ok=onLattice(e);
    if(e.pointerType==="mouse")helixHot=ok&&Math.abs(y-helixY)<Acur+60;hover=ok&&!helixHot?nearest(e.clientX-r.left,y):null;stage.classList.toggle("lat-hover",!!hover);if(reduce)frame(performance.now())});
  let hotTimer=0;B_.add(()=>clearTimeout(hotTimer));stage.addEventListener("pointerdown",e=>{if(e.pointerType==="mouse"||!W)return;const r=stage.getBoundingClientRect(),y=e.clientY-r.top;
    if(onLattice(e)&&Math.abs(y-helixY)<Acur+60){helixHot=!helixHot;clearTimeout(hotTimer);if(helixHot)hotTimer=setTimeout(()=>{helixHot=false;if(reduce)frame(performance.now())},5000);if(reduce)frame(performance.now())}});
  stage.addEventListener("pointerleave",e=>{if(e.pointerType!=="mouse")return;hover=null;helixHot=false;stage.classList.remove("lat-hover");if(reduce)frame(performance.now())});
  stage.addEventListener("click",e=>{if(!onLattice(e)||!W||helixHot)return;const r=stage.getBoundingClientRect(),h=nearest(e.clientX-r.left,e.clientY-r.top);
    ring(h.x,h.y,true);
    [[0,-1],[0,1],[-1,h.r%2?1:-1]].forEach(([dr,dc],i)=>{const[x,y]=center(h.r+dr,h.c+dc);ring(x,y,false,300+i*220)});
    if(reduce)frame(performance.now()+400)});
  B_.on(window,"resize",size);B_.add(onThemeChange(()=>{colors();buildLattice();if(reduce)frame(performance.now())}));
  size();
  if(reduce)frame(performance.now());else B_.add(whileVisible(stage,frame));
}


/* ---------- home sections stack: each stays put while the next slides over it ---------- */
function stack(){
  const layers=["#stage","#s-eng","#s-task"].map(q=>$(q)),on=()=>innerWidth>=960,T=[],T0=[];
  const tops=()=>{let acc=64;layers.forEach((el,i)=>{T[i]=on()?Math.min(64,innerHeight-el.offsetHeight):0;el.style.top=on()?T[i]+"px":"";T0[i]=acc;acc+=el.offsetHeight-24})};
  let ticking=false;
  const update=()=>{ticking=false;layers.forEach((el,i)=>{let c=0;const nx=layers[i+1];
    if(nx&&on()){const t=nx.getBoundingClientRect().top,A=Math.min(innerHeight,T0[i+1]-(window.scrollY>0?0:0));if(A>T[i+1])c=clamp((A-t)/(A-T[i+1]))}
    el.dataset.cover=c.toFixed(3);
    if(reduce)return;
    $$(".li",el).forEach(li=>{if(li.tagName==="CANVAS"){li.style.opacity=c?(1-c*.5).toFixed(3):"";return}
      li.style.opacity=c?(1-c*.55).toFixed(3):"";li.style.transform=c?`translateY(${(c*24).toFixed(1)}px) scale(${(1-c*.04).toFixed(4)})`:""})})};
  B_.on(window,"scroll",()=>{if(!ticking){ticking=true;requestAnimationFrame(update)}},{passive:true});
  B_.on(window,"resize",()=>{tops();update()});
  return()=>{tops();update()};
}

/* ---------- engine logos: drag, throw, bounce off each other and the table ---------- */
function enginePlay(){
  const sec=$("#s-eng"),field=$("#eng-field"),ob=$("#eng-center"),els=$$(".pl",field),rows=$$(".eng li"),E=.7;
  let W=0,H=0,obs={x:0,y:0,w:0,h:0},B=[],drag=null,tPrev=0,lastMoved=0,clock=0,on=false;
  const draw=()=>{for(const b of B)b.el.style.transform=`translate(${(b.x-b.r).toFixed(1)}px,${(b.y-b.r).toFixed(1)}px)`};
  // slots: two staggered columns either side of the table
  function slots(){const n=els.length,out=[],left=obs.x,right=W-(obs.x+obs.w),cols=[{cx:left/2,w:left},{cx:obs.x+obs.w+right/2,w:right}],per=[Math.ceil(n/2),Math.floor(n/2)],top=Math.max(90,obs.y+30),bot=Math.min(H-110,obs.y+obs.h-30);
    let idx=0;cols.forEach((c,ci)=>{for(let j=0;j<per[ci];j++){const t=per[ci]===1?.5:j/(per[ci]-1),zig=(j%2?1:-1)*Math.min(46,c.w*.16)*(ci?-1:1);out[idx++]={x:c.cx+zig,y:lerp(top,bot,t)}}});return out}
  function size(){const r=sec.getBoundingClientRect();if(!r.width)return;W=r.width;H=r.height;on=W>760;
    if(!on){els.forEach(el=>el.style.transform="");return}
    const o=ob.getBoundingClientRect();obs={x:o.left-r.left-14,y:o.top-r.top-14,w:o.width+28,h:o.height+28};const S=slots();
    els.forEach((el,i)=>{const r0=+el.dataset.s/2;if(!B[i])B[i]={el,x:S[i].x,y:S[i].y,vx:0,vy:0,r:r0,m:r0*r0,held:false,ph:i*1.7};const b=B[i];b.ax=S[i].x;b.ay=S[i].y});
    draw()}
  function step(dt){const k=dt/16.7;clock+=dt/1000;
    for(const b of B){if(b.held)continue;
      const tx=b.ax+Math.sin(clock*.6+b.ph)*4,ty=b.ay+Math.cos(clock*.5+b.ph)*6;
      b.vx+=(tx-b.x)*.018*k;b.vy+=(ty-b.y)*.018*k;const damp=Math.pow(.86,k);b.vx*=damp;b.vy*=damp;
      const sp=Math.hypot(b.vx,b.vy);if(sp>40){b.vx*=40/sp;b.vy*=40/sp}
      b.x+=b.vx*k;b.y+=b.vy*k;
      if(b.x<b.r){b.x=b.r;b.vx=Math.abs(b.vx)*E}if(b.x>W-b.r){b.x=W-b.r;b.vx=-Math.abs(b.vx)*E}
      if(b.y<b.r){b.y=b.r;b.vy=Math.abs(b.vy)*E}if(b.y>H-36-b.r){b.y=H-36-b.r;b.vy=-Math.abs(b.vy)*E}
      const cx=clamp(b.x,obs.x,obs.x+obs.w),cy=clamp(b.y,obs.y,obs.y+obs.h);let dx=b.x-cx,dy=b.y-cy;const d=Math.hypot(dx,dy);
      if(d<b.r&&d>0){dx/=d;dy/=d;b.x=cx+dx*b.r;b.y=cy+dy*b.r;const vn=b.vx*dx+b.vy*dy;if(vn<0){b.vx-=(1+E)*vn*dx;b.vy-=(1+E)*vn*dy}}}
    for(let i=0;i<B.length;i++)for(let j=i+1;j<B.length;j++){const a=B[i],c=B[j],dx=c.x-a.x,dy=c.y-a.y,d=Math.hypot(dx,dy),min=a.r+c.r+4;
      if(d>0&&d<min){const nx=dx/d,ny=dy/d,ia=a.held?0:1/a.m,ic=c.held?0:1/c.m,sum=ia+ic;if(!sum)continue;const ov=min-d;
        a.x-=nx*ov*ia/sum;a.y-=ny*ov*ia/sum;c.x+=nx*ov*ic/sum;c.y+=ny*ov*ic/sum;
        const rv=(c.vx-a.vx)*nx+(c.vy-a.vy)*ny;if(rv<0){const jj=-(1+E)*rv/sum;a.vx-=jj*ia*nx;a.vy-=jj*ia*ny;c.vx+=jj*ic*nx;c.vy+=jj*ic*ny}}}}
  field.addEventListener("pointerdown",e=>{if(!on)return;const el=e.target.closest(".pl");if(!el)return;e.preventDefault();const b=B.find(x=>x.el===el),r=sec.getBoundingClientRect();
    drag={b,ox:e.clientX-r.left-b.x,oy:e.clientY-r.top-b.y,sx:e.clientX,sy:e.clientY,hist:[[performance.now(),e.clientX,e.clientY]],moved:0};b.held=true;b.vx=b.vy=0;el.classList.add("held");el.setPointerCapture(e.pointerId)});
  field.addEventListener("pointermove",e=>{if(!drag)return;const r=sec.getBoundingClientRect(),b=drag.b;
    b.x=clamp(e.clientX-r.left-drag.ox,b.r,W-b.r);b.y=clamp(e.clientY-r.top-drag.oy,b.r,H-36-b.r);
    drag.moved=Math.max(drag.moved,Math.hypot(e.clientX-drag.sx,e.clientY-drag.sy));drag.hist.push([performance.now(),e.clientX,e.clientY]);if(drag.hist.length>8)drag.hist.shift();if(reduce)draw()});
  const release=()=>{if(!drag)return;const b=drag.b,now=performance.now(),h=drag.hist.filter(p=>now-p[0]<120),a=h[0]||[now,0,0],z=h[h.length-1]||a,dt=Math.max(16,z[0]-a[0]);
    b.vx=(z[1]-a[1])/dt*16.7;b.vy=(z[2]-a[2])/dt*16.7;b.held=false;b.el.classList.remove("held");lastMoved=drag.moved;drag=null;if(reduce){b.x=b.ax;b.y=b.ay;draw()}};
  field.addEventListener("pointerup",release);field.addEventListener("pointercancel",release);
  field.addEventListener("click",e=>{const pl=e.target.closest(".pl");if(pl&&(lastMoved>=5||pl.tagName!=="A"))e.preventDefault();lastMoved=0});
  const link=(i,v)=>{const pl=els.find(x=>x.dataset.i==i),li=rows.find(x=>x.dataset.i==i);if(pl)pl.classList.toggle("hl",v);if(li)li.classList.toggle("hl",v)};
  els.forEach(el=>{el.addEventListener("pointerenter",()=>link(el.dataset.i,true));el.addEventListener("pointerleave",()=>link(el.dataset.i,false))});
  rows.forEach(li=>{li.addEventListener("pointerenter",()=>link(li.dataset.i,true));li.addEventListener("pointerleave",()=>link(li.dataset.i,false))});
  B_.on(window,"resize",size);
  B_.add(whileVisible(sec,t=>{const dt=Math.min(40,t-(tPrev||t))||16;tPrev=t;if(!on||!W||+(sec.dataset.cover||0)>.98)return;if(!reduce||drag)step(dt);draw()}));
}

  wheel();heroBg();enginePlay();const stackRefresh=stack();
  requestAnimationFrame(()=>{stackRefresh();window.dispatchEvent(new Event("resize"))});
  B_.add(()=>{root.querySelectorAll(".li").forEach(li=>{li.style.opacity="";li.style.transform=""})});
  return()=>B_.dispose();
}
