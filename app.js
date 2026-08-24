
const $ = s => document.querySelector(s);
let currentRows = [];
let currentLevel = "district";
let context = {};

function fmt(n){ return Number(n||0).toLocaleString("en-IN"); }
function setLoading(v){ $("#loader").classList.toggle("hidden", !v); }
function setUpdated(){ $("#lastUpdated").textContent = "Updated " + new Date().toLocaleTimeString(); }

async function api(url){
  setLoading(true);
  try{
    const r = await fetch(url, {headers: {"Accept": "application/json"}});
    const text = await r.text();
    let j;
    try {
      j = JSON.parse(text);
    } catch (_) {
      throw new Error(`Backend returned HTTP ${r.status} instead of JSON.`);
    }
    if(!r.ok || !j.ok) throw new Error(j.error || `Request failed (${r.status})`);
    return j.data;
  } finally { setLoading(false); }
}

function stats(rows){
  $("#sTotal").textContent = fmt(rows.reduce((a,r)=>a+(r.totalSchools||0),0));
  $("#sReported").textContent = fmt(rows.reduce((a,r)=>a+(r.dailyReported||0),0));
  $("#sPending").textContent = fmt(rows.reduce((a,r)=>a+(r.dailyNotReported||0),0));
  $("#sMeals").textContent = fmt(rows.reduce((a,r)=>a+(r.mealsServed||0),0));
}

function renderDistricts(rows){
  currentLevel="district"; currentRows=rows;
  $("#panelTitle").textContent="District Overview"; $("#breadcrumb").textContent="Assam";
  $("#search").placeholder="Search district...";
  $("#thead").innerHTML=`<tr><th>District</th><th>Total Schools</th><th>Monthly Reported</th><th>Monthly Pending</th><th>Daily Reported</th><th>Daily Pending</th><th>Meals Served</th></tr>`;
  $("#tbody").innerHTML=rows.map(r=>`<tr>
    <td><a class="link" data-district="${r.districtCode}" data-name="${r.district}">${r.district}</a></td>
    <td>${fmt(r.totalSchools)}</td><td>${fmt(r.monthlyReported)}</td><td class="bad">${fmt(r.monthlyNotReported)}</td>
    <td class="good">${fmt(r.dailyReported)}</td><td class="bad">${fmt(r.dailyNotReported)}</td><td>${fmt(r.mealsServed)}</td>
  </tr>`).join("");
  stats(rows);
}

function renderBlocks(rows){
  currentLevel="block"; currentRows=rows;
  $("#panelTitle").textContent=`Blocks — ${context.districtName}`; $("#breadcrumb").textContent=`Assam / ${context.districtName}`;
  $("#search").placeholder="Search block...";
  $("#thead").innerHTML=`<tr><th>Block</th><th>Total Schools</th><th>Monthly Reported</th><th>Monthly Pending</th><th>Daily Reported</th><th>Daily Pending</th><th>Meals Served</th></tr>`;
  $("#tbody").innerHTML=rows.map(r=>`<tr>
    <td><a class="link" data-block="${r.blockCode}" data-name="${r.block}">${r.block}</a></td>
    <td>${fmt(r.totalSchools)}</td><td>${fmt(r.monthlyReported)}</td><td class="bad">${fmt(r.monthlyNotReported)}</td>
    <td class="good">${fmt(r.dailyReported)}</td><td class="bad">${fmt(r.dailyNotReported)}</td><td>${fmt(r.mealsServed)}</td>
  </tr>`).join("");
  stats(rows);
}

function renderClusters(rows){
  currentLevel="cluster"; currentRows=rows;
  $("#panelTitle").textContent=`Clusters — ${context.blockName}`; $("#breadcrumb").textContent=`Assam / ${context.districtName} / ${context.blockName}`;
  $("#search").placeholder="Search cluster...";
  $("#thead").innerHTML=`<tr><th>Cluster</th><th>Total Schools</th><th>Monthly Reported</th><th>Monthly Pending</th><th>Daily Reported</th><th>Daily Pending</th><th>Meals Served</th></tr>`;
  $("#tbody").innerHTML=rows.map(r=>`<tr>
    <td><a class="link" data-cluster="${r.clusterCode}" data-name="${r.cluster}">${r.cluster}</a></td>
    <td>${fmt(r.totalSchools)}</td><td>${fmt(r.monthlyReported)}</td><td class="bad">${fmt(r.monthlyNotReported)}</td>
    <td class="good">${fmt(r.dailyReported)}</td><td class="bad">${fmt(r.dailyNotReported)}</td><td>${fmt(r.mealsServed)}</td>
  </tr>`).join("");
  stats(rows);
}

function renderSchools(rows){
  currentLevel="school"; currentRows=rows;
  $("#panelTitle").textContent=`Schools — ${context.clusterName}`;
  $("#breadcrumb").textContent=`Assam / ${context.districtName} / ${context.blockName} / ${context.clusterName}`;
  $("#search").placeholder="Search school...";
  $("#thead").innerHTML=`<tr><th>School</th><th>School Code</th><th>Shift</th><th>Monthly Status</th><th>Enrolled</th><th>Daily Status</th><th>Meals Served</th></tr>`;
  $("#tbody").innerHTML=rows.map(r=>`<tr>
    <td>${r.school}</td><td>${r.schoolCode}</td><td>${r.shift}</td>
    <td class="${r.monthlyStatus==='Yes'?'good':'bad'}">${r.monthlyStatus}</td>
    <td>${fmt(r.enrolled)}</td><td class="${r.dailyStatus==='Yes'?'good':'bad'}">${r.dailyStatus}</td><td>${fmt(r.mealsServed)}</td>
  </tr>`).join("");
  $("#sTotal").textContent=fmt(rows.length);
  $("#sReported").textContent=fmt(rows.filter(r=>r.dailyStatus==="Yes").length);
  $("#sPending").textContent=fmt(rows.filter(r=>r.dailyStatus!=="Yes").length);
  $("#sMeals").textContent=fmt(rows.reduce((a,r)=>a+(r.mealsServed||0),0));
}

async function loadDistricts(){ const rows=await api("/api/districts"); renderDistricts(rows); setUpdated(); }
async function loadBlocks(code,name){ context={districtCode:code,districtName:name}; renderBlocks(await api(`/api/blocks?districtCode=${encodeURIComponent(code)}`)); setUpdated(); }
async function loadClusters(code,name){ context.blockCode=code;context.blockName=name;renderClusters(await api(`/api/clusters?districtCode=${context.districtCode}&blockCode=${encodeURIComponent(code)}`));setUpdated(); }
async function loadSchools(code,name){ context.clusterCode=code;context.clusterName=name;renderSchools(await api(`/api/schools?districtCode=${context.districtCode}&blockCode=${context.blockCode}&clusterCode=${encodeURIComponent(code)}`));setUpdated(); }

$("#tbody").addEventListener("click", e=>{
  const a=e.target.closest("a.link"); if(!a) return;
  if(a.dataset.district) loadBlocks(a.dataset.district,a.dataset.name);
  else if(a.dataset.block) loadClusters(a.dataset.block,a.dataset.name);
  else if(a.dataset.cluster) loadSchools(a.dataset.cluster,a.dataset.name);
});

$("#refreshBtn").addEventListener("click", ()=>{
  if(currentLevel==="district") loadDistricts();
  else if(currentLevel==="block") loadBlocks(context.districtCode,context.districtName);
  else if(currentLevel==="cluster") loadClusters(context.blockCode,context.blockName);
  else if(currentLevel==="school") loadSchools(context.clusterCode,context.clusterName);
});

$("#search").addEventListener("input", e=>{
  const q=e.target.value.toLowerCase();
  for(const tr of $("#tbody").rows){
    tr.style.display=tr.innerText.toLowerCase().includes(q)?"":"none";
  }
});

loadDistricts().catch(err=>alert(err.message));
