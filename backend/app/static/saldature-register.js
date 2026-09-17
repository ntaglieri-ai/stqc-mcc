(() => {
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt=value=>Number(value||0).toLocaleString('it-IT',{maximumFractionDigits:2});
  const ref=decodeURIComponent(location.pathname.split('/').filter(Boolean)[1]||'');
  const auth=()=>({Authorization:'Bearer '+sessionStorage.getItem('stqc_token')});
  let data={items:[],source_available:false},commessaId=null,page=0,printKey=null;
  const selected=new Set();
  async function get(url){const response=await fetch(url,{headers:auth()});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Caricamento non riuscito');return result;}
  function filtered(){const q=$('search').value.trim().toLowerCase(),material=$('material').value;return data.items.filter(row=>(!material||row.materiale===material)&&(!q||[row.codice,row.profilo,row.materiale].join(' ').toLowerCase().includes(q)));}
  function render(){
    const rows=filtered(),size=Number($('page-size').value),pages=Math.max(1,Math.ceil(rows.length/size));page=Math.min(page,pages-1);
    const visible=rows.slice(page*size,(page+1)*size);
    $('rows').innerHTML=visible.map(row=>`<article class="welding-row"><input type="checkbox" data-select="${esc(row.id)}" aria-label="Seleziona QR ${esc(row.codice)} numero ${row.progressivo}" ${selected.has(row.id)?'checked':''}><img class="welding-qr" loading="lazy" src="${esc(row.qr_image_url)}" alt="QR assemblato ${esc(row.codice)} numero ${row.progressivo}"><span class="parent-name"><strong>${esc(row.codice)}</strong><span class="tag">Assemblato ${row.progressivo} / ${row.totale_codice}</span></span><span class="parent-meta">${[row.profilo,row.materiale].filter(Boolean).map(esc).join(' &middot; ')}</span><span class="quantity">1 assemblato</span></article>`).join('')||`<div class="empty">${!data.source_available?'Carica il file Assemblaggi in Analisi Distinta per visualizzare gli assemblati.':'Nessun assemblato trovato.'}</div>`;
    $('rows').querySelectorAll('[data-select]').forEach(input=>{input.onclick=event=>event.stopPropagation();input.onchange=()=>{input.checked?selected.add(input.dataset.select):selected.delete(input.dataset.select);updateSelection();};});
    $('count').textContent=`${rows.length} assemblati filtrati / ${data.items.length} · Origine: file Assemblaggi`;
    $('page-count').textContent=`${page+1} / ${pages}`;$('previous').disabled=page===0;$('next').disabled=page>=pages-1;updateSelection();
  }
  function updateSelection(){$('selection-count').textContent=`${selected.size} QR assemblato selezionati`;$('print-open').textContent=selected.size?`Stampa QR (${selected.size})`:'Stampa QR';}
  async function load(){
    $('reload').disabled=true;
    try{
      if(!commessaId){const commessa=await get('/api/v1/commesse/resolve/'+encodeURIComponent(ref));commessaId=commessa.id;}
      data=await get(`/api/v1/commesse/${commessaId}/analisi/saldature`);
      const codes=new Set(data.items.map(row=>row.id));for(const code of selected)if(!codes.has(code))selected.delete(code);
      $('analysis-link').href='/commesse/'+encodeURIComponent(data.commessa.codice)+'/analisi';
      const material=$('material').value;
      $('material').innerHTML='<option value="">Tutti</option>'+[...new Set(data.items.map(row=>row.materiale).filter(Boolean))].sort().map(value=>`<option value="${esc(value)}">${esc(value)}</option>`).join('');
      if([...$('material').options].some(option=>option.value===material))$('material').value=material;
      render();
    }catch(error){$('rows').innerHTML=`<div class="empty" role="alert">${esc(error.message)}</div>`;$('selection-count').textContent='Caricamento non riuscito';}
    finally{$('reload').disabled=false;}
  }
  $('filters-toggle').onclick=()=>{const hidden=!$('assembly-filters').hidden;$('assembly-filters').hidden=hidden;$('filters-toggle').setAttribute('aria-expanded',String(!hidden));$('filters-toggle').innerHTML=hidden?'&#9654; Filtri':'&#9664; Filtri';};
  $('search').oninput=$('material').onchange=$('page-size').onchange=()=>{page=0;render();};
  $('reset').onclick=()=>{$('search').value='';$('material').value='';page=0;render();};
  $('previous').onclick=()=>{page--;render();};$('next').onclick=()=>{page++;render();};
  $('select-all').onclick=()=>{filtered().forEach(row=>selected.add(row.id));render();};$('clear').onclick=()=>{selected.clear();render();};
  $('scanner-open').onclick=()=>window.PhaseScanners.open();$('reload').onclick=load;
  $('print-open').onclick=()=>{
    const rows=data.items.filter(row=>selected.has(row.id)).map(row=>({title:data.commessa.codice+' '+row.codice,detail:'Assemblato '+row.progressivo+' / '+row.totale_codice,image:row.qr_image_url}));
    $('print-frame').hidden=true;$('print-message').textContent='';$('print-drawer').showModal();
    if(!rows.length||rows.length>2000){$('print-message').textContent=rows.length?'Seleziona al massimo 2000 QR.':'Seleziona i QR assemblato nelle righe prima di stampare.';return;}
    printKey='qr-print-'+crypto.randomUUID();
    try{sessionStorage.setItem(printKey,JSON.stringify(rows));$('print-frame').src='/static/qr-print.html#'+printKey;$('print-frame').hidden=false;}catch(error){$('print-message').textContent='Dati troppo grandi: seleziona meno QR.';}
  };
  $('print-close').onclick=()=>$('print-drawer').close();
  $('print-drawer').addEventListener('close',()=>{if(printKey)sessionStorage.removeItem(printKey);printKey=null;$('print-frame').src='about:blank';$('print-open').focus();});
  if(!sessionStorage.getItem('stqc_token'))location.replace('/login');else load();
})();
