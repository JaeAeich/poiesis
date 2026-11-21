import { esc, lerp, clamp, ease, css, reducedMotion, whileVisible, onThemeChange, logoParts, bag } from "./core.js";

const TSTEPS=[
  {lbl:"Submit",cap:"The engine sends <code>POST /tasks</code>. Poiesis stores it as <code>QUEUED</code> and creates one Pod and a volume of the size it asked for. <code>trec</code> starts first and marks it <code>RUNNING</code>."},
  {lbl:"Stage in",cap:"<code>tif</code> copies the inputs from object storage onto the volume."},
  {lbl:"exec-0",cap:"Executors run in order, in your image, with your command."},
  {lbl:"exec-1",cap:"Each executor reads what the one before it wrote."},
  {lbl:"Stage out",cap:"<code>tof</code> uploads the outputs."},
  {lbl:"Clean up",cap:"The Pod succeeds and <code>tctl</code> writes <code>COMPLETE</code>. After <code>retainAfterSeconds</code> the Job and volume are deleted."},
];
export function taskFigure(host,{compact=false}={}){
  const reduce=reducedMotion();
  const narrow=host.clientWidth>0&&host.clientWidth<600;
  const C=[["tif","stage in"],["exec-0","bwa mem"],["exec-1","samtools"],["tof","stage out"]],FILES=["reads.fq","aligned.sam","sorted.bam"];
  const L=narrow?{vb:"0 0 360 580",bin:[132,24],bout:[132,474],pod:[16,124,328,320],podLbl:[30,148],badge:[226,132],
      c:i=>[30+(i%2)*154,162+Math.floor(i/2)*72,146,62],cw:false,vol:[30,312,300,116],volLbl:[44,334],volTxt:[316,334],volTxtS:"25 Gi",f:i=>[40+i*96,356,88,30],
      win:"M180 100V124",wout:"M180 444V474",inA:[180,60],outB:[180,512]}
    :{vb:"0 0 800 280",bin:[22,116],bout:[682,116],pod:[170,22,460,238],podLbl:[186,46],badge:[512,31],
      c:i=>[186+i*110,62,98,62],cw:true,vol:[186,160,428,84],volLbl:[200,182],volTxt:[600,182],volTxtS:"25 Gi · /inputs /work /outputs",f:i=>[200+i*138,196,124,30],
      win:"M118 142H170",wout:"M630 142H682",inA:[70,150],outB:[730,150]};
  const fc=i=>{const[x,y,w,h]=L.f(i);return[x+w/2,y+h/2]};
  const bucket=(id,[x,y],label)=>`<g class="bucket" data-b="${id}"><path d="M${x} ${y}v52a48 10 0 0 0 96 0v-52"/><ellipse cx="${x+48}" cy="${y}" rx="48" ry="10"/><text class="t" x="${x+48}" y="${y+84}" text-anchor="middle">${label}</text><text class="ts" data-bf="${id}" x="${x+48}" y="${y+36}" text-anchor="middle"></text></g>`;
  const[px,py,pw,ph]=L.pod,[bx,by]=L.badge,[vx,vy,vw,vh]=L.vol;
  host.innerHTML=`<div class="tfig ${compact?"compact":""}"><svg viewBox="${L.vb}" role="img" aria-label="How a task runs, step by step">
    ${bucket("in",L.bin,"s3://in")}${bucket("out",L.bout,"s3://out")}
    <path class="wire" data-w="in" d="${L.win}"/><path class="wire" data-w="out" d="${L.wout}"/>
    <rect class="pod" x="${px}" y="${py}" width="${pw}" height="${ph}" rx="10"/>
    <text class="ts" x="${L.podLbl[0]}" y="${L.podLbl[1]}">pod/task-7f3a</text>
    <g class="badge" data-badge><rect x="${bx}" y="${by}" width="104" height="22" rx="11"/><text x="${bx+52}" y="${by+15}" text-anchor="middle">Pending</text></g>
    ${C.map((c,i)=>{const[x,y,w,h]=L.c(i);return L.cw?`<path class="wire" data-cw="${i}" d="M${x+w/2} ${y+h}V${vy}"/>`:`<path class="wire" data-cw="${i}" d="M0 0"/>`}).join("")}
    ${C.map((c,i)=>{const[x,y,w,h]=L.c(i);return`<g data-c="${i}"><rect class="box" x="${x}" y="${y}" width="${w}" height="${h}" rx="6"/>
      <text class="t" x="${x+12}" y="${y+24}">${c[0]}</text><text class="ts" x="${x+12}" y="${y+42}">${c[1]}</text>
      <circle class="dot" cx="${x+w-14}" cy="${y+19}" r="4"/><path class="chk" d="M${x+w-19} ${y+19}l3.5 3.5 6-7"/>
      <rect class="pbg" x="${x+12}" y="${y+h-12}" width="${w-24}" height="3" rx="1.5"/><rect class="pfg" data-p="${i}" data-pw="${w-24}" x="${x+12}" y="${y+h-12}" width="0" height="3" rx="1.5"/></g>`}).join("")}
    <g class="vol" data-vol><rect class="box" x="${vx}" y="${vy}" width="${vw}" height="${vh}" rx="6"/>
      <text class="t" x="${L.volLbl[0]}" y="${L.volLbl[1]}">volume</text><text class="ts" data-vl x="${L.volTxt[0]}" y="${L.volTxt[1]}" text-anchor="end"></text>
      ${FILES.map((f,i)=>{const[x,y,w,h]=L.f(i);return`<g class="file" data-f="${i}" style="opacity:0"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="5"/><text class="ts" x="${x+w/2}" y="${y+19}" text-anchor="middle" style="fill:var(--fg)">${f}</text></g>`}).join("")}</g>
    <g class="mover" data-m style="opacity:0"><rect x="-50" y="-12" width="100" height="24" rx="5"/><text x="0" y="4" text-anchor="middle"></text></g>
  </svg>
  <div class="tl"><button class="play" aria-label="Pause"></button><div class="segs" style="grid-template-columns:repeat(${TSTEPS.length},1fr)">${TSTEPS.map((s,i)=>`<button class="seg" data-s="${i}" aria-label="Step ${i+1}: ${s.lbl}"><i><b></b></i><span>${s.lbl}</span></button>`).join("")}</div></div>
  <div class="tcap" aria-live="off"><span></span></div></div>`;
  const q=s=>host.querySelector(s),qa=s=>[...host.querySelectorAll(s)];
  const P={c:qa("[data-c]"),cw:qa("[data-cw]"),pf:qa("[data-p]"),f:qa("[data-f]"),vol:q("[data-vol]"),vl:q("[data-vl]"),m:q("[data-m]"),mt:q("[data-m] text"),badge:q("[data-badge]"),bt:q("[data-badge] text"),bin:q('[data-b="in"]'),bout:q('[data-b="out"]'),bfin:q('[data-bf="in"]'),bfout:q('[data-bf="out"]'),win:q('[data-w="in"]'),wout:q('[data-w="out"]'),segs:qa(".seg"),bars:qa(".seg b"),cap:q(".tcap span"),capBox:q(".tcap"),play:q(".play")};
  let k=0,p=0,playing=!reduce,lastCap=-1,last=0,lastPlay=null;const DUR=2600,HOLD=700;
  const PLAY='<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',PAUSE='<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>';
  if(reduce)P.play.hidden=true;
  function apply(){
    const pp=clamp(p);
    P.c.forEach((g,i)=>{const run=i+1,st=k>run?"done":k===run?(pp<.85?"run":"done"):"idle",pw=+P.pf[i].dataset.pw;if(g.getAttribute("class")!==st)g.setAttribute("class",st);
      P.pf[i].setAttribute("width",(st==="run"?pw*ease(clamp(pp/.85)):st==="done"?pw:0).toFixed(1));P.cw[i].classList.toggle("on",st==="run")});
    const phase=k===0?(pp<.5?"Pending":"Running"):k<5?"Running":"Succeeded";
    P.badge.setAttribute("class","badge "+phase);P.bt.textContent={Pending:"QUEUED",Running:"RUNNING",Succeeded:"COMPLETE"}[phase];
    P.vol.style.opacity=k===0?(.15+.85*ease(pp)).toFixed(2):k===5?(pp<.45?1:lerp(1,.2,ease(clamp((pp-.45)/.4)))).toFixed(2):1;
    P.vl.textContent=k===5&&pp>.6?"deleted":L.volTxtS;
    const has=[k>1||(k===1&&pp>.8),k>2||(k===2&&pp>.6),k>3||(k===3&&pp>.6)];
    P.f.forEach((g,i)=>g.style.opacity=has[i]?1:0);
    P.bfin.textContent="reads.fq";P.bfout.textContent=k>4||(k===4&&pp>.82)?"sorted.bam":"";
    let mv=null;
    if(k===1&&pp>.1&&pp<.8)mv={t:"reads.fq",a:L.inA,b:fc(0),u:(pp-.1)/.7};
    if(k===4&&pp>.1&&pp<.82)mv={t:"sorted.bam",a:fc(2),b:L.outB,u:(pp-.1)/.72};
    if(mv){const u=ease(clamp(mv.u)),x=lerp(mv.a[0],mv.b[0],u),y=lerp(mv.a[1],mv.b[1],u)-(narrow?0:Math.sin(Math.PI*u)*36);
      P.m.style.opacity=1;P.m.setAttribute("transform",`translate(${x.toFixed(1)} ${y.toFixed(1)})`);P.mt.textContent=mv.t}else P.m.style.opacity=0;
    P.bin.classList.toggle("on",k===1&&pp<.8);P.bout.classList.toggle("on",k===4&&pp>.5);
    P.win.classList.toggle("on",k===1&&pp<.8);P.wout.classList.toggle("on",k===4&&pp>.4);
    P.segs.forEach((s,i)=>{s.classList.toggle("cur",i===k);s.classList.toggle("past",i<k)});
    P.bars.forEach((b,i)=>b.style.width=i===k?(pp*100).toFixed(1)+"%":i<k?"100%":"0");
    if(lastCap!==k){lastCap=k;P.cap.style.opacity=0;setTimeout(()=>{P.cap.innerHTML=TSTEPS[k].cap;P.cap.style.opacity=1},reduce?0:160)}
    if(lastPlay!==playing){lastPlay=playing;P.play.innerHTML=playing?PAUSE:PLAY;P.play.setAttribute("aria-label",playing?"Pause":"Play");P.capBox.setAttribute("aria-live",playing?"off":"polite")}
  }
  host.addEventListener("click",e=>{const s=e.target.closest(".seg"),pl=e.target.closest(".play");
    if(s){k=+s.dataset.s;p=reduce?1:0;playing=reduce?false:playing;apply()}
    if(pl){playing=!playing;apply()}});
  if(reduce){p=1;apply();return()=>{}}
  apply();
  return whileVisible(host,t=>{const dt=Math.min(50,t-(last||t));last=t;
    if(p<1)p=Math.min(1,p+dt/DUR);else if(playing){p+=dt/DUR;if(p>1+HOLD/DUR){k=(k+1)%TSTEPS.length;p=0}}
    apply()});
}


export function flow(host,spec,opts={}){
  const reduce=reducedMotion();
  const W=opts.wide?600:420,sx=W/420,H=spec.h||250;
  const N=Object.fromEntries(Object.entries(spec.nodes).map(([k,n])=>{const w=n.w||118;return[k,{...n,w,x:n.x*sx+w*(sx-1)/2}]}));
  const box=id=>{const n=N[id];return{x:n.x,y:n.y,w:n.w||118,h:44}};
  const center=id=>{const b=box(id);return[b.x+b.w/2,b.y+b.h/2]};
  const clip=(a,b)=>{const B=box(a),[x1,y1]=center(a),[x2,y2]=center(b),dx=x2-x1,dy=y2-y1,t=Math.min(dx?Math.abs(B.w/2/dx):1e9,dy?Math.abs(B.h/2/dy):1e9);return[x1+dx*t,y1+dy*t]};
  const edges=spec.edges.map(([a,b])=>({a,b,p1:clip(a,b),p2:clip(b,a)}));
  host.innerHTML=`<div class="flow"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(spec.title||"")}">
    ${edges.map((e,i)=>`<line class="ed2" x1="${e.p1[0]}" y1="${e.p1[1]}" x2="${e.p2[0]}" y2="${e.p2[1]}"/>`).join("")}
    ${Object.keys(N).map(id=>{const b=box(id),n=N[id];return`<g class="nd" data-n="${id}"><rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" rx="7"/><text x="${b.x+b.w/2}" y="${b.y+(n.sub?19:26)}" text-anchor="middle">${esc(n.label)}</text>${n.sub?`<text class="s" x="${b.x+b.w/2}" y="${b.y+34}" text-anchor="middle">${esc(n.sub)}</text>`:""}</g>`}).join("")}
    <g class="pk" style="opacity:0"><rect x="0" y="-11" height="22" rx="5"/><text x="0" y="4" text-anchor="middle"></text></g></svg>
    <div class="fcap"><span class="n"></span><span class="c"></span>${reduce?'<button class="btn sm r" data-prev aria-label="Previous step">‹</button><button class="btn sm" data-nx aria-label="Next step">›</button>':'<button class="btn sm r" data-replay>Replay</button>'}</div></div>`;
  const pk=host.querySelector(".pk"),pr=pk.querySelector("rect"),pt=pk.querySelector("text"),capN=host.querySelector(".fcap .n"),capC=host.querySelector(".fcap .c"),lines=[...host.querySelectorAll(".ed2")],nds=[...host.querySelectorAll(".nd")];
  let h=0,u=0,last=0,alive=true;const HOP=1700,HOLD=700;
  const setHop=()=>{const hp=spec.hops[h];capN.textContent=`${h+1}/${spec.hops.length}`;capC.style.opacity=0;setTimeout(()=>{capC.innerHTML=hp.cap;capC.style.opacity=1},reduce?0:120);
    pt.textContent=hp.label;const w=Math.max(44,hp.label.length*6.7+18);pr.setAttribute("x",-w/2);pr.setAttribute("width",w);pk.setAttribute("class","pk "+(hp.tone||""));
    nds.forEach(n=>n.classList.toggle("on",n.dataset.n===hp.f||n.dataset.n===hp.t));
    lines.forEach((l,i)=>l.classList.toggle("on",(edges[i].a===hp.f&&edges[i].b===hp.t)||(edges[i].a===hp.t&&edges[i].b===hp.f)))};
  const place=()=>{const hp=spec.hops[h],a=clip(hp.f,hp.t),b=clip(hp.t,hp.f),e=ease(clamp(u));pk.style.opacity=u<1.02?1:0;
    const my=lerp(a[1],b[1],e),lift=Math.abs(b[0]-a[0])>Math.abs(b[1]-a[1])?(my-34<14?34:-34):0;pk.setAttribute("transform",`translate(${lerp(a[0],b[0],e).toFixed(1)} ${(lerp(a[1],b[1],e)+lift).toFixed(1)})`)};
  setHop();
  const rp=host.querySelector("[data-replay]");if(rp)rp.onclick=()=>{h=0;u=0;setHop()};
  if(reduce){u=.5;place();const n=spec.hops.length;host.querySelector("[data-prev]").onclick=()=>{h=(h-1+n)%n;setHop();place()};host.querySelector("[data-nx]").onclick=()=>{h=(h+1)%n;setHop();place()};return()=>{}}
  const loop=t=>{if(!alive)return;if(!host.isConnected)return;if(!host.offsetParent){last=t;requestAnimationFrame(loop);return}const dt=Math.min(50,t-(last||t));last=t;u+=dt/HOP;
    if(u>1+HOLD/HOP){h=(h+1)%spec.hops.length;u=0;setHop()}place();requestAnimationFrame(loop)};
  requestAnimationFrame(loop);return()=>{alive=false};
}
