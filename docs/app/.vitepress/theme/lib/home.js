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
  let flows=[],lastFlow=-4500;
  const S=26,HW=Math.sqrt(3)*S,RH=1.5*S;
  const colors=()=>{col={line:css("--line-strong"),blue:css("--blue"),coral:css("--coral"),muted:css("--muted"),bg:css("--bg")}};
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
    colors();buildLattice();computeSlots();if(reduce)frame(performance.now());
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

  /* workflows on the lattice: several shapes, some steps in parallel, some in sequence.
     A step waits for its inputs, runs (coral), then is done (blue). Labels never move. */
  const FLOWS=[
    {name:"chain",nodes:[[0,0,"qc"],[0,1,"trim"],[0,2,"map"],[0,3,"call"]],deps:[[],[0],[1],[2]]},
    {name:"fan",nodes:[[1,0,"split"],[0,1,"map"],[1,1,"map"],[2,1,"map"],[1,2,"merge"]],deps:[[],[0],[0],[0],[1,2,3]]},
    {name:"diamond",nodes:[[1,0,"qc"],[0,1,"trim"],[2,1,"kmer"],[1,2,"asm"]],deps:[[],[0],[0],[1,2]]},
    {name:"pair",nodes:[[0,0,"idx"],[0,1,"map"],[0,2,"count"],[2,0,"qc"],[2,1,"trim"],[2,2,"sort"]],deps:[[],[0],[1],[],[3],[4]]},
    {name:"scatter",nodes:[[0,0,"split"],[1,0,"call"],[1,1,"call"],[0,1,"call"],[2,1,"gather"]],deps:[[],[0],[0],[0],[1,2,3]]},
  ];
  const flowHexes=()=>flows.flatMap(f=>f.nodes.map(n=>n.r+":"+n.c));
  // every place each workflow shape fits, recomputed on resize; spawning picks from these
  let slots=[];
  function computeSlots(){
    slots=[];if(!W)return;
    const sr=stage.getBoundingClientRect(),pad=10,cb=$('#copy').getBoundingClientRect(),wb=$('#wheel').getBoundingClientRect();
    const c0=cb.left-sr.left-pad,c1=cb.right-sr.left+pad,r0=cb.top-sr.top-pad,r1=cb.bottom-sr.top+pad;
    const wx=wb.left-sr.left+wb.width/2,wy=wb.top-sr.top+wb.height/2,wr=wb.width*.47+S*.6;
    const g=amGeom();const blocked=(x,y)=>Math.hypot(x-g.cx,y-g.cy)<g.R*1.2+S||Math.hypot(x-wx,y-wy)<wr||(x>c0-S*.6&&x<c1+S*.6&&y>r0-S*.6&&y<r1+S*.6);
    const rows=Math.ceil(helixY/RH),cols=Math.ceil(W/HW)+1;
    for(const T of FLOWS)for(let r=0;r<rows;r++)for(let c=0;c<cols;c++){
      const nodes=T.nodes.map(([dr,dc])=>{const rr=r+dr,cc=c+dc+(dr%2&&r%2?1:0);const[x,y]=center(rr,cc);return{r:rr,c:cc,x,y}});
      const ok=nodes.every(n=>n.x>34&&n.x<W-34&&n.y>30&&n.y<helixY-52&&!blocked(n.x,n.y))
        &&T.deps.every((ds,k)=>ds.every(d=>{const a=nodes[d],b=nodes[k];for(let u=.25;u<1;u+=.25)if(blocked(lerp(a.x,b.x,u),lerp(a.y,b.y,u)))return false;return true}));
      if(ok)slots.push({T,r,c,nodes});
    }
    stage.dataset.slots=String(slots.length);
  }
  function spawnFlow(now){
    const near=new Set();for(const k of flowHexes()){const[a,b]=k.split(':').map(Number);for(let dr=-1;dr<=1;dr++)for(let dc=-1;dc<=1;dc++)near.add((a+dr)+':'+(b+dc))}
    const live=new Set(flows.map(f=>f.name));
    let pool=slots.filter(sl=>!sl.nodes.some(n=>near.has(n.r+':'+n.c)));
    const fresh=pool.filter(sl=>!live.has(sl.T.name));if(fresh.length)pool=fresh;
    if(!pool.length)return false;
    const sl=pool[Math.floor(Math.random()*pool.length)];
    flows.push({name:sl.T.name,t0:now,end:0,nodes:sl.nodes.map((n,i)=>({...n,label:sl.T.nodes[i][2],dep:sl.T.deps[i],dur:2200+Math.random()*1400,shown:0,start:0,state:"wait"}))});
    return true;
  }
  function drawFlows(now){
    const FADE=700;
    for(const f of flows){
      f.nodes.forEach((n,i)=>{
        // a step appears once its inputs are running; the first steps appear one after another
        if(!n.shown&&(n.dep.length?n.dep.every(d=>f.nodes[d].state!=="wait"):now-f.t0>i*450))n.shown=now;
        if(n.state==="wait"&&n.shown&&now-n.shown>FADE&&n.dep.every(d=>f.nodes[d].state==="done")){n.state="run";n.start=now}
        if(n.state==="run"&&now-n.start>n.dur)n.state="done";
      });
      if(!f.end&&f.nodes.every(n=>n.state==="done"))f.end=now;
      const out=f.end?1-clamp((now-f.end-2200)/1600):1;
      if(f.end&&out<=0){f.gone=true;continue}
      // links draw out from the upstream step when the downstream one appears
      f.nodes.forEach(n=>{if(!n.shown)return;const g=clamp((now-n.shown)/FADE);n.dep.forEach(d=>{const p=f.nodes[d],live=p.state==="done";
        ctx.globalAlpha=out*(live?.55:.25);ctx.strokeStyle=col.coral;ctx.lineWidth=1.2;ctx.setLineDash([3,4]);ctx.lineDashOffset=live?-now/60:0;
        ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(lerp(p.x,n.x,ease(g)),lerp(p.y,n.y,ease(g)));ctx.stroke();ctx.setLineDash([])})});
      ctx.font="500 8.5px 'JetBrains Mono', monospace";ctx.textAlign="center";
      for(const n of f.nodes){
        if(!n.shown)continue;
        const a=out*ease(clamp((now-n.shown)/FADE)),run=n.state==="run",done=n.state==="done",pulse=run?.5+.5*Math.sin((now-n.start)/260):0;
        ctx.globalAlpha=a*.92;ctx.fillStyle=col.bg;hexPath(ctx,n.x,n.y);ctx.fill();
        if(run||done){ctx.globalAlpha=a*(run?.1+.1*pulse:.15);ctx.fillStyle=run?col.coral:col.blue;hexPath(ctx,n.x,n.y);ctx.fill()}
        ctx.globalAlpha=a*(n.state==="wait"?.45:.85);ctx.strokeStyle=done?col.blue:col.coral;ctx.lineWidth=run?1.5:1.2;
        if(n.state==="wait")ctx.setLineDash([3,3]);hexPath(ctx,n.x,n.y);ctx.stroke();ctx.setLineDash([]);
        ctx.globalAlpha=a*(n.state==="wait"?.45:.8);ctx.fillStyle=done?col.blue:run?col.coral:col.muted;ctx.fillText(n.label,n.x,n.y+3.5);
      }
      ctx.textAlign="start";
    }
    flows=flows.filter(f=>!f.gone);ctx.globalAlpha=1;
  }

  /* one large amoeba resting in the top-left corner, organelles visible */
  const am={seed:Math.random()*100,cx:0,cy:0,R:0,px:0,py:0,on:false,reach:0,pa:0,food:[]};
  const inAmoeba=(x,y)=>am.R&&Math.hypot(x-am.cx,y-am.cy)<am.R*1.08;
  const amGeom=(t=0)=>{const R=Math.min(W,H)*(W>760?.3:.24);return{R,cx:R*.42+Math.sin(t*.00007)*R*.05+Math.sin(t*.00019)*R*.015,cy:R*.5+Math.cos(t*.00005)*R*.04}};
  function blob(cx,cy,r,t,amp,seed,n=72){ctx.beginPath();for(let i=0;i<=n;i++){const a=i/n*Math.PI*2;
    let da=Math.abs(((a-am.pa)%(Math.PI*2)+Math.PI*3)%(Math.PI*2)-Math.PI);const pod=am.reach*.38*Math.pow(Math.max(0,Math.cos(da)),8);
    const w=1+pod+amp*(.55*Math.sin(a*3+t*.00035+seed)+.35*Math.sin(a*5-t*.0005+seed*2)+.6*Math.max(0,Math.sin(a*2-t*.00022+seed))**3);
    ctx.lineTo(cx+Math.cos(a)*r*w,cy+Math.sin(a)*r*w)}ctx.closePath()}
  function drawAmoeba(now){
    const t=reduce?0:now,{R,cx,cy}=amGeom(t);
    am.cx=cx;am.cy=cy;am.R=R;am.reach=lerp(am.reach,am.on?1:0,reduce?1:.05);
    if(am.on){const ta=Math.atan2(am.py-cy,am.px-cx);let d=ta-am.pa;d=Math.atan2(Math.sin(d),Math.cos(d));am.pa+=d*(reduce?1:.08)}
    const sx=Math.cos(am.pa)*am.reach*R*.08,sy=Math.sin(am.pa)*am.reach*R*.08,B=col.blue,Cc=col.coral;
    const dot=(x,y,r,c,a)=>{ctx.globalAlpha=a;ctx.fillStyle=c;ctx.beginPath();ctx.arc(x,y,r,0,7);ctx.fill()};
    const ring=(x,y,r,c,a,w=1)=>{ctx.globalAlpha=a;ctx.strokeStyle=c;ctx.lineWidth=w;ctx.beginPath();ctx.arc(x,y,r,0,7);ctx.stroke()};
    // membrane: soft fill, ectoplasm and endoplasm outlines
    ctx.globalAlpha=.035;ctx.fillStyle=B;blob(cx,cy,R,t,.12,am.seed);ctx.fill();
    ctx.globalAlpha=.22;ctx.strokeStyle=B;ctx.lineWidth=1.3;blob(cx,cy,R,t,.12,am.seed);ctx.stroke();
    ctx.globalAlpha=.08;ctx.lineWidth=1;blob(cx,cy,R*.9,t,.1,am.seed+.4);ctx.stroke();
    // fine granules streaming with the cytoplasm
    for(let i=0;i<34;i++){const u=((i*0.618)%1),v=((i*0.382+.13)%1),gx=-.42+.68*u+Math.sin(t*.00006+i)*.02,gy=-.3+1.22*v+Math.cos(t*.00005+i)*.02;
      if(Math.hypot(gx,gy)<.95)dot(cx+sx*1.3+gx*R,cy+sy*1.3+gy*R,.6+(i%3)*.35,B,.15)}
    // nucleus position (other parts are placed around it)
    const nx=cx+sx*.5-R*.04+Math.cos(t*.0001)*R*.02,ny=cy+sy*.5+R*.26+Math.sin(t*.00013)*R*.02,nr=R*.13;
    // endoplasmic reticulum: wavy sheets around the nucleus
    ctx.lineWidth=.9;for(let k=0;k<3;k++){const rr=nr*(1.35+k*.28);ctx.globalAlpha=.13-k*.025;ctx.strokeStyle=B;ctx.beginPath();
      for(let a=-1.1+k*.25;a<2.2+k*.25;a+=.06){const w=rr*(1+.06*Math.sin(a*9+t*.0006+k));ctx.lineTo(nx+Math.cos(a)*w,ny+Math.sin(a)*w)}ctx.stroke()}
    // golgi: a stack of short curved cisternae
    {const gx=cx-R*.2,gy=cy-R*.16,ga=-.3;ctx.save();ctx.translate(gx,gy);ctx.rotate(ga);ctx.strokeStyle=B;
      for(let k=0;k<4;k++){ctx.globalAlpha=.24-k*.03;ctx.lineWidth=1.4-k*.15;ctx.beginPath();ctx.arc(0,R*.16,R*(.1+k*.022),-2.2,-.95);ctx.stroke()}
      for(let k=0;k<3;k++)dot(R*(.11+k*.03),R*(.03-k*.02),1.4,B,.2);ctx.restore()}
    // mitochondria with cristae
    const MP=[[.16,-.08],[-.27,.6],[.13,.72],[.2,.4]];for(let i=0;i<4;i++){const a=i*1.7,x=cx+sx+R*MP[i][0]+Math.sin(t*.00008+i)*R*.02,y=cy+sy+R*MP[i][1]+Math.cos(t*.00007+i)*R*.02,ang=a+t*.00015;
      ctx.save();ctx.translate(x,y);ctx.rotate(ang);ctx.globalAlpha=.26;ctx.strokeStyle=B;ctx.lineWidth=1;ctx.beginPath();ctx.ellipse(0,0,R*.07,R*.032,0,0,7);ctx.stroke();
      ctx.globalAlpha=.2;ctx.beginPath();for(let j=-3;j<=3;j++)ctx.lineTo(j*R*.017,(j%2?1:-1)*R*.018);ctx.stroke();ctx.restore()}
    // food vacuoles with digesting contents
    const FP=[[-.13,.86],[-.3,.32]];for(let i=0;i<2;i++){const x=cx+sx+R*FP[i][0]+Math.sin(t*.00006+i)*R*.02,y=cy+sy+R*FP[i][1]+Math.cos(t*.00005+i)*R*.02,r=R*(.06+.015*i);
      ring(x,y,r,B,.2);dot(x+r*.2,y-r*.15,r*.38,Cc,.24);dot(x-r*.3,y+r*.25,r*.16,Cc,.18)}
    // contractile vacuole with feeder canals: fills, then empties
    const fill=reduce?.6:(Math.sin(t*.0012)+1)/2,vx=cx+sx-R*.3,vy=cy+sy+R*.06,vr=R*(.035+.06*fill);
    ctx.strokeStyle=B;ctx.lineWidth=.9;for(let k=0;k<6;k++){const a=k*Math.PI/3+.3;ctx.globalAlpha=.16*(1-fill*.6);ctx.beginPath();ctx.moveTo(vx+Math.cos(a)*vr*1.3,vy+Math.sin(a)*vr*1.3);ctx.lineTo(vx+Math.cos(a)*R*.17,vy+Math.sin(a)*R*.17);ctx.stroke()}
    dot(vx,vy,vr,B,.1+.12*fill);ring(vx,vy,vr,B,.26);
    // nucleus: envelope with pores, nucleolus, chromatin
    dot(nx,ny,nr,Cc,.07);
    ctx.globalAlpha=.3;ctx.strokeStyle=Cc;ctx.lineWidth=1.2;ctx.setLineDash([R*.03,R*.01]);ctx.beginPath();ctx.arc(nx,ny,nr,0,7);ctx.stroke();ctx.setLineDash([]);
    dot(nx+nr*.25,ny-nr*.2,nr*.3,Cc,.36);
    for(let k=0;k<9;k++){const a=k*2.2+t*.0002,d=nr*(.25+.5*((k*37)%10)/10);dot(nx+Math.cos(a)*d,ny+Math.sin(a)*d,.9,Cc,.3)}
    // engulfed food: forms where you clicked, drifts to the nucleus, is digested
    am.food=am.food.filter(f=>now-f.t0<4200);
    for(const f of am.food){const u=clamp((now-f.t0)/4200),e=ease(clamp(u/.7)),x=lerp(f.x,nx-nr*1.2,e),y=lerp(f.y,ny+nr*.7,e),r=R*.065*(u<.08?u/.08:1)*(1-clamp((u-.6)/.4)*.85);
      ring(x,y,r,B,.5*(1-clamp((u-.75)/.25)));dot(x,y,r*.45,Cc,.55*(1-clamp((u-.5)/.5)))}
    ctx.globalAlpha=1;
  }

  function frame(now){
    tNow=now;if(!W)return;
    const k=Math.min(3,(now-(lastF||now))/16.7)||1;lastF=now;
    if(+(stage.dataset.cover||0)>.98)return;
    ctx.clearRect(0,0,W,H);ctx.globalAlpha=1;ctx.drawImage(lat,0,0,W,H);
    drawAmoeba(now);
    if(hover){ctx.globalAlpha=.55;ctx.strokeStyle=col.blue;ctx.lineWidth=1.2;hexPath(ctx,hover.x,hover.y);ctx.stroke()}
    // turning the wheel throws tasks from the hub onto nodes, the way it turns; at rest only the odd one
    const om=wheelState.om,spin=Math.abs(om),busy=spin>.5;
    if(!reduce&&(busy||!flows.length)&&now-lastRing>(busy?Math.max(320,2600/spin):6000)&&rings.length<(busy?9:1)){lastRing=now;
      const ang=Math.random()*Math.PI*2,rad=(.22+Math.random()*(busy?Math.min(1,.45+spin/14):.6))*Math.min(W,H)*.62,h=nearest(fx+Math.cos(ang)*rad,fy+Math.sin(ang)*rad);
      if(h&&!rings.some(r=>r.x===h.x&&r.y===h.y)){const fly=busy?520:0;if(busy)fliers.push({x:h.x,y:h.y,t0:now,dur:fly});ring(h.x,h.y,false,fly,(busy?.22+Math.min(spin,20)*.012:.2)*(om<0?-1:1))}}
    rings=rings.filter(p=>now-p.t0<p.dur);for(const p of rings)drawRing(p,now);
    if(!reduce&&now-lastFlow>7000&&flows.length<2){lastFlow=now;spawnFlow(now)}
    drawFlows(now);
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
  stage.addEventListener("pointermove",e=>{if(!W)return;const r=stage.getBoundingClientRect(),y=e.clientY-r.top,x=e.clientX-r.left;
    am.on=onLattice(e)&&inAmoeba(x,y);if(am.on){am.px=x;am.py=y}stage.classList.toggle("amoeba-hover",am.on);const ok=onLattice(e)&&!am.on;
    if(e.pointerType==="mouse")helixHot=ok&&Math.abs(y-helixY)<Acur+60;hover=ok&&!helixHot?nearest(e.clientX-r.left,y):null;stage.classList.toggle("lat-hover",!!hover);if(reduce)frame(performance.now())});
  let hotTimer=0;B_.add(()=>clearTimeout(hotTimer));stage.addEventListener("pointerdown",e=>{if(e.pointerType==="mouse"||!W)return;const r=stage.getBoundingClientRect(),y=e.clientY-r.top;
    if(onLattice(e)&&Math.abs(y-helixY)<Acur+60){helixHot=!helixHot;clearTimeout(hotTimer);if(helixHot)hotTimer=setTimeout(()=>{helixHot=false;if(reduce)frame(performance.now())},5000);if(reduce)frame(performance.now())}});
  stage.addEventListener("pointerleave",e=>{am.on=false;stage.classList.remove("amoeba-hover");if(e.pointerType!=="mouse")return;hover=null;helixHot=false;stage.classList.remove("lat-hover");if(reduce)frame(performance.now())});
  stage.addEventListener("click",e=>{if(!onLattice(e)||!W||helixHot)return;const r=stage.getBoundingClientRect();
    if(inAmoeba(e.clientX-r.left,e.clientY-r.top)){if(am.food.length<4)am.food.push({x:e.clientX-r.left,y:e.clientY-r.top,t0:performance.now()});if(reduce)frame(performance.now());return}
    const h=nearest(e.clientX-r.left,e.clientY-r.top);
    ring(h.x,h.y,true);
    [[0,-1],[0,1],[-1,h.r%2?1:-1]].forEach(([dr,dc],i)=>{const[x,y]=center(h.r+dr,h.c+dc);ring(x,y,false,300+i*220)});
    if(reduce)frame(performance.now()+400)});
  B_.on(window,"resize",size);B_.add(onThemeChange(()=>{colors();buildLattice();if(reduce)frame(performance.now())}));
  size();
  if(reduce)frame(performance.now());else B_.add(whileVisible(stage,frame));
}


/* ---------- home sections stack: each stays put while the next slides over it ---------- */
/* ---------- behind "How a task runs": the world, with tasks arriving at Poiesis deployments in several regions ---------- */
// land: Natural Earth 110m (public domain) rasterised to a 144x52 grid, lat 76 to -56
const LAND={cols:144,rows:52,lat0:76,lat1:-56,b64:"AAAAEB8Af/8AAAADAB/4ARAAAAADfY/AP/wAAAAECf//8PAAAf4Yf6N4L/4AAPAAn/////8OP////////////ADgBAAAAAAAJv////p8HwHAD7z/////////A////+JgDgAAPn////////++AfD//8BwAAAAPh////////yAACAf/+B+AAACBj///////wGAAgAP//7/gAAHEP///////AOAAAAH//7/wAALv////////4AAAAAH///6QAAA/////////0AAAAAD///8IAAB/////////wAAAAAD///6AAAB+/Xn/////gAAAAAD///wAAAPlOBn////8IAAAAAD///AAAAPEp/3////IIAAAAAB//+AAAAOBB/z////kQAAAAAA//+AAAAH8AP/////BwAAAAAAf/8AAAAP/IP/////iAAAAAAAH/EAAAAP///v////gAAAAAAAL4EAAAAf//v3////AAAAAAAAF4AAAAA///36H///gAAAAAAAA4OAAAB///7/D/f4AAAAAAAAA4gQAAB///7+B8fAAAAAAAAAAPgAAAB///98B4PggAAAAAAAAB4AAAB///9wAwHwgAAAAAAAAAYAAAB///+AAwFwgAAAAAAAAAIuAAA////wAQEhAAAAAAAAAAB/gAAf///wAIAAIAAAAAAAAAB/4AAIP//gAAKCAAAAAAAAAAB/8AAAD//AAAFGAAAAAAAAAAD/+AAAD/+AAACOAAAAAAAAAAD//gAAD/8AAABOh4gAAAAAAAD//8AAB/8AAAAAAcgAAAAAAAD//8AAB/8AAAAMAeEAAAAAAAB//8AAB/8AAAAAQBAAAAAAAAB//4AAB/8AAAAADgAAAAAAAAA//wAAB/8QAAAAPEAAAAAAAAAf/wAAB/4wAAAAf8AAAAAAAAAP/wAAB/wgAAAA/+AAAAAAAAAP/gAAA/xgAAAD//AAAAAAAAAP+AAAA/gAAAAD//gAAAAAAAAP+AAAA/gAAAAD//gAAAAAAAAf8AAAAfAAAAAD//gAAAAAAAAf4AAAAeAAAAADw/gAAAAAAAAfgAAAAAAAAAAAAfAEAAAAAAAfgAAAAAAAAAAAAPACAAAAAAAeAAAAAAAAAAAAAAACAAAAAAA8AAAAAAAAAAAAACAIAAAAAAA4AAAAAAAAAAAAAAAQAAAAAAA8AAAAAAAAAAAAAAAAAAAAAAA4AAAAAAAAAAAAAAAAAAAAAAA4AAAAAAAAAAAAAAAA"};
function worldBg(){
  const sec=$("#s-task"),cv=$("#world");if(!cv)return;const ctx=cv.getContext("2d");
  let W=0,H=0,dpr=1,col={},dots=[],sites=[],flights=[],last=0,ox=0,oy=0,sc=1;
  const bin=atob(LAND.b64),bit=i=>(bin.charCodeAt(i>>3)>>(7-(i&7)))&1;
  const SITES=[[8.7,50.1],[-77,39],[-122,45.5],[72.9,19],[103.8,1.3],[-46.6,-23.5],[151,-33.9]];
  const colors=()=>{col={dot:css("--line-strong"),blue:css("--blue"),coral:css("--coral"),muted:css("--muted")}};
  const proj=(lon,lat)=>[ox+(lon+180)/360*sc,oy+(LAND.lat0-lat)/(LAND.lat0-LAND.lat1)*sc*(LAND.lat0-LAND.lat1)/360];
  function size(){const r=sec.getBoundingClientRect();if(!r.width)return;dpr=Math.min(2,devicePixelRatio||1);W=r.width;H=r.height;cv.width=W*dpr;cv.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);
    sc=W*(W>760?1.02:1.6);const mh=sc*(LAND.lat0-LAND.lat1)/360;ox=(W-sc)/2;oy=Math.max(0,(H-mh)/2);
    dots=[];const cw=sc/LAND.cols;for(let r=0;r<LAND.rows;r++)for(let c=0;c<LAND.cols;c++)if(bit(r*LAND.cols+c)){const x=ox+(c+.5)*cw,y=oy+(r+.5)*cw,d=Math.hypot((x-W/2)/(W*.42),(y-H*.42)/(H*.5));dots.push([x,y,.12+.3*clamp((d-.3)/.55)])}
    sites=SITES.map(([lon,lat])=>({xy:proj(lon,lat),pulse:0}));colors()}
  const near=(x,y)=>sites.reduce((b,s)=>Math.hypot(s.xy[0]-x,s.xy[1]-y)<Math.hypot(b.xy[0]-x,b.xy[1]-y)?s:b);
  const arc=(a,b,u)=>{const mx=(a[0]+b[0])/2,my=(a[1]+b[1])/2-Math.hypot(b[0]-a[0],b[1]-a[1])*.22,q=1-u;return[q*q*a[0]+2*q*u*mx+u*u*b[0],q*q*a[1]+2*q*u*my+u*u*b[1]]};
  function frame(now){
    if(!W)return;ctx.clearRect(0,0,W,H);const rr=Math.max(.8,sc/LAND.cols*.16),cxm=W/2,cym=H*.45,fr=Math.hypot(W,H)*.5;
    ctx.fillStyle=col.dot;for(const[x,y,a]of dots){ctx.globalAlpha=a;ctx.beginPath();ctx.arc(x,y,rr,0,7);ctx.fill()}
    if(!reduce&&now-last>1400&&flights.length<4){last=now;const a=dots[Math.floor(Math.random()*dots.length)],s=near(a[0],a[1]);
      if(Math.hypot(s.xy[0]-a[0],s.xy[1]-a[1])>sc*.04)flights.push({a,s,t0:now,dur:2600+Math.random()*1200})}
    flights=flights.filter(f=>{const u=(now-f.t0)/f.dur;if(u>1.5)return false;const e=ease(clamp(u)),fade=1-clamp((u-1)/.5);
      ctx.globalAlpha=.45*fade;ctx.strokeStyle=col.muted;ctx.lineWidth=1;ctx.beginPath();ctx.arc(f.a[0],f.a[1],2.6,0,7);ctx.stroke();
      ctx.globalAlpha=.32*fade;ctx.strokeStyle=col.coral;ctx.lineWidth=1;ctx.setLineDash([2,4]);ctx.beginPath();for(let v=0;v<=e;v+=.025){const[x,y]=arc(f.a,f.s.xy,v);v?ctx.lineTo(x,y):ctx.moveTo(x,y)}ctx.stroke();ctx.setLineDash([]);
      if(u<1){const[x,y]=arc(f.a,f.s.xy,e);ctx.globalAlpha=.9;ctx.fillStyle=col.coral;ctx.beginPath();ctx.arc(x,y,2.6,0,7);ctx.fill()}else if(!f.hit){f.hit=1;f.s.pulse=now}
      return true});
    for(const s of sites){const[x,y]=s.xy,k=clamp((now-s.pulse)/1100);
      if(s.pulse&&k<1){ctx.globalAlpha=(1-ease(k))*.45;ctx.strokeStyle=col.blue;ctx.lineWidth=1.1;ctx.beginPath();ctx.arc(x,y,4+ease(k)*18,0,7);ctx.stroke()}
      ctx.globalAlpha=.16;ctx.fillStyle=col.blue;ctx.beginPath();ctx.arc(x,y,8,0,7);ctx.fill();ctx.globalAlpha=.9;ctx.beginPath();ctx.arc(x,y,2.8,0,7);ctx.fill()}
    ctx.globalAlpha=1}
  const ro=new ResizeObserver(()=>{size();if(reduce)frame(performance.now())});ro.observe(sec);B_.add(()=>ro.disconnect());
  B_.add(onThemeChange(()=>{colors();if(reduce)frame(performance.now())}));
  size();if(reduce)frame(performance.now());else B_.add(whileVisible(sec,frame));
}

function stack(){
  const layers=["#stage","#s-eng","#s-task"].map(q=>$(q)),on=()=>true,NAV=()=>innerWidth>=960?64:0,T=[],T0=[];
  const tops=()=>{let acc=64;layers.forEach((el,i)=>{T[i]=on()?Math.min(NAV(),innerHeight-el.offsetHeight):0;el.style.top=on()?T[i]+"px":"";T0[i]=acc;acc+=el.offsetHeight-24})};
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

  wheel();heroBg();worldBg();enginePlay();const stackRefresh=stack();
  requestAnimationFrame(()=>{stackRefresh();window.dispatchEvent(new Event("resize"))});
  B_.add(()=>{root.querySelectorAll(".li").forEach(li=>{li.style.opacity="";li.style.transform=""})});
  return()=>B_.dispose();
}
