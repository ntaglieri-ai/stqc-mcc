(() => {
  const layout=document.querySelector('.layout');
  layout.classList.add('qr-compact','filters-closed');
  const filters=document.querySelector('.filter-side');filters.id='qr-filters';filters.hidden=true;
  const head=document.querySelector('.qr-workbench .section-head');
  const actions=document.createElement('div');actions.className='compact-title-actions';
  actions.innerHTML='<button class="btn filter-arrow" id="filter-arrow" aria-controls="qr-filters" aria-expanded="false" title="Apri filtri">▶ Filtri</button><button class="btn" id="scanner-open">Lista scanner</button><button class="btn primary" id="print-open">Stampa QR</button>';
  head.append(actions);
  document.getElementById('filter-arrow').onclick=()=>{const closed=layout.classList.toggle('filters-closed');filters.hidden=closed;const button=document.getElementById('filter-arrow');button.textContent=closed?'▶ Filtri':'◀ Filtri';button.setAttribute('aria-expanded',String(!closed));button.title=closed?'Apri filtri':'Chiudi filtri';};
  const pager=document.querySelector('.show-all-actions');
  document.querySelector('.show-all-row').remove();
  qrWindowFooter.innerHTML='<span id="compact-count"></span>';qrWindowFooter.append(pager);
  document.querySelector('label[for="code-page-size"]').textContent='QR per pagina';
  const pageSize=document.getElementById('code-page-size');
  pageSize.innerHTML='<option value="50">50</option><option value="100">100</option><option value="200">200</option><option value="0">Tutti</option>';
  codePageSize=Number(localStorage.getItem('stqc_qr_flat_page_size')||0);
  if(![0,50,100,200].includes(codePageSize))codePageSize=0;
  codePage=0;
  setCodePageSize=function(value){codePageSize=Number(value)||0;localStorage.setItem('stqc_qr_flat_page_size',String(codePageSize));codePage=0;render();document.getElementById('qr-scroll-window').scrollTop=0;};
  moveCodePage=function(delta){codePage+=delta;render();document.getElementById('qr-scroll-window').scrollTop=0;};
  render=function(){
    const rows=visible();
    const size=codePageSize||Math.max(rows.length,1);
    const pages=Math.max(1,Math.ceil(rows.length/size));
    codePage=Math.min(Math.max(0,codePage),pages-1);
    const shown=rows.slice(codePage*size,(codePage+1)*size);
    grid.classList.add('qr-record-list');
    grid.innerHTML='<table class="qr-record-table"><thead><tr><th>Seleziona</th><th>Pezzo</th><th>Progressivo</th><th>Profilo</th><th>Qualità</th><th></th></tr></thead><tbody>'+shown.map(row=>`<tr data-record="${esc(row.uuid)}" tabindex="0" aria-label="Apri ${esc(pieceDisplayTitle(row))}"><td><input type="checkbox" data-select="${esc(row.uuid)}" aria-label="Seleziona ${esc(pieceDisplayTitle(row))}" ${selected.has(row.uuid)?'checked':''}></td><td><strong>${esc(pieceDisplayCode(row))}</strong></td><td>${esc(pieceProgressLabel(row))}</td><td>${esc(row.profilo||'—')}</td><td>${esc(row.materiale||row.qualita||'—')}</td><td>Apri ›</td></tr>`).join('')+'</tbody></table>'+(shown.length?'':'<div class="empty">Nessun QR trovato.</div>');
    pageSize.value=String(codePageSize);
    document.getElementById('code-page-label').textContent=`Pagina ${codePage+1} / ${pages}`;
    document.getElementById('code-page-prev').disabled=codePage===0;
    document.getElementById('code-page-next').disabled=codePage===pages-1;
    document.getElementById('compact-count').textContent=`${shown.length} / ${rows.length} QR`;
    renderQrActions(rows.length);renderNotes();
  };
  renderQrActions=function(visibleCount){qrActionBar.innerHTML=`<span>${selected.size} selezionati · ${visibleCount} QR filtrati</span><div><button class="btn" onclick="selectVisible()">Seleziona tutti i filtrati</button>${selected.size?'<button class="btn" onclick="clearSelected()">Deseleziona</button>':''}</div>`;document.getElementById('print-open').textContent=selected.size?`Stampa QR (${selected.size})`:'Stampa QR';};
  const recordDialog=document.createElement('dialog');recordDialog.className='qr-operation-drawer qr-record-drawer';
  recordDialog.setAttribute('aria-label','Dettaglio QR pezzo');document.body.append(recordDialog);
  const editFields=[['tipo','Tipo'],['profilo','Profilo'],['qualita','Qualità'],['assemblato','Assemblato'],['stato','Stato'],['nota','Note']];
  let record=null,unlocked=false,saving=false,recordOpener=null;
  function renderRecord(){
    recordDialog.innerHTML=`<div class="operation-head"><h2>${esc(pieceDisplayTitle(record))}</h2><button class="btn" data-close-record>Chiudi ×</button></div><div class="operation-content record-body"><img class="record-large-qr" src="${esc(record.qr_image_url)}" alt="QR ${esc(pieceDisplayTitle(record))}"><p>UUID: ${esc(record.uuid)}</p><div class="record-dimensions">Lunghezza: ${esc(record.lunghezza_mm??'—')} mm · Larghezza: ${esc(record.larghezza_mm??'—')} mm · Spessore: ${esc(record.spessore_mm??'—')} mm · Peso: ${esc(record.peso_kg??'—')} kg</div><button class="btn" id="record-lock" aria-pressed="${unlocked}">${unlocked?'🔓 Blocca modifiche':'🔒 Abilita modifiche manuali'}</button><section class="record-origin"><h3>Materiale grezzo di origine</h3>${Object.entries(record.materiale_origine_dati||{}).map(([label,value])=>`<p><strong>${esc(label)}:</strong> ${esc(value??'—')}</p>`).join('')||'<p>Nessun grezzo collegato.</p>'}</section><form id="record-form"><div class="record-fields">${editFields.map(([key,label])=>`<label>${label}<input name="${key}" value="${esc((key==='qualita'?record.materiale??record.qualita:record[key])??'')}" ${unlocked?'':'disabled'}></label>`).join('')}</div><p id="record-error" role="status"></p><button class="btn primary" type="submit" ${unlocked?'':'disabled'}>Salva modifiche</button></form></div>`;
    recordDialog.querySelector('[data-close-record]').onclick=()=>recordDialog.close();
    recordDialog.querySelector('#record-lock').onclick=()=>{if(saving)return;unlocked=!unlocked;renderRecord();};
    recordDialog.querySelector('form').onsubmit=async event=>{
      event.preventDefault();if(!unlocked||saving)return;
      const payload=Object.fromEntries(new FormData(event.target));saving=true;
      recordDialog.querySelectorAll('button,input').forEach(element=>element.disabled=true);
      try{
        const response=await fetch(`/api/v1/commesse/${commessaId}/qr/items/${record.id}`,{method:'PATCH',headers:auth(),body:JSON.stringify(payload)});
        const result=await response.json().catch(()=>({}));if(!response.ok)throw new Error(result.detail||'Salvataggio non riuscito');
        items=items.map(item=>item.id===result.id?result:item);record=result;unlocked=false;
        const activeFilters=[...attributeFilters.querySelectorAll('[data-filter]')].map(el=>[el.dataset.filter,el.value]);setupPageFilters();activeFilters.forEach(([key,value])=>{const el=attributeFilters.querySelector(`[data-filter="${key}"]`);if(el){if(el.tagName==='SELECT'&&value&&![...el.options].some(option=>option.value===value))el.add(new Option(value,value));el.value=value;}});render();renderRecord();recordDialog.querySelector('#record-error').textContent='Modifiche salvate';
      }catch(error){recordDialog.querySelector('#record-error').textContent=error.message;recordDialog.querySelectorAll('button,input').forEach(element=>element.disabled=false);}
      finally{saving=false;}
    };
  }
  function openRecord(uuid){record=items.find(item=>item.uuid===uuid);if(!record)return;recordOpener=document.activeElement;unlocked=false;renderRecord();recordDialog.showModal();}
  grid.addEventListener('click',event=>{const check=event.target.closest('[data-select]');if(check){toggleSelect(check.dataset.select);return;}const row=event.target.closest('[data-record]');if(row)openRecord(row.dataset.record);});
  grid.addEventListener('keydown',event=>{if(event.target.matches('[data-record]')&&['Enter',' '].includes(event.key)){event.preventDefault();openRecord(event.target.dataset.record);}});
  recordDialog.addEventListener('cancel',event=>{if(saving)event.preventDefault();});
  recordDialog.addEventListener('close',()=>recordOpener?.focus());
  let opener=null,printKey=null;
  const dialog=document.createElement('dialog');dialog.className='qr-operation-drawer';dialog.setAttribute('aria-labelledby','operation-title');
  dialog.innerHTML='<div class="operation-head"><h2 id="operation-title"></h2><button class="btn" id="operation-close">Chiudi ×</button></div><div class="operation-content"></div>';
  document.body.append(dialog);
  const content=dialog.querySelector('.operation-content');
  const stations=document.getElementById('inline-stations');stations.open=true;stations.hidden=true;content.append(stations);
  const frame=document.createElement('iframe');frame.title='Configurazione e anteprima stampa QR';frame.hidden=true;content.append(frame);
  const message=document.createElement('p');message.className='operation-message';message.hidden=true;content.append(message);
  function open(title){opener=document.activeElement;document.getElementById('operation-title').textContent=title;dialog.showModal();}
  function close(){dialog.close();}
  document.getElementById('operation-close').onclick=close;
  dialog.addEventListener('click',event=>{if(event.target===dialog){const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)close();}});
  dialog.addEventListener('close',()=>{if(printKey)sessionStorage.removeItem(printKey);frame.src='about:blank';opener?.focus();});
  toggleStationPanel=function(){if(window.PhaseScanners){window.PhaseScanners.open();}else{alert('Lista scanner non caricata. Ricarica la pagina.');}};
  document.getElementById('scanner-open').onclick=toggleStationPanel;
  function printDrawer(){
    stations.hidden=true;frame.hidden=true;message.hidden=true;
    const rows=selectedItems().map(x=>({title:(x.commessa||commessaCode||'COMMESSA')+' '+pieceDisplayCode(x),detail:"Q.TA' "+pieceProgressLabel(x)+(x.peso_kg!=null?' KG '+Math.round(Number(x.peso_kg)||0):''),image:x.qr_image_url}));
    open(`Stampa QR · ${rows.length} selezionati`);
    if(!rows.length||rows.length>2000){message.hidden=false;message.textContent=rows.length?'Seleziona al massimo 2000 QR per stampa.':'Seleziona i codici o i singoli QR nell’elenco, poi riapri Stampa QR.';return;}
    printKey='qr-print-'+crypto.randomUUID();
    try{sessionStorage.setItem(printKey,JSON.stringify(rows));frame.src='/static/qr-print.html#'+printKey;frame.hidden=false;}
    catch(error){message.hidden=false;message.textContent='Troppi dati per la stampa: seleziona meno QR.';}
  }
  printSelectedQr=printDrawer;
  document.getElementById('print-open').onclick=printDrawer;
  render();
})();
