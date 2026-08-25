
const DEFAULT_BACKEND = "https://assam-mdm-dashboard.onrender.com";

async function getConfig(){
  const c = await chrome.storage.local.get(["backendUrl","syncKey"]);
  return {
    backendUrl: (c.backendUrl || DEFAULT_BACKEND).replace(/\/+$/,""),
    syncKey: c.syncKey || ""
  };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if(msg && msg.type === "uploadPage"){
    (async()=>{
      try{
        const cfg = await getConfig();
        if(!cfg.syncKey) throw new Error("Sync key is not configured. Open extension Options.");
        const res = await fetch(cfg.backendUrl + "/api/browser-sync/page", {
          method:"POST",
          headers:{
            "Content-Type":"application/json",
            "X-Sync-Key":cfg.syncKey
          },
          body:JSON.stringify(msg.page)
        });
        const data = await res.json().catch(()=>({}));
        if(!res.ok || data.ok === false) throw new Error(data.error || ("Upload failed: HTTP "+res.status));
        sendResponse({ok:true,data:data.data});
      }catch(e){
        sendResponse({ok:false,error:String(e.message || e)});
      }
    })();
    return true;
  }
});
