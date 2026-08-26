
const STATE_CODE = "18";
const BASE = "https://mdmhp.nic.in";

function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }
function txt(el){ return (el?.textContent || "").replace(/\s+/g," ").trim(); }
function num(s){ const n=parseInt(String(s||"").replace(/[^\d-]/g,""),10); return Number.isFinite(n)?n:0; }

async function setProgress(data){
  await chrome.storage.local.set({syncProgress:{...data,updatedAt:new Date().toISOString()}});
}

function extractLastCode(el){
  const s=(el?.getAttribute("onclick")||"")+" "+(el?.getAttribute("href")||"");
  const matches=[...s.matchAll(/['"(=,\s](\d{4,})['"),\s&]/g)].map(m=>m[1]);
  return matches.length ? matches[matches.length-1] : "";
}

function parseAggregate(html, level){
  const doc=new DOMParser().parseFromString(html,"text/html");
  const out=[];
  for(const tr of doc.querySelectorAll("table tbody tr")){
    const td=[...tr.querySelectorAll(":scope > td")];
    if(td.length < 6) continue;

    const name=txt(td[1]);
    if(!name) continue;
    const code=extractLastCode(td[1]) || extractLastCode(tr);

    let monthlyReported=0, monthlyNotReported=0, enrolled=0;
    let dailyReported=0, dailyNotReported=0, mealsServed=0;

    if(td.length >= 9){
      monthlyReported=num(txt(td[3]));
      monthlyNotReported=num(txt(td[4]));
      enrolled=num(txt(td[5]));
      dailyReported=num(txt(td[6]));
      dailyNotReported=num(txt(td[7]));
      mealsServed=num(txt(td[8]));
    }else{
      // Public historical daily-only aggregate layout:
      // Sr | Name | Total | Reported | Not Reported | Meals
      dailyReported=num(txt(td[3]));
      dailyNotReported=num(txt(td[4]));
      mealsServed=num(txt(td[5]));
    }

    out.push({
      [level]:name,
      [level+"Code"]:code,
      totalSchools:num(txt(td[2])),
      monthlyReported,
      monthlyNotReported,
      enrolled,
      dailyReported,
      dailyNotReported,
      mealsServed
    });
  }
  return out;
}

function parseDistrict(html){
  const doc=new DOMParser().parseFromString(html,"text/html");
  const out=[];
  for(const tr of doc.querySelectorAll("table tbody tr")){
    const td=[...tr.querySelectorAll(":scope > td")];
    if(td.length < 6) continue;
    const name=txt(td[1]); if(!name) continue;
    const code=extractLastCode(td[1]) || extractLastCode(tr);
    out.push({
      district:name, districtCode:code,
      totalSchools:num(txt(td[2])),
      monthlyReported:0, monthlyNotReported:0, enrolled:0,
      dailyReported:num(txt(td[3])),
      dailyNotReported:num(txt(td[4])),
      mealsServed:num(txt(td[5]))
    });
  }
  return out;
}

function parseSchools(html){
  const doc=new DOMParser().parseFromString(html,"text/html");
  const out=[];
  for(const tr of doc.querySelectorAll("table tbody tr")){
    const td=[...tr.querySelectorAll(":scope > td")];
    if(td.length < 6) continue;
    const raw=txt(td[1]);
    if(!/Shift\s*ID\s*:/i.test(raw)) continue;
    const m=raw.match(/\s*-\s*\[\s*Shift\s*ID\s*:\s*([^\]]+)\]\s*$/i);
    const school=m ? raw.slice(0,m.index).trim() : raw;
    const shift=m ? m[1].trim() : "1";
    out.push({
      school, schoolCode:"", shift,
      monthlyStatus:txt(td[2]),
      enrolled:num(txt(td[3])),
      dailyStatus:txt(td[4]),
      mealsServed:num(txt(td[5]))
    });
  }
  return out;
}

function getToken(){
  const input=document.querySelector('input[name="__RequestVerificationToken"]');
  return input?.value || "";
}

async function postForm(path, fields, token){
  const body=new URLSearchParams({...fields,__RequestVerificationToken:token});
  const res=await fetch(BASE+path,{
    method:"POST",
    credentials:"include",
    headers:{
      "Content-Type":"application/x-www-form-urlencoded; charset=UTF-8",
      "X-Requested-With":"XMLHttpRequest"
    },
    body
  });
  if(!res.ok) throw new Error(path+" HTTP "+res.status);
  return await res.text();
}

async function uploadPage(page){
  const r=await chrome.runtime.sendMessage({type:"uploadPage",page});
  if(!r?.ok) throw new Error(r?.error || "Dashboard upload failed");
}

async function syncDate({reportDate,districtCode,allAssam}){
  if(!location.hostname.endsWith("mdmhp.nic.in")) throw new Error("Open mdmhp.nic.in first.");
  const token=getToken();
  if(!token){
    throw new Error("Verification token not found. Open https://mdmhp.nic.in/Home/StateWiseSummary/AS in this logged-in tab, then retry.");
  }

  await setProgress({status:"running",progress:1,message:"Loading district summary…"});
  const districtHtml=await postForm("/Home/DisttWiseSummary",{
    stateCode:STATE_CODE,mealServedDate:reportDate
  },token);
  const districts=parseDistrict(districtHtml);
  if(!districts.length) throw new Error("No district rows returned for "+reportDate);

  await uploadPage({
    reportDate,level:"district",rows:districts,
    sourceUrl:BASE+"/Home/DisttWiseSummary"
  });

  let targets=districts;
  if(!allAssam){
    targets=districts.filter(d=>String(d.districtCode)===String(districtCode));
    if(!targets.length) throw new Error("District code "+districtCode+" was not found.");
  }

  let districtDone=0, blockDone=0, clusterDone=0, discoveredBlocks=0, discoveredClusters=0, schoolRows=0;

  for(const d of targets){
    await setProgress({
      status:"running",
      progress:Math.max(2,Math.round((districtDone/Math.max(1,targets.length))*90)),
      message:`${d.district}: loading blocks…`,
      districtDone,totalDistricts:targets.length,blockDone,clusterDone,schoolRows
    });

    const blockHtml=await postForm("/Home/BlockWiseSummary",{
      stateCode:STATE_CODE,districtCode:d.districtCode,mealServedDate:reportDate
    },token);
    const blocks=parseAggregate(blockHtml,"block");
    discoveredBlocks += blocks.length;
    await uploadPage({
      reportDate,level:"block",districtCode:d.districtCode,rows:blocks,
      sourceUrl:BASE+"/Home/BlockWiseSummary"
    });
    await sleep(150);

    for(const b of blocks){
      const clusterHtml=await postForm("/Home/ClusterWiseSummary",{
        stateCode:STATE_CODE,districtCode:d.districtCode,
        blockCode:b.blockCode,mealServedDate:reportDate
      },token);
      const clusters=parseAggregate(clusterHtml,"cluster");
      discoveredClusters += clusters.length;
      await uploadPage({
        reportDate,level:"cluster",districtCode:d.districtCode,
        blockCode:b.blockCode,rows:clusters,
        sourceUrl:BASE+"/Home/ClusterWiseSummary"
      });
      blockDone++;
      await setProgress({
        status:"running",
        progress:Math.max(5,Math.round(((districtDone + blockDone/Math.max(1,discoveredBlocks))/Math.max(1,targets.length))*90)),
        message:`${d.district} / ${b.block}: ${clusters.length} clusters found`,
        districtDone,totalDistricts:targets.length,blockDone,clusterDone,
        discoveredBlocks,discoveredClusters,schoolRows
      });
      await sleep(150);

      for(const c of clusters){
        const schoolHtml=await postForm("/Home/SchoolWiseSummary",{
          stateCode:STATE_CODE,districtCode:d.districtCode,
          blockCode:b.blockCode,clusterCode:c.clusterCode,
          mealServedDate:reportDate
        },token);
        const schools=parseSchools(schoolHtml);
        if(!schools.length){
          throw new Error(`No school rows parsed for ${d.district} / ${b.block} / ${c.cluster}`);
        }
        schoolRows += schools.length;
        await uploadPage({
          reportDate,level:"school",districtCode:d.districtCode,
          blockCode:b.blockCode,clusterCode:c.clusterCode,rows:schools,
          sourceUrl:BASE+"/Home/SchoolWiseSummary"
        });
        clusterDone++;
        await setProgress({
          status:"running",
          progress:Math.max(8,Math.min(96,Math.round(((districtDone + 0.9)/Math.max(1,targets.length))*90))),
          message:`${d.district} / ${b.block} / ${c.cluster}: ${schools.length} schools archived`,
          districtDone,totalDistricts:targets.length,blockDone,clusterDone,
          discoveredBlocks,discoveredClusters,schoolRows
        });
        await sleep(180);
      }
    }
    districtDone++;
  }

  await setProgress({
    status:"done",progress:100,
    message:`Sync complete: ${districtDone} district(s), ${blockDone} blocks, ${clusterDone} clusters, ${schoolRows} school rows.`,
    districtDone,totalDistricts:targets.length,blockDone,clusterDone,schoolRows
  });
  return {districtDone,blockDone,clusterDone,schoolRows};
}

chrome.runtime.onMessage.addListener((msg,sender,sendResponse)=>{
  if(msg?.type==="startSync"){
    syncDate(msg.options)
      .then(data=>sendResponse({ok:true,data}))
      .catch(async e=>{
        await setProgress({status:"error",progress:0,message:String(e.message||e)});
        sendResponse({ok:false,error:String(e.message||e)});
      });
    return true;
  }
});
