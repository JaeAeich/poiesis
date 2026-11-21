import { esc, lerp, clamp, ease, css, reducedMotion, whileVisible, onThemeChange, logoParts, bag } from "./core.js";
import { taskFigure, flow } from "./figures.js";

export function mountDeploy(root,BASE="/"){
  const $=(s,r=root)=>r.querySelector(s), $$=(s,r=root)=>[...r.querySelectorAll(s)];
  const reduce=reducedMotion(), B_=bag();let dead=false;B_.add(()=>{dead=true;termRun++;stopFlow()});
  function toast(t){const el=$("#toast");el.textContent=t;el.classList.add("on");clearTimeout(toast.t);toast.t=setTimeout(()=>el.classList.remove("on"),1600)}
  function copy(text){(navigator.clipboard?navigator.clipboard.writeText(text):Promise.reject()).then(()=>toast("Copied"),()=>toast("Copy failed"))}
/* ---------- configurator state ---------- */
const EX={url:"https://poiesis.example.org",dbSecret:"poiesis-db",s3Endpoint:"https://s3.eu-central-1.amazonaws.com",s3Region:"eu-central-1",s3Secret:"poiesis-s3",issuer:"https://keycloak.example.org/realms/poiesis",pdp:"http://opa.policy.svc:8181/access/v1/evaluation"};
const S={step:0,done:new Set(),ex:new Set(),manual:null,editing:false,openGroup:null,
  url:"",ns:"poiesis",ingress:"",tls:"cm",cmIssuer:"",tlsSecret:"",s3Role:"",dbSecret:"",dbCa:"",
  s3Endpoint:"",s3Region:"",s3Cred:"secret",s3Secret:"",votes:{gcs:41,azure:27,ftp:12,fuse:19,aws:33,gcp:21,azurek:17},voted:{},
  defSize:10,maxSize:100,sc:"",retain:3600,
  chain:[{type:"oidc",issuer:"",aud:"poiesis",clients:"poiesis-cli",jwks:""}],keys:false,
  authz:"owner",userGroup:"",adminGroup:"",pdp:"",sharing:false,trial:null,adv:{}};
// Everything the steps don't ask, with the chart default and a reason to change it.
const ADV=[
  {g:"Service info",items:[
    {k:"serviceInfo.id",lab:"Service id",def:"",ph:"org.ga4gh.poiesis",why:"Tells your deployment apart in registries and policies."},
    {k:"serviceInfo.name",lab:"Display name",def:"",ph:"Poiesis",why:"Shown by clients and registries."},
    {k:"serviceInfo.environment",lab:"Environment",def:"",opts:["","prod","staging","test","dev"],why:"Lets clients tell prod from test."}]},
  {g:"API",items:[
    {k:"api.replicas",lab:"Replicas",def:1,num:1,why:"More replicas for availability."},
    {k:"api.pdb.enabled",lab:"PodDisruptionBudget",def:false,bool:1,why:"Keeps an API Pod up during node drains."},
    {k:"logLevel",lab:"Log level",def:"INFO",opts:["DEBUG","INFO","WARNING","ERROR"],why:"DEBUG while you set things up."}]},
  {g:"API keys",when:()=>S.keys,items:[
    {k:"auth.apiKeys.defaultTtl",lab:"Default lifetime",def:"7d",why:"How long a key lasts if the request names no lifetime."},
    {k:"auth.apiKeys.maxTtl",lab:"Longest lifetime",def:"90d",why:"The longest an owner may ask for."},
    {k:"auth.apiKeys.maxPerOwner",lab:"Keys per owner",def:20,num:1,why:"Active keys one owner may hold."}]},
  {g:"Swagger UI login",when:()=>S.chain.some(l=>l.type==="oidc"&&l.issuer),items:[
    {k:"auth.swaggerUi.clientId",lab:"Public client id",def:"",ph:"poiesis-swagger",why:"Lets users log in at /docs and mint keys in the browser."}]},
  {g:"Task pods",items:[
    {k:"taskpods.namespace",lab:"Task namespace",def:"",ph:"same as release",why:"Runs tasks apart from the control plane."},
    {k:"taskpods.outputGlobFallback",lab:"Upload everything when a glob matches nothing",def:false,bool:1,why:"Off is safer: a typo can't export a whole volume."},
    {k:"taskpods.persistence.rwx",show:"taskpods.persistence.accessModes",lab:"ReadWriteMany volumes",def:false,bool:1,why:"Only if your storage offers nothing else."}]},
  {g:"Security",items:[
    {k:"networkPolicy.enabled",lab:"NetworkPolicy",def:false,bool:1,why:"Limits who can reach the API Pods."},
    {k:"audit.enabled",lab:"Audit log",def:true,bool:1,why:"One JSON line per decision and key event."},
    {k:"authz.adminRead",lab:"Admins can read every task",def:false,bool:1,when:()=>S.authz==="owner"&&S.adminGroup,why:"Off: admins see only their own tasks."},
    {k:"authz.maxOwners",lab:"Most owners per list",def:1000,num:1,when:()=>S.authz==="pdp"&&S.sharing,why:"Caps what one shared list may query."}]},
];
const advVal=it=>it.k in S.adv?S.adv[it.k]:it.def;
const advLive=()=>ADV.filter(g=>!g.when||g.when()).flatMap(g=>g.items.filter(it=>!it.when||it.when()).map(it=>({...it,g:g.g})));
const advChanged=()=>advLive().filter(it=>advVal(it)!==it.def);
const advDefaults=()=>advLive().filter(it=>advVal(it)===it.def);

const LOGO={k8s:'<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#326CE5" d="M10.204 14.35l.007.01-.999 2.413a5.171 5.171 0 0 1-2.075-2.597l2.578-.437.004.005a.44.44 0 0 1 .484.606zm-.833-2.129a.44.44 0 0 0 .173-.756l.002-.011L7.585 9.7a5.143 5.143 0 0 0-.73 3.255l2.514-.725.002-.009zm1.145-1.98a.44.44 0 0 0 .699-.337l.01-.005.15-2.62a5.144 5.144 0 0 0-3.01 1.442l2.147 1.523.004-.002zm.76 2.75l.723.349.722-.347.18-.78-.5-.623h-.804l-.5.623.179.779zm1.5-3.095a.44.44 0 0 0 .7.336l.008.003 2.134-1.513a5.188 5.188 0 0 0-2.992-1.442l.148 2.615.002.001zm10.876 5.97l-5.773 7.181a1.6 1.6 0 0 1-1.248.594l-9.261.003a1.6 1.6 0 0 1-1.247-.596l-5.776-7.18a1.583 1.583 0 0 1-.307-1.34L2.1 5.573c.108-.47.425-.864.863-1.073L11.305.513a1.606 1.606 0 0 1 1.385 0l8.345 3.985c.438.209.755.604.863 1.073l2.062 8.955c.108.47-.005.963-.308 1.34zm-3.289-2.057c-.042-.01-.103-.026-.145-.034-.174-.033-.315-.025-.479-.038-.35-.037-.638-.067-.895-.148-.105-.04-.18-.165-.216-.216l-.201-.059a6.45 6.45 0 0 0-.105-2.332 6.465 6.465 0 0 0-.936-2.163c.052-.047.15-.133.177-.159.008-.09.001-.183.094-.282.197-.185.444-.338.743-.522.142-.084.273-.137.415-.242.032-.024.076-.062.11-.089.24-.191.295-.52.123-.736-.172-.216-.506-.236-.745-.045-.034.027-.08.062-.111.088-.134.116-.217.23-.33.35-.246.25-.45.458-.673.609-.097.056-.239.037-.303.033l-.19.135a6.545 6.545 0 0 0-4.146-2.003l-.012-.223c-.065-.062-.143-.115-.163-.25-.022-.268.015-.557.057-.905.023-.163.061-.298.068-.475.001-.04-.001-.099-.001-.142 0-.306-.224-.555-.5-.555-.275 0-.499.249-.499.555l.001.014c0 .041-.002.092 0 .128.006.177.044.312.067.475.042.348.078.637.056.906a.545.545 0 0 1-.162.258l-.012.211a6.424 6.424 0 0 0-4.166 2.003 8.373 8.373 0 0 1-.18-.128c-.09.012-.18.04-.297-.029-.223-.15-.427-.358-.673-.608-.113-.12-.195-.234-.329-.349-.03-.026-.077-.062-.111-.088a.594.594 0 0 0-.348-.132.481.481 0 0 0-.398.176c-.172.216-.117.546.123.737l.007.005.104.083c.142.105.272.159.414.242.299.185.546.338.743.522.076.082.09.226.1.288l.16.143a6.462 6.462 0 0 0-1.02 4.506l-.208.06c-.055.072-.133.184-.215.217-.257.081-.546.11-.895.147-.164.014-.305.006-.48.039-.037.007-.09.02-.133.03l-.004.002-.007.002c-.295.071-.484.342-.423.608.061.267.349.429.645.365l.007-.001.01-.003.129-.029c.17-.046.294-.113.448-.172.33-.118.604-.217.87-.256.112-.009.23.069.288.101l.217-.037a6.5 6.5 0 0 0 2.88 3.596l-.09.218c.033.084.069.199.044.282-.097.252-.263.517-.452.813-.091.136-.185.242-.268.399-.02.037-.045.095-.064.134-.128.275-.034.591.213.71.248.12.556-.007.69-.282v-.002c.02-.039.046-.09.062-.127.07-.162.094-.301.144-.458.132-.332.205-.68.387-.897.05-.06.13-.082.215-.105l.113-.205a6.453 6.453 0 0 0 4.609.012l.106.192c.086.028.18.042.256.155.136.232.229.507.342.84.05.156.074.295.145.457.016.037.043.09.062.129.133.276.442.402.69.282.247-.118.341-.435.213-.71-.02-.039-.045-.096-.065-.134-.083-.156-.177-.261-.268-.398-.19-.296-.346-.541-.443-.793-.04-.13.007-.21.038-.294-.018-.022-.059-.144-.083-.202a6.499 6.499 0 0 0 2.88-3.622c.064.01.176.03.213.038.075-.05.144-.114.28-.104.266.039.54.138.87.256.154.06.277.128.448.173.036.01.088.019.13.028l.009.003.007.001c.297.064.584-.098.645-.365.06-.266-.128-.537-.423-.608zM16.4 9.701l-1.95 1.746v.005a.44.44 0 0 0 .173.757l.003.01 2.526.728a5.199 5.199 0 0 0-.108-1.674A5.208 5.208 0 0 0 16.4 9.7zm-4.013 5.325a.437.437 0 0 0-.404-.232.44.44 0 0 0-.372.233h-.002l-1.268 2.292a5.164 5.164 0 0 0 3.326.003l-1.27-2.296h-.01zm1.888-1.293a.44.44 0 0 0-.27.036.44.44 0 0 0-.214.572l-.003.004 1.01 2.438a5.15 5.15 0 0 0 2.081-2.615l-2.6-.44-.004.005z"/></svg>',aws:'<img class="lt" src="'+BASE+'logos/aws-light.svg" alt=""><img class="dk" src="'+BASE+'logos/aws.svg" alt="">',gc:'<img src="'+BASE+'logos/google-cloud.svg" alt="">',az:'<img src="'+BASE+'logos/azure.svg" alt="">',s3:'<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#569A31" d="M20.913 13.147l.12-.895c.947.576 1.258.922 1.354 1.071-.16.031-.562.046-1.474-.176zm-2.174 7.988a.547.547 0 0 0-.005.073c0 .084-.207.405-1.124.768a10.28 10.28 0 0 1-1.438.432c-1.405.325-3.128.504-4.853.504-4.612 0-7.412-1.184-7.412-1.704a.547.547 0 0 0-.005-.073L1.81 5.602c.135.078.28.154.432.227.042.02.086.038.128.057.134.062.272.122.417.18l.179.069c.154.058.314.114.478.168.043.013.084.029.13.043.207.065.423.127.646.187l.176.044c.175.044.353.087.534.127a23.414 23.414 0 0 0 .843.17l.121.023c.252.045.508.085.768.122.071.011.144.02.216.03.2.027.4.053.604.077l.24.027c.245.026.49.05.74.07l.081.009c.275.022.552.04.83.056l.233.012c.21.01.422.018.633.025a33.088 33.088 0 0 0 2.795-.026l.232-.011c.278-.016.555-.034.83-.056l.08-.008c.25-.02.497-.045.742-.072l.238-.026c.205-.024.408-.05.609-.077.07-.01.141-.019.211-.03.261-.037.519-.078.772-.122l.111-.02c.215-.04.427-.082.634-.125l.212-.047c.186-.041.368-.085.546-.13l.166-.042c.225-.06.444-.122.654-.189.04-.012.077-.026.115-.038a10.6 10.6 0 0 0 .493-.173c.058-.021.114-.044.17-.066.15-.06.293-.12.43-.185.038-.017.079-.034.116-.052.153-.073.3-.15.436-.228l-.976 7.245c-2.488-.78-5.805-2.292-7.311-3a1.09 1.09 0 0 0-1.088-1.085c-.6 0-1.088.489-1.088 1.088 0 .6.488 1.089 1.088 1.089.196 0 .378-.056.537-.148 1.72.812 5.144 2.367 7.715 3.15zm-7.42-20.047c5.677 0 9.676 1.759 9.75 2.736l-.014.113c-.01.033-.031.067-.048.101-.015.028-.026.057-.047.087-.024.033-.058.068-.09.102-.028.03-.051.06-.084.09-.038.035-.087.07-.133.105-.04.03-.074.06-.119.091-.053.036-.116.071-.177.107-.05.03-.095.06-.15.09-.068.036-.147.073-.222.11-.059.028-.114.057-.177.085-.084.038-.177.074-.268.111-.068.027-.13.054-.203.082-.097.036-.205.072-.31.107-.075.026-.148.053-.228.079-.111.035-.233.069-.35.103-.085.024-.165.05-.253.073-.124.034-.258.065-.389.098-.093.022-.181.046-.278.068-.139.032-.287.061-.433.091-.098.02-.191.041-.293.06-.155.03-.32.057-.482.084-.1.018-.198.036-.302.052-.166.026-.342.048-.515.072-.11.014-.213.03-.325.044-.181.023-.372.041-.56.06-.11.012-.218.025-.332.036-.188.016-.386.029-.58.043-.122.009-.24.02-.364.028-.207.012-.422.02-.635.028-.12.005-.234.012-.354.016a35.605 35.605 0 0 1-2.069 0c-.12-.004-.234-.011-.352-.016-.214-.008-.43-.016-.637-.028-.122-.008-.238-.02-.36-.027-.195-.015-.394-.028-.584-.044-.11-.01-.215-.024-.324-.035-.19-.02-.384-.038-.568-.06l-.315-.044c-.176-.024-.355-.046-.525-.073-.1-.015-.192-.033-.29-.05-.167-.028-.335-.055-.494-.086-.096-.018-.183-.038-.276-.056-.151-.032-.305-.062-.45-.095-.09-.02-.173-.043-.26-.064-.138-.034-.277-.067-.407-.102-.082-.022-.157-.046-.235-.069a11.75 11.75 0 0 1-.368-.108c-.075-.024-.141-.049-.213-.073-.11-.037-.223-.075-.325-.113-.067-.025-.125-.051-.188-.077-.096-.038-.195-.076-.282-.115-.06-.027-.11-.054-.166-.08-.08-.039-.162-.077-.233-.116-.052-.028-.094-.055-.142-.084-.063-.038-.13-.075-.185-.113-.043-.029-.075-.058-.113-.086-.048-.037-.098-.073-.139-.11-.032-.029-.054-.057-.08-.087-.033-.035-.069-.07-.093-.104-.02-.03-.031-.058-.046-.086-.018-.035-.039-.068-.049-.102l-.015-.113c.076-.977 4.074-2.736 9.748-2.736zm12.182 12.124c-.118-.628-.84-1.291-2.31-2.128l.963-7.16a.531.531 0 0 0 .005-.073C22.16 1.581 16.447 0 11.32 0 6.194 0 .482 1.581.482 3.851a.58.58 0 0 0 .005.072L2.819 21.25c.071 2.002 5.236 2.75 8.5 2.75 1.805 0 3.615-.188 5.098-.531.598-.138 1.133-.3 1.592-.48 1.18-.467 1.789-1.053 1.813-1.739l.945-7.018c.557.131 1.016.197 1.389.197.54 0 .902-.137 1.134-.413a.956.956 0 0 0 .21-.804Z"/></svg>',gcs:'<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M24 2.4v8.4h-2.4V2.4H24zM0 10.8h2.4V2.4H0v8.4zm3-8.4h18v8.4H3V2.4zm12.6 4.2a1.8 1.8 0 1 0 3.6 0 1.8 1.8 0 0 0-3.6 0zm-10.8.6H12V6H4.8v1.2zm16.8 14.4H24v-8.4h-2.4v8.4zM0 21.6h2.4v-8.4H0v8.4zm3-8.4h18v8.4H3v-8.4zm12.6 4.2a1.8 1.8 0 1 0 3.6 0 1.8 1.8 0 0 0-3.6 0zM4.8 18H12v-1.2H4.8V18z"/></svg>'};
const STEPDEF=[
  {id:"basics",t:"Basics",sum:()=>S.url||"public URL"},
  {id:"db",t:"Database",sum:()=>S.dbSecret?`Secret ${S.dbSecret}`:"Postgres"},
  {id:"storage",t:"Storage",sum:()=>S.s3Region?`S3 · ${S.s3Region}`:"S3"},
  {id:"vol",t:"Task volumes",sum:()=>`${S.defSize}–${S.maxSize} Gi`},
  {id:"authn",t:"Authentication",sum:()=>`${S.chain.length} issuer${S.chain.length===1?"":"s"}${S.keys?" + API keys":""}`},
  {id:"authz",t:"Authorization",sum:()=>S.authz==="owner"?"owner only":"decision service"},
  {id:"adv",t:"Advanced",opt:1,sum:()=>{const n=advChanged().length;return n?`${n} changed`:"chart defaults"}},
  {id:"review",t:"Review",sum:()=>""},
];
const LAST=STEPDEF.length-1,ADVI=LAST-1;
const ICON={up:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 15l6-6 6 6"/></svg>',down:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>',x:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6 6 18"/></svg>',thumb:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 10v11H3V10zM7 10l4-8a3 3 0 0 1 3 3v4h6a2 2 0 0 1 2 2.3l-1.4 8A2 2 0 0 1 18.6 21H7"/></svg>',play:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M10 8.5v7l5.5-3.5z" fill="currentColor"/></svg>',copy:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h9"/></svg>',file:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M14 3H6v18h12V7z"/><path d="M14 3v4h4"/></svg>'};

const INFO={
  cmIssuer:"The cert-manager ClusterIssuer that signs the certificate, such as letsencrypt.",
  tlsSecret:"A kubernetes.io/tls Secret holding the certificate for the host.",
  s3Role:"Written as eks.amazonaws.com/role-arn on the API and TaskPod service accounts, so tif and tof get S3 access through IRSA.",
  url:"The address clients use, such as https://poiesis.example.org. It is also the OAuth resource identifier, so a client that only knows this URL can find your issuers.",
  ns:"The Kubernetes namespace the chart installs into. Tasks run here too, unless you set a task namespace under Advanced.",
  ingress:"Which ingress controller serves the API, such as nginx or traefik. Leave empty for the cluster default.",
  dbSecret:"A Secret in the namespace with one key, DATABASE_URL, for example postgresql://user:pass@host:5432/poiesis. The chart reads it; it never creates it.",
  dbCa:"A ConfigMap with a ca.crt key, used to verify Postgres's TLS certificate.",
  s3Endpoint:"Only for S3-compatible stores such as MinIO, Ceph or SeaweedFS. Leave empty for AWS.",
  s3Secret:"A Secret with AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY.",
  sc:"Which StorageClass provisions task volumes. Empty uses the cluster default.",
  retain:"How long a finished task's Job and volume are kept for debugging before Kubernetes deletes them.",
  pdp:"An OpenID AuthZEN 1.0 evaluation endpoint, from OPA, Cerbos or your own service. Poiesis asks it about every action.",
  userGroup:"Callers must have this value in their groups claim, or they get 403.",
  adminGroup:"Members of this group can list and revoke anyone's API keys.",
  c_issuer:"Exactly the iss of the tokens. Poiesis finds the keys through its /.well-known/openid-configuration.",
  c_aud:"The aud value tokens must carry for this Poiesis. Usually set as an audience mapper in your identity provider.",
  c_clients:"OAuth clients whose tokens are accepted, comma-separated. Empty accepts any client of the issuer.",
  c_jwks:"Where the gateway publishes its signing keys. Used instead of OIDC discovery.",
};
const infoBtn=(l,id)=>`<button type="button" class="ib" data-info aria-label="About ${l}" aria-expanded="false" aria-controls="p-${id}">?</button>`,popEl=(t,id)=>`<div class="pop" id="p-${id}" role="tooltip">${t}</div>`;
const field=(key,label,k,{req,ph,hint,type="text"}={})=>`<div class="f" id="w-${key}"><div class="lab"><label for="f-${key}">${label}${req?' <span class="req" aria-hidden="true">*</span>':""}</label>${INFO[key]?infoBtn(label,key):""}${k?`<span class="k" title="${k}">${k}</span>`:""}</div>${INFO[key]?popEl(INFO[key],key):""}<input id="f-${key}" type="${type}" data-bind="${key}" ${req?'aria-required="true"':""} ${INFO[key]?`aria-describedby="p-${key}"`:""} value="${esc(S[key]??"")}" placeholder="${esc(ph||"")}" class="${S.ex.has(key)?"ex":""}">${hint?`<div class="hint">${hint}</div>`:""}</div>`;
const why=t=>`<div class="why"><p>${t}</p><button class="explain-btn" data-explain>${ICON.play}How it works</button></div>`;
const acts=i=>i<LAST?`<div class="acts"><button class="btn primary sm" data-next>${i===ADVI?"Review":"Continue"}</button>${STEPDEF[i].opt?"":`<button class="btn sm" data-example>Use example values</button>`}</div>`:"";

function body(id,i){
  if(id==="basics")return why("Where Poiesis runs, and the URL people use to reach it.")+
    `<div class="tiles"><button class="tile sel"><span class="lg logo">${LOGO.k8s}</span><span><b>Any Kubernetes</b><small>EKS, GKE, AKS, k3s, bare metal</small></span></button>
    ${[[LOGO.aws,"AWS preset"],[LOGO.gc,"Google Cloud preset"],[LOGO.az,"Azure preset"]].map(([l,n])=>`<div class="tile soon"><span class="lg logo">${l}</span><span><b>${n}</b><small>Planned, with its storage</small></span></div>`).join("")}</div>`+
    field("url","Public URL","auth.resource",{req:1,ph:"https://poiesis.example.org",hint:"Also the ingress host."})+
    `<div class="sublab">TLS</div><div class="seg2" role="group" aria-label="TLS">${[["cm","cert-manager"],["secret","Existing Secret"],["none","Terminated upstream"]].map(([k,n])=>`<button data-tls="${k}" class="${S.tls===k?"on":""}" aria-pressed="${S.tls===k}">${n}</button>`).join("")}</div>`+
    (S.tls==="cm"?field("cmIssuer","ClusterIssuer","cert-manager.io/cluster-issuer",{req:1,ph:"letsencrypt"}):S.tls==="secret"?field("tlsSecret","TLS Secret","api.ingress.tls[].secretName",{req:1,ph:"poiesis-tls"}):"")+`<div class="row2">${field("ns","Namespace","",{req:1})}${field("ingress","Ingress class","api.ingress.className",{ph:"cluster default"})}</div>`+acts(i);
  if(id==="db")return why("Poiesis stores tasks in Postgres. You create the Secret; the chart never does.")+
    field("dbSecret","Secret with DATABASE_URL","database.existingSecret",{req:1,ph:"poiesis-db"})+field("dbCa","CA ConfigMap","database.caConfigmap",{ph:"optional",hint:"For <code>sslmode=verify-full</code>."})+acts(i);
  if(id==="storage"){const soon=[[LOGO.gcs,"Google Cloud Storage",29],[LOGO.az,"Azure Blob",29],["FTP","FTP / SFTP",29],["FS","FUSE mounts",27]];
    return why("Where task inputs come from and outputs go.")+
    `<div class="tiles"><button class="tile sel"><span class="lg logo">${LOGO.s3}</span><span><b>S3-compatible</b><small>AWS, MinIO, Ceph, SeaweedFS</small></span></button>
    ${soon.map(([l,n,iss])=>`<div class="tile soon"><span class="lg ${l.length>4?"logo":""}">${l}</span><span><b>${n}</b><small>Planned · #${iss}</small></span></div>`).join("")}</div>`+
    field("s3Endpoint","Endpoint","s3.endpoint",{ph:"empty for AWS"})+field("s3Region","Region","s3.region",{req:1,ph:"eu-central-1"})+
    `<div class="seg2" role="group" aria-label="Credentials"><button data-cred="secret" aria-pressed="${S.s3Cred==="secret"}" class="${S.s3Cred==="secret"?"on":""}">Access key Secret</button><button data-cred="irsa" aria-pressed="${S.s3Cred==="irsa"}" class="${S.s3Cred==="irsa"?"on":""}">Workload identity</button></div>`+
    (S.s3Cred==="secret"?field("s3Secret","Secret name","s3.existingSecret",{req:1,ph:"poiesis-s3"}):field("s3Role","IAM role ARN","serviceAccount.*.annotations",{req:1,ph:"arn:aws:iam::123456789012:role/poiesis",hint:"EKS IRSA. For GCS through its S3 API, use an access key Secret with HMAC keys."}))+acts(i)}
  if(id==="vol")return why("Each task gets its own volume, deleted with the task.")+
    `<div class="row2">${field("defSize","Default size (Gi)","taskpods.persistence.defaultSizeGi",{type:"number"})}${field("maxSize","Largest allowed (Gi)","taskpods.persistence.maxSizeGi",{type:"number"})}</div><div class="row2">${field("sc","StorageClass","taskpods.persistence.storageClass",{ph:"cluster default"})}${field("retain","Keep finished tasks (s)","taskpods.persistence.retainAfterSeconds",{type:"number"})}</div>`+acts(i);
  if(id==="authn")return why("Who may call the API. Each token is checked by the issuer that signed it.")+`<div class="sublab">Trusted issuers</div>`+
    `<ol class="chain">${S.chain.map((l,j)=>`<li class="link ${S.trial&&S.trial.hit===j?"hit":""}"><div class="lh"><span class="tag ${l.type==="gw"?"gw":""}">${l.type==="oidc"?"OIDC":"Gateway"}</span><span class="nm">${esc(l.issuer||"issuer not set")}</span>
      <button class="mini" data-rm="${j}" aria-label="Remove" ${S.chain.length>1?"":"disabled"}>${ICON.x}</button></div><div class="lb">${chainFields(l,j)}</div></li>`).join("")}
      ${S.keys?`<li class="link ${S.trial&&S.trial.hit==="key"?"hit":""}"><div class="lh"><span class="tag key">API keys</span><span class="nm">poi_… for engines, minted by OIDC users</span><button class="mini" data-keys aria-label="Turn API keys off">${ICON.x}</button></div></li>`:""}</ol>
    <div class="adds"><button class="btn sm" data-add="oidc">+ OIDC issuer</button><button class="btn sm" data-add="gw">+ Gateway JWT</button>${S.keys?"":`<button class="btn sm" data-keys>+ API keys</button>`}<span class="soonchip">GA4GH Passports · planned</span></div>
    <div class="tryit"><div class="eyebrow">Try a request</div><div class="opts">${[["kc","Keycloak token"],["gw","Gateway token"],["key","API key"],["none","No credential"]].map(([k,n])=>`<button data-try="${k}" class="${S.trial&&S.trial.k===k?"on":""}">${n}</button>`).join("")}</div><ol class="trace">${S.trial?S.trial.html:'<li style="opacity:1;animation:none" class="muted"><span class="s">›</span>Pick one to see how the chain handles it.</li>'}</ol></div>`+acts(i);
  if(id==="authz")return why("What a caller may do once authenticated. By default, everyone sees only their own tasks.")+
    `<div class="seg2" role="group"><button data-authz="owner" aria-pressed="${S.authz==="owner"}" class="${S.authz==="owner"?"on":""}">Owner only</button><button data-authz="pdp" aria-pressed="${S.authz==="pdp"}" class="${S.authz==="pdp"?"on":""}">Decision service</button></div>`+
    (S.authz==="pdp"?field("pdp","AuthZEN evaluation URL","authz.decisionService.url",{req:1,ph:"http://opa.policy.svc:8181/access/v1/evaluation",hint:"Asked once per decision. Errors and timeouts deny."})+`<label class="check"><input type="checkbox" data-bool="sharing" ${S.sharing?"checked":""}><span>Let the policy share tasks<small>With groups, teams or everyone.</small></span></label>`:"")+
    `<div class="row2">${field("userGroup","Only admit group","auth.issuers[].requiredClaim",{ph:"/poiesis-users",hint:"Optional. Others get 403."})}${S.authz==="owner"?field("adminGroup","Admin group","auth.issuers[].admin",{ph:"/poiesis-admins",hint:"Can revoke anyone's keys."}):""}</div>`+acts(i);
  if(id==="adv"){const groups=ADV.filter(g=>!g.when||g.when());
    return why("Everything else. Each value keeps the chart default unless you change it.")+
    groups.map(g=>{const items=g.items.filter(it=>!it.when||it.when()),ch=items.filter(it=>advVal(it)!==it.def).length;
      return`<details class="adv-group" data-g="${esc(g.g)}" ${S.openGroup===g.g?"open":""}><summary>${g.g}<small>${ch?ch+" changed":"defaults"}</small></summary><div class="in">${items.map(advField).join("")}</div></details>`}).join("")+acts(i)}
  if(id==="review")return review();
}
function advField(it){const v=advVal(it),id="a-"+it.k.replace(/\./g,"-");
  if(it.bool)return`<label class="check" id="${id}"><input id="${id}-i" type="checkbox" data-adv="${it.k}" ${v?"checked":""}><span>${it.lab}<small>${it.why}</small></span></label>`;
  const input=it.opts?`<select id="${id}-i" data-adv="${it.k}">${it.opts.map(o=>`<option ${o===v?"selected":""} value="${o}">${o||"not set"}</option>`).join("")}</select>`:`<input id="${id}-i" type="${it.num?"number":"text"}" data-adv="${it.k}" value="${esc(v)}" placeholder="${esc(it.ph||(it.def===""?"not set":it.def))}">`;
  return`<div class="f" id="${id}"><div class="lab"><label for="${id}-i">${it.lab}</label><span class="k" title="${it.show||it.k}">${it.show||it.k}</span></div>${input}<div class="hint">${it.why}</div></div>`}
function chainFields(l,j){
  const f=(k,lab,ph)=>`<div class="f" style="margin-bottom:10px"><div class="lab"><label for="c-${j}-${k}">${lab}</label>${INFO["c_"+k]?infoBtn(lab,`c${j}${k}`):""}</div>${INFO["c_"+k]?popEl(INFO["c_"+k],`c${j}${k}`):""}<input id="c-${j}-${k}" type="text" data-chain="${j}.${k}" value="${esc(l[k]||"")}" placeholder="${ph}" class="${S.ex.has("chain"+j+k)?"ex":""}"></div>`;
  return l.type==="oidc"?f("issuer","Issuer URL","https://keycloak.example.org/realms/poiesis")+`<div class="row2">${f("aud","Audience","poiesis")}${f("clients","Clients","poiesis-cli")}</div>`
    :f("issuer","Issuer","https://gateway.example.org")+`<div class="row2">${f("aud","Audience","poiesis")}${f("jwks","JWKS URL","http://gateway.mesh.svc/.well-known/jwks.json")}</div>`;
}
function missing(){const m=[];if(!S.url)m.push(["Public URL",0,"w-url"]);if(!S.dbSecret)m.push(["Database Secret",1,"w-dbSecret"]);if(!S.s3Region)m.push(["S3 region",2,"w-s3Region"]);if(S.s3Cred==="secret"&&!S.s3Secret)m.push(["S3 Secret",2,"w-s3Secret"]);if(S.s3Cred==="irsa"&&!S.s3Role)m.push(["IAM role",2,"w-s3Role"]);if(S.tls==="secret"&&!S.tlsSecret)m.push(["TLS Secret",0,"w-tlsSecret"]);if(S.tls==="cm"&&!S.cmIssuer)m.push(["ClusterIssuer",0,"w-cmIssuer"]);if(!S.chain.some(l=>l.issuer))m.push(["An issuer URL",4]);if(S.authz==="pdp"&&!S.pdp)m.push(["Decision service URL",5,"w-pdp"]);return m}
const EXLABEL={cmIssuer:["ClusterIssuer",0,"w-cmIssuer"],s3Role:["IAM role",2,"w-s3Role"],url:["Public URL",0,"w-url"],dbSecret:["Database Secret",1,"w-dbSecret"],s3Endpoint:["S3 endpoint",2,"w-s3Endpoint"],s3Region:["S3 region",2,"w-s3Region"],s3Secret:["S3 Secret",2,"w-s3Secret"],pdp:["Decision service URL",5,"w-pdp"]};
const fmt=v=>v===""?"unset":String(v);
function review(){
  const m=missing(),ex=[...S.ex].map(k=>EXLABEL[k]?[...EXLABEL[k],S[k]]:k.startsWith("chain")?["Issuer URL",4,null,(S.chain[+k[5]]||{}).issuer]:null).filter(Boolean),defs=advDefaults(),chg=advChanged();
  const row=(l,s,f,btn,v)=>`<li><span class="d" style="color:var(--fg)">${l}</span>${v?`<span class="v rv-ex">${esc(v)}</span>`:""}<button class="btn ghost sm go" data-go="${s}" ${f?`data-focus="${f}"`:""}>${btn}</button></li>`;
  return`<div class="rv">
    ${m.length?`<div><h3>Still required <span class="cnt">${m.length}</span></h3><ul class="miss">${m.map(([l,s,f])=>row(l,s,f,"Set")).join("")}</ul></div>`:(ex.length?`<div class="ok neutral">Ready once you replace ${ex.length} example value${ex.length>1?"s":""}.</div>`:`<div class="ok"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12l5 5 9-10"/></svg>Every required value is set.</div>`)}
    ${ex.length?`<div><h3>Example values to replace <span class="cnt">${ex.length}</span></h3><ul>${ex.map(([l,s,f,v])=>row(l,s,f,"Change",v)).join("")}</ul></div>`:""}
    ${chg.length?`<div><h3>Changed from the defaults <span class="cnt">${chg.length}</span></h3><ul>${chg.map(it=>`<li><code>${it.show||it.k}</code><span class="d"></span><span class="v">${esc(fmt(advVal(it)))}</span><button class="btn ghost sm go" data-adv-go="${esc(it.k)}" data-group="${esc(it.g)}">Edit</button></li>`).join("")}</ul></div>`:""}
    <div><h3>Left at the chart defaults <span class="cnt">${defs.length}</span></h3>${[...new Set(defs.map(d=>d.g))].map(g=>{const its=defs.filter(d=>d.g===g);return`<details><summary>${g}<small>${its.map(i=>i.lab).join(", ").slice(0,48)}${its.map(i=>i.lab).join(", ").length>48?"…":""}</small></summary><ul>${its.map(it=>`<li><span class="d"><b style="font-weight:500;color:var(--fg)">${it.lab}</b><br>${it.why}</span><span class="v">${esc(fmt(it.def))}</span><button class="btn ghost sm go" data-adv-go="${esc(it.k)}" data-group="${esc(it.g)}">Change</button></li>`).join("")}</ul></details>`}).join("")}</div>
    <div><h3>Install</h3>
      <div class="cmd"><span>${1+(S.s3Cred==="secret"?1:0)} Secret${S.s3Cred==="secret"?"s":""} to create, in install.sh</span><button class="mini" data-tab-go="install" aria-label="Show install.sh">${ICON.file}</button></div>
      <div class="cmd"><span>helm install poiesis ./deployment/helm/poiesis -n ${esc(S.ns||"poiesis")} -f values.yaml</span><button class="mini" data-copy-cmd aria-label="Copy">${ICON.copy}</button></div></div>
    <div class="acts"><button class="btn primary sm" data-edit-now>Edit values.yaml here</button><button class="btn sm" id="dl2">Download</button></div></div>`;
}
function renderSteps(){
  $("#steps").innerHTML=STEPDEF.map((d,i)=>`<li class="step ${i===S.step?"cur":""} ${S.done.has(i)&&i!==S.step?"done":""}" data-i="${i}">
    <button class="hd" data-go="${i}" aria-expanded="${i===S.step}"><span class="n">${S.done.has(i)&&i!==S.step?"✓":i+1}</span><span class="ttl">${d.t}</span>${d.opt?'<span class="opt">optional</span>':""}<span class="sum">${i===S.step?"":esc(d.sum())}</span></button>
    <div class="bd">${i===S.step?body(d.id,i):""}</div></li>`).join("");
}

/* YAML: only what differs from the chart defaults; each line remembers which step wrote it */
let tab="values";
const q=v=>v===true||v===false||typeof v==="number"?String(v):/^[\w./:@-]+$/.test(v)&&!/^\d/.test(v)&&!/^(true|false|null|yes|no|on|off)$/i.test(v)?v:JSON.stringify(v);
function lines(){
  const L=[],ex=k=>S.ex.has(k)?"  # example, replace":"",add=(txt,step)=>L.push({txt,step});
  const adv=Object.fromEntries(advChanged().map(it=>[it.k,advVal(it)]));
  add("# Poiesis values.yaml (non-default values only)",-1);add("",-1);
  if("logLevel"in adv){add(`logLevel: ${adv.logLevel}`,ADVI);add("",ADVI)}
  if(S.url||"api.replicas"in adv||"api.pdb.enabled"in adv){add("api:",S.url?0:ADVI);
    if("api.replicas"in adv)add(`  replicas: ${adv["api.replicas"]}`,ADVI);
    if("api.pdb.enabled"in adv){add("  pdb:",ADVI);add(`    enabled: ${adv["api.pdb.enabled"]}`,ADVI)}
    if(S.url){const host=S.url.replace(/^https?:\/\//,"").replace(/\/.*$/,"");add("  ingress:",0);add("    enabled: true",0);if(S.ingress)add(`    className: ${q(S.ingress)}`,0);add("    hosts:",0);add(`      - host: ${q(host)}${ex("url")}`,0);add("        paths: [{path: /, pathType: Prefix}]",0);if(S.tls==="cm"){add("    annotations:",0);add(`      cert-manager.io/cluster-issuer: ${S.cmIssuer?q(S.cmIssuer)+ex("cmIssuer"):'""  # required'}`,0)}if(S.tls!=="none"){add("    tls:",0);add(`      - secretName: ${q(S.tls==="secret"?(S.tlsSecret||"poiesis-tls"):"poiesis-tls")}`,0);add(`        hosts: [${q(host)}]`,0)}}add("",0)}
  add("database:",1);add(`  existingSecret: ${S.dbSecret?q(S.dbSecret)+ex("dbSecret"):'""  # required'}`,1);if(S.dbCa)add(`  caConfigmap: ${q(S.dbCa)}`,1);add("",1);
  add("s3:",2);if(S.s3Endpoint)add(`  endpoint: ${q(S.s3Endpoint)}${ex("s3Endpoint")}`,2);add(`  region: ${S.s3Region?q(S.s3Region)+ex("s3Region"):'""  # required'}`,2);
  if(S.s3Cred==="secret")add(`  existingSecret: ${S.s3Secret?q(S.s3Secret)+ex("s3Secret"):'""  # required'}`,2);add("",2);
  if(S.s3Cred==="irsa"){const an="eks.amazonaws.com/role-arn",v=S.s3Role?JSON.stringify(S.s3Role):'""  # required';
    add("serviceAccount:",2);for(const c of["api","taskpod"]){add(`  ${c}:`,2);add("    annotations:",2);add(`      ${an}: ${v}${S.ex.has("s3Role")?"  # example, replace":""}`,2)}add("",2)}
  const vol=[];if(+S.defSize!==10)vol.push([`    defaultSizeGi: ${+S.defSize}`,3]);if(+S.maxSize!==100)vol.push([`    maxSizeGi: ${+S.maxSize}`,3]);if(S.sc)vol.push([`    storageClass: ${q(S.sc)}`,3]);if(+S.retain!==3600)vol.push([`    retainAfterSeconds: ${+S.retain}`,3]);
  if(adv["taskpods.persistence.rwx"])vol.push(["    accessModes: [ReadWriteMany]",ADVI]);
  const tp=[];if(adv["taskpods.namespace"])tp.push(`  namespace: ${q(adv["taskpods.namespace"])}`);if(adv["taskpods.outputGlobFallback"])tp.push("  outputGlobFallback: true");
  if(vol.length||tp.length){add("taskpods:",vol.length?3:ADVI);tp.forEach(t=>add(t,ADVI));if(vol.length){add("  persistence:",3);vol.forEach(([t,s])=>add(t,s))}add("",3)}
  add("auth:",4);if(S.url)add(`  resource: ${q(S.url)}${ex("url")}`,0);add("  issuers:",4);
  const firstOidc=S.chain.findIndex(c=>c.type==="oidc");
  S.chain.forEach((l,j)=>{add(`    - issuer: ${l.issuer?q(l.issuer)+ex("chain"+j+"issuer"):'""  # required'}`,4);add(`      audience: ${q(l.aud||"poiesis")}`,4);
    if(l.type==="oidc"){if(/\/realms\//.test(l.issuer||""))add("      tokenTypes: [JWT]  # Keycloak access tokens; other issuers default to at+jwt",4);if(l.clients)add(`      clients: [${l.clients}]`,4);
      if(S.userGroup)add(`      requiredClaim: {name: groups, values: [${S.userGroup}]}`,5);
      if(S.adminGroup&&S.authz==="owner")add(`      admin: {name: groups, values: [${S.adminGroup}]}`,5);
      if(S.keys&&j===firstOidc)add(`      keyMinting: {clients: [${l.clients||"poiesis-cli"}], maxAuthAge: 600}`,4)}
    else add(`      jwksUri: ${l.jwks?q(l.jwks):'""  # required'}`,4)});
  if(S.keys){add("  apiKeys:",4);add("    enabled: true",4);["defaultTtl","maxTtl","maxPerOwner"].forEach(k=>{if(("auth.apiKeys."+k)in adv)add(`    ${k}: ${q(adv["auth.apiKeys."+k])}`,ADVI)})}
  if(adv["auth.swaggerUi.clientId"]&&firstOidc>=0){add("  swaggerUi:",ADVI);add(`    issuer: ${q(S.chain[firstOidc].issuer||"")}`,ADVI);add(`    clientId: ${q(adv["auth.swaggerUi.clientId"])}`,ADVI)}
  if(S.authz==="pdp"||adv["authz.adminRead"]){add("",5);add("authz:",5);
    if(S.authz==="pdp"){add("  decisionService:",5);add(`    url: ${S.pdp?q(S.pdp)+ex("pdp"):'""  # required'}`,5);if(S.sharing)add("  sharing: true",5);if("authz.maxOwners"in adv)add(`  maxOwners: ${adv["authz.maxOwners"]}`,ADVI)}
    if(adv["authz.adminRead"])add("  adminRead: true",ADVI)}
  if(adv["audit.enabled"]===false){add("",ADVI);add("audit:",ADVI);add("  enabled: false",ADVI)}
  if(adv["networkPolicy.enabled"]){add("",ADVI);add("networkPolicy:",ADVI);add("  enabled: true",ADVI)}
  const si=["id","name","environment"].filter(k=>adv["serviceInfo."+k]);if(si.length){add("",ADVI);add("serviceInfo:",ADVI);si.forEach(k=>add(`  ${k}: ${q(adv["serviceInfo."+k])}`,ADVI))}
  return L;
}
function installLines(){
  const ns=S.ns||"poiesis",L=[["# 1. Secrets. The chart references them; it never creates them.",-1],[`kubectl create namespace ${ns}`,-1],...(S.adv["taskpods.namespace"]&&S.adv["taskpods.namespace"]!==ns?[[`kubectl create namespace ${S.adv["taskpods.namespace"]}`,ADVI]]:[]),["",-1],
    [`kubectl -n ${ns} create secret generic ${S.dbSecret||"poiesis-db"} \\`,1],[`  --from-literal=DATABASE_URL='postgresql://poiesis:…@db:5432/poiesis?${S.dbCa?"sslmode=verify-full&sslrootcert=/etc/ssl/poiesis/ca.crt":"sslmode=require"}'`,1],["",1]];
  if(S.s3Cred==="secret")L.push([`kubectl -n ${ns} create secret generic ${S.s3Secret||"poiesis-s3"} \\`,2],["  --from-literal=AWS_ACCESS_KEY_ID=… \\",2],["  --from-literal=AWS_SECRET_ACCESS_KEY=…",2],["",2]);
  L.push(["# 2. Install (from a checkout until the chart is published, #53)",-1],["helm install poiesis ./deployment/helm/poiesis \\",-1],[`  -n ${ns} -f values.yaml`,-1]);
  return L.map(([txt,step])=>({txt,step}));
}
function hl(t){if(/^\s*#/.test(t))return`<span class="c">${esc(t)}</span>`;
  const[main,com]=t.split(/(?=  # )/);let h=esc(main).replace(/^(\s*-?\s*)([\w.]+)(:)/,'$1<span class="k">$2</span>$3').replace(/(: )(.+)$/,(m,a,b)=>a+`<span class="s">${b}</span>`);
  if(com&&/example/.test(com))h=h.replace('<span class="s">','<span class="s exv">');
  if(com)h+=`<span class="${/example/.test(com)?"ex":"c"}">${esc(com)}</span>`;return h}
function hlSh(t){return/^\s*#/.test(t)?`<span class="c">${esc(t)}</span>`:esc(t).replace(/^(kubectl|helm)/,'<span class="k">$1</span>')}
function currentLines(){if(tab==="values"&&S.manual!==null)return S.manual.split("\n").map(txt=>({txt,step:-2}));return tab==="values"?lines():installLines()}
function fileText(){return currentLines().map(l=>l.txt).join("\n").replace(/\n*$/,"\n")}
function renderCode(scroll=true){
  const L=currentLines(),cur=S.step,ed=$("#ed"),ta=$("#ta"),editing=S.editing&&tab==="values";
  $("#code").innerHTML=L.map(l=>`<span class="ln ${l.step===cur?"hl":""}">${(tab==="values"?hl:hlSh)(l.txt)||" "}</span>`).join("");
  $("#file-meta").textContent=`${L.length} lines`;
  $$(".file .tab").forEach(b=>b.classList.toggle("on",b.dataset.tab===tab));
  $("#banner").classList.toggle("on",S.manual!==null&&tab==="values");
  ed.classList.toggle("editing",editing);
  const eb=$("#edit-btn");eb.classList.toggle("on",editing);eb.textContent=editing?"Done":"Edit";eb.setAttribute("aria-pressed",String(editing));eb.disabled=tab!=="values";
  if(editing&&document.activeElement!==ta)ta.value=fileText().replace(/\n$/,"");
  ta.style.height=$("#code").offsetHeight+"px";
  if(scroll&&!editing){const first=$("#code .hl");if(first)ed.scrollTo({top:Math.max(0,first.offsetTop-ed.clientHeight/3),behavior:reduce?"auto":"smooth"})}
}
const sig=el=>{if(!el||!$("#steps").contains(el))return null;if(el.id)return"#"+CSS.escape(el.id);for(const a of el.attributes)if(a.name.startsWith("data-"))return`[${a.name}="${CSS.escape(a.value)}"]`;return null};
function render(restore=true){const a=document.activeElement,sel=restore?sig(a):null,pos=a&&"selectionStart"in a?a.selectionStart:null;
  renderSteps();renderCode();if(sel){const n=$("#steps").querySelector(sel);if(n&&n!==a){n.focus({preventScroll:true});try{if(pos!=null)n.setSelectionRange(pos,pos)}catch(e){}}}}
let kbd=false;B_.on(window,"keydown",()=>{kbd=true},true);B_.on(window,"pointerdown",()=>{kbd=false},true);

function fillExample(i){
  const set=(k,v)=>{if(!S[k]){S[k]=v;S.ex.add(k)}},id=STEPDEF[i].id;
  if(id==="basics"){set("url",EX.url);if(S.tls==="cm")set("cmIssuer","letsencrypt")}
  if(id==="db")set("dbSecret",EX.dbSecret);
  if(id==="storage"){set("s3Region",EX.s3Region);if(S.s3Cred==="secret")set("s3Secret",EX.s3Secret);else set("s3Role","arn:aws:iam::123456789012:role/poiesis")}
  if(id==="authn"){S.chain.forEach((l,j)=>{if(!l.issuer&&l.type==="oidc"){l.issuer=EX.issuer;S.ex.add("chain"+j+"issuer")}})}
  if(id==="authz"&&S.authz==="pdp")set("pdp",EX.pdp);
}
function go(i,focus){const moved=S.step!==clamp(i,0,LAST);S.step=clamp(i,0,LAST);render(!moved);if(panelOpen)openPanel();
  if(moved&&!focus&&kbd){const st=$(`.step[data-i="${S.step}"]`),t=st.querySelector(".bd input:not([disabled]):not([type=checkbox]),.bd select,.bd summary")||st.querySelector(".hd");if(t)t.focus({preventScroll:true})}
  const el=$(`.step[data-i="${S.step}"]`);
  if(focus){const t=document.getElementById(focus);if(t){t.scrollIntoView({behavior:reduce?"auto":"smooth",block:"center"});const inp=t.querySelector("input,select");if(inp)inp.focus({preventScroll:true});t.classList.remove("flash");void t.offsetWidth;t.classList.add("flash");return}}
  if(el&&el.getBoundingClientRect().top<70)el.scrollIntoView({behavior:reduce?"auto":"smooth",block:"start"})}
function advance(){S.done.add(S.step);go(S.step+1)}

const TRIALS={
  kc:()=>{const j=S.chain.findIndex(l=>l.type==="oidc"&&l.issuer);if(j<0)return{hit:null,steps:[["Bearer eyJ… (iss: keycloak)"],["no OIDC issuer set yet","bad"],["401 invalid_token","bad"]]};
    return{hit:j,steps:[["Bearer eyJhbGci…"],[`iss matches ${esc(S.chain[j].issuer.replace(/^https?:\/\//,""))}`],["signature checked against the issuer's keys"],[`aud ${S.chain[j].aud||"poiesis"} · typ JWT · client ${(S.chain[j].clients||"any").split(",")[0]}`],...(S.userGroup?[[`groups contains ${S.userGroup}`]]:[]),[`<b>200</b>  owner ${esc(S.chain[j].issuer.replace(/^https?:\/\//,""))}|alice`,"ok"]]}},
  gw:()=>{const j=S.chain.findIndex(l=>l.type==="gw");if(j<0)return{hit:null,steps:[["Bearer eyJ… (iss: gateway)"],["no entry for this issuer","bad"],["401 invalid_token","bad"]]};
    return{hit:j,steps:[["Bearer eyJ… signed by the gateway"],[`iss matches ${esc((S.chain[j].issuer||"").replace(/^https?:\/\//,""))}`],["keys from the static jwksUri"],["<b>200</b>  owner gateway|svc-nextflow","ok"]]}},
  key:()=>S.keys?{hit:"key",steps:[["Bearer poi_7Kq…"],["poi_ prefix: an API key, looked up by hash"],["not revoked, not expired"],["<b>200</b>  same owner as the user who minted it","ok"]]}:{hit:null,steps:[["Bearer poi_7Kq…"],["API keys are off","bad"],["401 invalid_token","bad"]]},
  none:()=>({hit:null,steps:[["no Authorization header"],["401","bad"],[`WWW-Authenticate: Bearer${S.url?" resource_metadata=…":""}`,"bad"],[S.url?"the client follows it to your issuer":"set a public URL so clients can find the issuer"]]}),
};
function runTrial(k){const r=TRIALS[k]();S.trial={k,hit:r.hit,html:r.steps.map((s,n)=>`<li class="${s[1]||""}" style="animation-delay:${reduce?0:n*140}ms"><span class="s">${s[1]==="bad"?"×":s[1]==="ok"?"✓":"›"}</span><span>${s[0]}</span></li>`).join("")};render()}

/* ---------- How-it-works panel content ---------- */
function explainSpec(id){
  const m=Math.min(3,S.chain.length)+(S.keys?1:0),blockH=m*58-14,midY=16+blockH/2-22;
  const ent=S.chain.slice(0,3).map((l,j)=>[`e${j}`,{x:150,y:16+j*58,w:132,label:l.type==="oidc"?"OIDC issuer":"Gateway JWT",sub:(l.issuer||"not set").replace(/^https?:\/\//,"").slice(0,18)}]);
  const host=(S.url||"poiesis.example.org").replace(/^https?:\/\//,"").slice(0,16);
  if(id==="vol")return{title:"Task volumes",pts:["Sized by the task's <code>disk_gb</code>, up to the largest allowed.","Shared by the task's containers.","Deleted with the Job after <code>retainAfterSeconds</code>."],fig:true};
  if(id==="adv")return{title:"Advanced",pts:["None of these are needed to start."]};
  return({
    basics:{title:"Public URL",pts:["Becomes the ingress host and <code>auth.resource</code>.","A client that only knows this URL gets a 401 that points to the metadata.","The metadata names your issuers, so the client can log in."],
      nodes:{cl:{x:10,y:100,w:100,label:"Client",sub:"Nextflow"},ing:{x:160,y:30,w:110,label:"Ingress",sub:host},api:{x:300,y:100,w:110,label:"Poiesis API"},iss:{x:160,y:180,w:110,label:"Issuer",sub:"Keycloak"}},
      edges:[["cl","ing"],["ing","api"],["cl","iss"],["cl","api"]],
      hops:[{f:"cl",t:"ing",label:"GET /tasks",cap:"A client calls the public URL."},{f:"ing",t:"api",label:"GET /tasks",cap:"The ingress forwards it to the API."},{f:"api",t:"cl",label:"401",tone:"bad",cap:"No token: 401, pointing to the resource metadata."},{f:"cl",t:"iss",label:"log in",cap:"The metadata names the issuer. The client logs in there."},{f:"cl",t:"api",label:"Bearer …",tone:"ok",cap:"It retries with the token and gets 200."}]},
    db:{title:"Database",pts:["The API and tctl read <code>DATABASE_URL</code> from your Secret.","A migration hook updates the schema before each install or upgrade.","In production, use <code>sslmode=verify-full</code> with a CA ConfigMap."],
      nodes:{sec:{x:10,y:100,w:110,label:"Secret",sub:S.dbSecret||"poiesis-db"},api:{x:160,y:30,w:110,label:"API"},tc:{x:160,y:170,w:110,label:"tctl",sub:"task state"},pg:{x:300,y:100,w:110,label:"Postgres"}},
      edges:[["sec","api"],["sec","tc"],["api","pg"],["tc","pg"]],
      hops:[{f:"sec",t:"api",label:"DATABASE_URL",cap:"The API reads the URL from your Secret."},{f:"sec",t:"tc",label:"DATABASE_URL",cap:"So does tctl, which records how tasks end."},{f:"api",t:"pg",label:"tasks",cap:"The API stores tasks and API keys."},{f:"tc",t:"pg",label:"COMPLETE",tone:"ok",cap:"tctl writes each task's final state."}]},
    storage:{title:"Storage",pts:["Only task inputs and outputs touch object storage.","Credentials come from your Secret, or from workload identity.","While a task runs, its files live on its own volume."],
      nodes:{in:{x:10,y:30,w:100,label:"s3://in"},tif:{x:155,y:30,w:110,label:"tif",sub:"stage in"},vol:{x:155,y:115,w:110,label:"volume"},tof:{x:155,y:200,w:110,label:"tof",sub:"stage out"},out:{x:310,y:200,w:100,label:"s3://out"},cr:{x:310,y:30,w:100,label:"credentials",sub:S.s3Cred==="secret"?(S.s3Secret||"Secret"):"IRSA"}},
      edges:[["cr","tif"],["in","tif"],["tif","vol"],["vol","tof"],["tof","out"]],h:260,
      hops:[{f:"cr",t:"tif",label:"AWS_*",cap:"tif gets the S3 credentials."},{f:"in",t:"tif",label:"reads.fq",cap:"It downloads each input…"},{f:"tif",t:"vol",label:"reads.fq",cap:"…onto the task's volume."},{f:"vol",t:"tof",label:"sorted.bam",cap:"After the executors, tof picks up the outputs…"},{f:"tof",t:"out",label:"sorted.bam",tone:"ok",cap:"…and uploads them."}]},
    authn:{title:"Authentication",pts:["The token's <code>iss</code> must match one trusted issuer exactly. Order doesn't matter.","Signature, audience, token type and client are checked.","The owner is <code>issuer|subject</code>, stamped on every task."],
      nodes:Object.assign({rq:{x:10,y:midY,w:100,label:"Request",sub:"Bearer …"},ow:{x:318,y:midY,w:94,label:"Owner",sub:"issuer|sub"}},Object.fromEntries(ent),S.keys?{k:{x:150,y:16+ent.length*58,w:132,label:"API keys",sub:"poi_…"}}:{}),
      edges:[...ent.map(([id])=>["rq",id]),...ent.map(([id])=>[id,"ow"]),...(S.keys?[["rq","k"],["k","ow"]]:[])],h:Math.max(120,32+blockH),
      hops:[{f:"rq",t:"e0",label:"iss ✓",cap:"The token's <code>iss</code> matches a trusted issuer exactly."},{f:"e0",t:"ow",label:"alice",tone:"ok",cap:"Checks pass: the caller is <code>issuer|alice</code>."},...(S.keys?[{f:"rq",t:"k",label:"poi_…",cap:"An API key is looked up by its hash."},{f:"k",t:"ow",label:"alice",tone:"ok",cap:"It has the owner of whoever minted it."}]:[])]},
    authz:S.authz==="pdp"?{title:"Authorization",pts:["Each decision is one AuthZEN call.","The service can share tasks with groups or everyone.","If it errors or times out, the answer is no (503)."],
      nodes:{rq:{x:10,y:90,w:100,label:"alice",sub:"GET task"},api:{x:160,y:90,w:100,label:"API"},pdp:{x:310,y:30,w:100,label:"Policy",sub:"AuthZEN"},db:{x:310,y:150,w:100,label:"Tasks"}},
      edges:[["rq","api"],["api","pdp"],["api","db"]],
      hops:[{f:"rq",t:"api",label:"GET",cap:"alice asks for a task."},{f:"api",t:"pdp",label:"evaluate",cap:"Poiesis asks the policy whether alice may read it."},{f:"pdp",t:"api",label:"true",tone:"ok",cap:"Yes: her group shares it."},{f:"api",t:"db",label:"read",cap:"Only then is the task read."},{f:"api",t:"rq",label:"200",tone:"ok",cap:"alice gets the task."}]}
      :{title:"Authorization",pts:["Everyone sees and cancels only their own tasks.","An admin group can revoke anyone's API keys.","Add a decision service later to share tasks."],
      nodes:{rq:{x:10,y:90,w:100,label:"alice",sub:"GET task"},api:{x:160,y:90,w:100,label:"API",sub:"owner rule"},db:{x:310,y:90,w:100,label:"Tasks"}},
      edges:[["rq","api"],["api","db"]],h:220,
      hops:[{f:"rq",t:"api",label:"GET",cap:"alice asks for a task."},{f:"api",t:"db",label:"owner?",cap:"Poiesis checks who owns the task."},{f:"api",t:"rq",label:"200",tone:"ok",cap:"It's hers: 200. Anyone else gets 404."}]},
    review:{title:"Installing",pts:["Create the Secrets first; the chart only refers to them.","A migration hook runs before the API starts.","tctl polls TaskPods and records how each task ends."],
      nodes:{you:{x:10,y:90,w:90,label:"You"},kc:{x:150,y:20,w:120,label:"kubectl",sub:"Secrets"},hm:{x:150,y:160,w:120,label:"helm",sub:"values.yaml"},cl:{x:310,y:90,w:100,label:"Cluster",sub:"api · tctl"}},
      edges:[["you","kc"],["you","hm"],["kc","cl"],["hm","cl"]],
      hops:[{f:"you",t:"kc",label:"create",cap:"Create the database and S3 Secrets."},{f:"kc",t:"cl",label:"Secrets",cap:"They land in the namespace."},{f:"you",t:"hm",label:"install",cap:"Run helm install with your values.yaml."},{f:"hm",t:"cl",label:"migrate",cap:"Migrations run, then the API and tctl start."},{f:"cl",t:"you",label:"ready",tone:"ok",cap:"Point an engine at the public URL."}]},
  })[id];
}
let panelOpen=false,stopFlow=()=>{},lastFocus=null;
function openPanel(){
  const sp=explainSpec(STEPDEF[S.step].id);if(!panelOpen)lastFocus=document.activeElement;panelOpen=true;stopFlow();stopFlow=()=>{};
  $("#panel-step").textContent=`Step ${S.step+1}`;$("#panel-title").textContent=sp.title;
  $("#panel-body").innerHTML=`<div id="pfig"></div><ul class="pts">${sp.pts.map(p=>`<li><span>${p}</span></li>`).join("")}</ul>
    <div class="pnav"><a class="btn ghost sm" href="${BASE}docs/start/what-is-poiesis">Read the docs</a></div>`;
  if(sp.fig)taskFigure($("#pfig"),{compact:true});else if(sp.nodes)stopFlow=flow($("#pfig"),sp);else $("#pfig").remove();
  $("#panel").classList.add("on");$("#scrim").classList.add("on");setTimeout(()=>$("#panel-x").focus({preventScroll:true}),50);
}
function closePanel(){if(!panelOpen)return;panelOpen=false;stopFlow();$("#panel").classList.remove("on");$("#scrim").classList.remove("on");if(lastFocus&&lastFocus.focus)lastFocus.focus({preventScroll:true})}
$("#panel-x").onclick=closePanel;$("#scrim").onclick=closePanel;
B_.on(window,"keydown",e=>{if(e.key==="Tab"&&panelOpen){const f=$$("#panel button,#panel a,#panel [tabindex]").filter(x=>!x.disabled&&x.offsetParent);if(f.length){const i=f.indexOf(document.activeElement);if(e.shiftKey&&i<=0){e.preventDefault();f[f.length-1].focus()}else if(!e.shiftKey&&i===f.length-1){e.preventDefault();f[0].focus()}}}});
B_.on(window,"keydown",e=>{if(e.key!=="Escape")return;const p=$(".f.pop-on");if(p){p.classList.remove("pop-on");return}if(panelOpen)closePanel()});
B_.on(document,"click",e=>{const b=e.target.closest("[data-info]"),open=$(".f.pop-on");
  if(b){e.preventDefault();const f=b.closest(".f"),was=f.classList.contains("pop-on");if(open)open.classList.remove("pop-on");if(!was)f.classList.add("pop-on");b.setAttribute("aria-expanded",String(!was));return}
  if(open&&!e.target.closest(".pop"))open.classList.remove("pop-on")});
$("#panel-body").addEventListener("click",e=>{const b=e.target.closest("[data-pgo]");if(b){S.done.add(S.step);go(S.step+ +b.dataset.pgo)}});

/* ---------- events ---------- */
$("#steps").addEventListener("input",e=>{const t=e.target;
  if(t.dataset.bind){S[t.dataset.bind]=t.value;S.ex.delete(t.dataset.bind);t.classList.remove("ex")}
  if(t.dataset.chain){const[j,k]=t.dataset.chain.split(".");S.chain[j][k]=t.value;S.ex.delete("chain"+j+k);t.classList.remove("ex")}
  if(t.dataset.bool)S[t.dataset.bool]=t.checked;
  if(t.dataset.adv){const it=ADV.flatMap(g=>g.items).find(x=>x.k===t.dataset.adv);S.adv[it.k]=it.bool?t.checked:it.num?(t.value===""?it.def:+t.value):t.value}
  renderCode()});
$("#steps").addEventListener("change",e=>{const t=e.target;if(t.dataset.chain){const li=t.closest(".link"),nm=li&&li.querySelector(".nm");if(nm)nm.textContent=S.chain[+t.dataset.chain.split(".")[0]].issuer||"issuer not set";return}if(t.dataset.adv&&t.type==="checkbox")render()});
$("#steps").addEventListener("toggle",e=>{if(e.target.matches&&e.target.matches("details.adv-group")){if(e.target.open)S.openGroup=e.target.dataset.g;else if(S.openGroup===e.target.dataset.g)S.openGroup=null}},true);
$("#steps").addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;
  if(b.dataset.go!==undefined)go(+b.dataset.go,b.dataset.focus);
  else if("next"in b.dataset)advance();
  else if("example"in b.dataset){fillExample(S.step);advance()}
  else if("explain"in b.dataset)openPanel();
  else if(b.dataset.vote){const k=b.dataset.vote;S.voted[k]=!S.voted[k];render();toast(S.voted[k]?"Thanks, counted":"Vote removed")}
  else if(b.dataset.cred){S.s3Cred=b.dataset.cred;render()}
  else if(b.dataset.tls){S.tls=b.dataset.tls;render()}
  else if(b.dataset.authz){S.authz=b.dataset.authz;render()}
  else if(b.dataset.add){S.chain.push({type:b.dataset.add,issuer:"",aud:"poiesis",clients:b.dataset.add==="oidc"?"poiesis-cli":"",jwks:""});S.trial=null;render()}
  else if("keys"in b.dataset){S.keys=!S.keys;S.trial=null;render()}
  else if(b.dataset.rm){S.chain.splice(+b.dataset.rm,1);S.trial=null;render()}
  else if(b.dataset.mv){const[j,d]=b.dataset.mv.split(",").map(Number);[S.chain[j],S.chain[j+d]]=[S.chain[j+d],S.chain[j]];S.trial=null;render()}
  else if(b.dataset.try)runTrial(b.dataset.try);
  else if(b.dataset.tabGo){tab=b.dataset.tabGo;S.editing=false;renderCode();$(".file").scrollIntoView({behavior:reduce?"auto":"smooth",block:"nearest"})}
  else if(b.dataset.advGo){S.openGroup=b.dataset.group;go(ADVI,"a-"+b.dataset.advGo.replace(/\./g,"-"))}
  else if("copyCmd"in b.dataset)copy(`helm install poiesis ./deployment/helm/poiesis -n ${S.ns||"poiesis"} -f values.yaml`);
  else if("editNow"in b.dataset){tab="values";S.editing=true;renderCode(false);$(".file").scrollIntoView({behavior:reduce?"auto":"smooth",block:"start"});$("#ta").focus({preventScroll:true})}
  else if(b.id==="dl2"){tab="values";renderCode(false);download()}
});
$$(".file .tab").forEach(b=>b.onclick=()=>{tab=b.dataset.tab;if(tab!=="values")S.editing=false;renderCode()});
$("#edit-btn").onclick=()=>{S.editing=!S.editing;renderCode(false);if(S.editing)$("#ta").focus()};
$("#ta").addEventListener("input",e=>{S.manual=e.target.value;renderCode(false)});
let tabOut=false;$("#ta").addEventListener("keydown",e=>{if(e.key==="Escape"){tabOut=true;return}if(e.key==="Tab"&&!tabOut){e.preventDefault();document.execCommand("insertText",false,"  ")}});$("#ta").addEventListener("blur",()=>{tabOut=false});
$("#regen").onclick=()=>{S.manual=null;S.editing=false;renderCode()};
function download(){const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([fileText()],{type:"text/yaml"}));a.download=tab==="values"?"values.yaml":"install.sh";a.click();toast("Downloaded "+a.download)}
$("#copy-file").onclick=()=>copy(fileText());$("#dl-file").onclick=download;
function fillAll(){for(let i=0;i<LAST;i++){fillExample(i);S.done.add(i)}go(LAST)}
$("#fill-all").onclick=fillAll;
let mode="human",termOn=false;
const TERM=[["u","Deploy Poiesis on my Kubernetes cluster. Read https://poiesis.jaeaeich.com/llms.txt first."],["r","reading llms.txt"],["r","reading Deploy, Helm values, Authentication"],["q","Which Postgres should Poiesis use?"],["u","Our managed Postgres. The URL is in a Secret called poiesis-db."],["q","Where do task inputs and outputs live?"],["u","S3 in eu-central-1. The nodes have IAM roles."],["q","Who issues your users' tokens?"],["u","Keycloak, realm poiesis, client poiesis-cli."],["r","writing values.yaml"],["ok","values.yaml, 22 lines"],["ok","Create the Secret poiesis-db first. S3 needs no Secret with IAM roles."],["c2","helm install poiesis ./deployment/helm/poiesis -n poiesis -f values.yaml"]];
let termRun=0;function startTerm(){if(termOn)return;termOn=true;const tb=$("#term-b"),run=++termRun;let i=0;tb.innerHTML="";
  if(reduce){tb.innerHTML=TERM.map(([c,t])=>`<div class="l ${c}" style="opacity:1;animation:none">${esc(t)}</div>`).join("");return}
  const next=()=>{if(run!==termRun)return;if(mode!=="agent"||dead){termOn=false;termRun++;return}
    if(i>=TERM.length){setTimeout(()=>{tb.innerHTML="";i=0;next()},4500);return}
    const[c,t]=TERM[i++],el=document.createElement("div");el.className="l "+c;tb.appendChild(el);tb.scrollTop=tb.scrollHeight;
    if(c==="u"){let j=0;const ty=()=>{if(run!==termRun)return;el.textContent=t.slice(0,++j);tb.scrollTop=tb.scrollHeight;if(j<t.length)setTimeout(ty,16);else setTimeout(next,600)};ty()}
    else{el.textContent=t;setTimeout(next,c==="r"?650:c==="q"?900:500)}};
  next()}
function setMode(m){mode=m;$$("[data-mode]").forEach(b=>{const on=b.dataset.mode===m;b.classList.toggle("on",on);b.setAttribute("aria-selected",String(on))});
  $("#mode-human").hidden=m!=="human";$("#mode-agent").hidden=m!=="agent";$("#fill-all").hidden=m!=="human";
  if(m==="human")renderCode(false);else{closePanel();startTerm()}}
$$("[data-mode]").forEach(b=>b.onclick=()=>setMode(b.dataset.mode));
$$("[data-copy]").forEach(b=>b.onclick=()=>copy($("#"+b.dataset.copy).firstChild.textContent));

  render();setMode(mode);
  if(location.hash==="#example"){fillAll()}
  return()=>{closePanel();B_.dispose()};
}
