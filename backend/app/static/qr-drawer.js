(function(){
  const esc=v=>String(v??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  const display=v=>{
    if(v===null||v===undefined||v==="")return"—";
    if(typeof v==="string"&&/T\d\d:/.test(v)){
      const normalized=/Z$|[+-]\d\d:?\d\d$/.test(v)?v:v+"Z";
      return new Date(normalized).toLocaleString("it-IT",{dateStyle:"short",timeStyle:"medium"});
    }
    return String(v);
  };
  let history=[], currentValues=[], collection=[];
  function ensure(){
    if(document.getElementById("qrd-backdrop"))return;
    document.body.insertAdjacentHTML("beforeend",`<div class="qrd-backdrop" id="qrd-backdrop" onclick="if(event.target===this)QrDrawer.close()"><aside class="qrd"><header class="qrd-head"><button class="qrd-btn" id="qrd-back" onclick="QrDrawer.back()" style="display:none">← Indietro</button><div><div class="qrd-kicker" id="qrd-kicker">Scheda QR</div><div class="qrd-title" id="qrd-title">—</div></div><div class="qrd-spacer"></div><button class="qrd-btn" onclick="QrDrawer.refresh()">↻ Aggiorna</button><button class="qrd-btn qrd-close" onclick="QrDrawer.close()">×</button></header><div class="qrd-content"><nav class="qrd-nav" id="qrd-nav"><div class="qrd-nav-title">Naviga tra i codici</div><input class="qrd-nav-search" id="qrd-nav-search" placeholder="Filtra codice…" oninput="QrDrawer.filterNav()"><div class="qrd-nav-filters"><select class="qrd-nav-select" id="qrd-nav-profile" onchange="QrDrawer.filterNav()"><option value="">Tutti i profili</option></select><select class="qrd-nav-select" id="qrd-nav-assembly" onchange="QrDrawer.filterNav()"><option value="">Tutti gli assemblati</option></select></div><div class="qrd-nav-count" id="qrd-nav-count"></div><div class="qrd-nav-list" id="qrd-nav-list"></div></nav><div class="qrd-body" id="qrd-body"></div></div></aside></div>`);
  }
  const headers=()=>({Authorization:"Bearer "+sessionStorage.getItem("stqc_token"),"Content-Type":"application/json"});
  async function fetchOne(value){
    const r=await fetch("/api/v1/qr/details/"+encodeURIComponent(value),{headers:headers()});
    const d=await r.json().catch(()=>({})); if(!r.ok)throw new Error(d.detail||"QR non disponibile"); return d;
  }
  function setCollection(items){
    collection=(items||[]).filter(x=>x&&x.uuid).map(x=>({uuid:x.uuid,code:x.code||x.qr_code||x.uuid,status:x.status||x.stato||"",profilo:x.profilo||"",assemblato:x.assemblato||"",nota:x.nota||""}));
    if(document.getElementById("qrd-nav"))setupNavFilters();
  }
  function setupNavFilters(){
    const profile=document.getElementById("qrd-nav-profile"),assembly=document.getElementById("qrd-nav-assembly");if(!profile||!assembly)return;
    const profiles=[...new Set(collection.map(x=>x.profilo).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"it"));
    const assemblies=[...new Set(collection.map(x=>x.assemblato).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"it"));
    profile.innerHTML='<option value="">Tutti i profili</option>'+profiles.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join("");
    assembly.innerHTML='<option value="">Tutti gli assemblati</option>'+assemblies.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join("");
    filterNav();
  }
  function filterNav(){
    const search=(document.getElementById("qrd-nav-search")?.value||"").trim().toLowerCase(),profile=document.getElementById("qrd-nav-profile")?.value||"",assembly=document.getElementById("qrd-nav-assembly")?.value||"";
    const rows=collection.filter(x=>(!search||[x.code,x.profilo,x.assemblato,x.nota].some(v=>String(v).toLowerCase().includes(search)))&&(!profile||x.profilo===profile)&&(!assembly||x.assemblato===assembly));
    const list=document.getElementById("qrd-nav-list"),count=document.getElementById("qrd-nav-count");if(!list)return;
    count.textContent=`${rows.length} codici`;
    list.innerHTML=rows.slice(0,500).map(x=>`<button class="qrd-nav-item ${currentValues.length===1&&currentValues[0]===x.uuid?"active":""}" onclick="QrDrawer.open('${esc(x.uuid)}')"><div class="qrd-nav-code">${esc(x.code)}</div><div class="qrd-nav-meta">${esc(x.profilo||"—")}${x.assemblato?" · "+esc(x.assemblato):""}</div></button>`).join("")||'<div class="qrd-empty">Nessun codice.</div>';
  }
  function statusText(x){return x.status_label||x.status||"—"}
  function rowLink(x){return `<div class="qrd-row click" onclick="QrDrawer.open('${esc(x.uuid)}',true)"><div><div class="qrd-row-main">${esc(x.code)}</div><div class="qrd-row-sub">${esc(x.subtitle||statusText(x))}</div></div><div class="qrd-time">Apri →</div></div>`}
  function phaseLabel(event){
    const map={
      PIECE_READ:"PEZZO LETTO",
      PHASE_START:"FASE INIZIATA",
      PHASE_DONE:"FASE COMPLETATA",
      PHASE_END:"FASE FINITA",
      MATERIAL_ASSIGNED:"GREZZO COLLEGATO",
      MATERIAL_PENDING:"PEZZO IN ATTESA GREZZO"
    };
    return map[event]||event||"EVENTO";
  }
  function timelineRow(x){
    const isPreprod=["MATERIAL_ASSIGNED","MATERIAL_PENDING"].includes(x.event);
    const main=isPreprod?"Pre-produzione":(x.workstation_label||x.workstation||"Postazione non indicata");
    const sub=phaseLabel(x.event);
    const extra=isPreprod&&x.origin_code?`<div class="qrd-row-note">Origine: ${esc(x.origin_code)}${x.origin_status?" · "+esc(x.origin_status):""}</div>`:"";
    return `<div class="qrd-row ${isPreprod?"preprod":""}"><div><div class="qrd-row-main phase">${esc(main)}</div><div class="qrd-row-sub phase">${esc(sub)}</div>${extra}</div><div class="qrd-time">${esc(display(x.timestamp))}${x.duration_seconds!=null?`<br>${esc(x.duration_seconds)} s`:""}</div></div>`;
  }
  function render(d){
    document.getElementById("qrd-kicker").textContent=d.entity_label||"Scheda QR";
    document.getElementById("qrd-title").textContent=d.code||d.uuid;
    document.getElementById("qrd-back").style.display=history.length?"":"none";
    const fields=Object.entries(d.fields||{}).map(([k,v])=>`<div class="qrd-field"><div class="qrd-label">${esc(k)}</div><div class="qrd-value">${esc(display(v))}</div></div>`).join("");
    const origin=d.origin?`<div class="qrd-section"><h3>Origine materiale</h3><div class="qrd-list"><div class="qrd-row qrd-origin click" onclick="QrDrawer.open('${esc(d.origin.uuid)}',true)"><div><div class="qrd-row-main">${esc(d.origin.code)}</div><div class="qrd-row-sub">${esc(d.origin.subtitle||("Grezzo collegato · "+statusText(d.origin)))}</div></div><div class="qrd-time">Apri →</div></div></div></div>`:"";
    const deps=(d.dependencies||[]).length?`<div class="qrd-section"><h3>Dipendenze e componenti collegati</h3><div class="qrd-list">${d.dependencies.map(rowLink).join("")}</div></div>`:"";
    const timeline=(d.timeline||[]).length?`<div class="qrd-section"><h3>Aggiornamenti officina</h3><div class="qrd-list">${d.timeline.map(timelineRow).join("")}</div></div>`:"<div class='qrd-section'><h3>Aggiornamenti officina</h3><div class='qrd-empty'>Nessun aggiornamento officina registrato.</div></div>";
    document.getElementById("qrd-body").innerHTML=`<div class="qrd-hero"><img class="qrd-qr" src="${esc(d.qr_image_url)}" alt="QR"><div><div class="qrd-status">${esc(d.status_label||d.status||"—")}</div>${d.subtitle?`<div class="qrd-entity-subtitle">${esc(d.subtitle)}</div>`:""}<div class="qrd-grid">${fields}</div></div></div>${origin}${deps}${timeline}`;
  }
  async function open(value,fromLink=false){
    ensure(); if(fromLink&&currentValues.length)history.push([...currentValues]); currentValues=[value]; setupNavFilters();
    document.getElementById("qrd-backdrop").classList.add("open"); document.getElementById("qrd-body").innerHTML="<div class='qrd-loading'>Caricamento scheda dal DB…</div>";
    try{render(await fetchOne(value))}catch(e){document.getElementById("qrd-body").innerHTML=`<div class="qrd-empty qrd-error">${esc(e.message)}</div>`}
  }
  async function openMany(values){
    ensure(); currentValues=[...new Set(values)].filter(Boolean); history=[]; setupNavFilters(); document.getElementById("qrd-backdrop").classList.add("open");
    document.getElementById("qrd-kicker").textContent="Selezione multipla"; document.getElementById("qrd-title").textContent=currentValues.length+" QR selezionati"; document.getElementById("qrd-back").style.display="none";
    document.getElementById("qrd-body").innerHTML="<div class='qrd-loading'>Caricamento elementi dal DB…</div>";
    const r=await fetch("/api/v1/qr/details",{method:"POST",headers:headers(),body:JSON.stringify({values:currentValues})}); const d=await r.json();
    document.getElementById("qrd-body").innerHTML=`<div class="qrd-cards">${(d.items||[]).map(x=>`<div class="qrd-card" onclick="QrDrawer.open('${esc(x.uuid)}',true)"><div class="qrd-kicker">${esc(x.entity_label||x.entity)}</div><div class="qrd-title" style="font-size:18px;margin-top:7px">${esc(x.code)}</div>${x.subtitle?`<div class="qrd-row-sub">${esc(x.subtitle)}</div>`:""}<div class="qrd-status">${esc(x.status_label||x.status||"—")}</div>${x.error?`<div class="qrd-error">${esc(x.error)}</div>`:""}</div>`).join("")}</div>`;
  }
  function back(){const values=history.pop(); if(values)openMany(values)}
  function refresh(){currentValues.length>1?openMany(currentValues):currentValues[0]&&open(currentValues[0])}
  function close(){document.getElementById("qrd-backdrop")?.classList.remove("open")}
  window.QrDrawer={open,openMany,back,refresh,close,setCollection,filterNav};
})();
