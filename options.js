
const backend=document.querySelector("#backend"), key=document.querySelector("#key"), msg=document.querySelector("#msg");
(async()=>{
 const c=await chrome.storage.local.get(["backendUrl","syncKey"]);
 if(c.backendUrl)backend.value=c.backendUrl;
 if(c.syncKey)key.value=c.syncKey;
})();
document.querySelector("#save").onclick=async()=>{
 await chrome.storage.local.set({backendUrl:backend.value.trim(),syncKey:key.value});
 msg.textContent="Saved.";
};
