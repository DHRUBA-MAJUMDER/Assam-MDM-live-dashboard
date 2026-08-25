
const $=s=>document.querySelector(s);
function reportDate(v){if(!v)return ""; const [y,m,d]=v.split("-"); return `${d}/${m}/${y}`;}
function update(p){
  $("#fill").style.width=(p.progress||0)+"%";
  $("#status").textContent=p.message||p.status||"";
}
async function init(){
  const d=new Date(); d.setDate(d.getDate()-1);
  $("#date").value=d.toISOString().slice(0,10);
  const s=await chrome.storage.local.get("syncProgress");
  if(s.syncProgress) update(s.syncProgress);
}
chrome.storage.onChanged.addListener(ch=>{
  if(ch.syncProgress?.newValue) update(ch.syncProgress.newValue);
});
$("#open").onclick=()=>chrome.tabs.create({url:"https://mdmhp.nic.in/Home/StateWiseSummary/AS"});
$("#start").onclick=async()=>{
  const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
  if(!tab?.id){update({message:"No active tab."});return;}
  const date=reportDate($("#date").value);
  const allAssam=$("#all").checked;
  const districtCode=$("#district").value.trim();
  if(!date){update({message:"Choose a date."});return;}
  if(!allAssam && !districtCode){update({message:"Enter a district code or choose all Assam."});return;}
  update({progress:1,message:"Starting…"});
  try{
    const r=await chrome.tabs.sendMessage(tab.id,{
      type:"startSync",
      options:{reportDate:date,districtCode,allAssam}
    });
    if(!r?.ok) throw new Error(r?.error||"Sync failed");
  }catch(e){
    update({progress:0,message:String(e.message||e)+" Open the PM POSHAN historical page and retry."});
  }
};
init();
