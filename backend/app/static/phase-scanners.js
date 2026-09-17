(() => {
  if(window.PhaseScanners)return;
  const phase=location.pathname==='/magazzino'?'magazzino':location.pathname.split('/').filter(Boolean)[2];
  if(!['officina','assemblaggi','saldature','lavorazioni','in-cantiere','magazzino'].includes(phase))return;
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const style=document.createElement('style');style.textContent='.phase-scanner-dialog{position:fixed;inset:0 0 0 auto;margin:0;width:min(680px,96vw);height:100dvh;max-height:100dvh;padding:22px;background:#132640;color:#eaf2ff;border:1px solid #35527a}.phase-scanner-dialog::backdrop{background:#030b16bb}.phase-scanner-head{display:flex;align-items:center;justify-content:space-between;gap:16px}.phase-scanner-dialog button,.phase-scanner-button{padding:9px 14px;background:#203958;color:#eaf2ff;border:1px solid #496b95;border-radius:10px;cursor:pointer;font-weight:700}.phase-scanner-row{padding:16px 0;border-bottom:1px solid #35527a}.phase-scanner-row p{font-size:13px;color:#a8bfda}.phase-scanner-button{margin:0 0 12px auto;display:block}';document.head.append(style);
  let dialog,opener;
  async function open(){
    opener=document.activeElement;
    if(!dialog){dialog=document.createElement('dialog');dialog.className='phase-scanner-dialog';dialog.setAttribute('aria-label','Lista scanner della fase');dialog.innerHTML='<div class="phase-scanner-head"><h2>Lista scanner</h2><button type="button">Chiudi ×</button></div><div class="phase-scanner-list" role="status"></div>';dialog.querySelector('button').onclick=()=>dialog.close();dialog.addEventListener('close',()=>opener?.focus());document.body.append(dialog);}
    const list=dialog.querySelector('.phase-scanner-list');list.textContent='Caricamento…';if(!dialog.open)dialog.showModal();
    try{const response=await fetch('/api/v1/officina/scanner-per-fase/'+phase,{headers:{Authorization:'Bearer '+sessionStorage.getItem('stqc_token')}});const data=await response.json();if(!response.ok)throw new Error(data.detail||'Caricamento non riuscito');list.innerHTML=data.items.map(row=>`<article class="phase-scanner-row"><strong>${esc(row.code)} · ${esc(row.name)}</strong><p>${esc(row.mode)}${row.station?' · '+esc(row.station):''}</p><span>${row.active?'Attivo':'Disattivato'}</span></article>`).join('')||'<p>Nessuno scanner configurato per questa fase.</p>';}catch(error){list.textContent=error.message;}
  }
  window.PhaseScanners={open};
  function setup(){if(phase==='officina'||document.getElementById('scanner-open'))return;const main=document.querySelector('main');if(!main)return;const button=document.createElement('button');button.className='phase-scanner-button';button.textContent='Lista scanner';button.type='button';button.onclick=open;main.prepend(button);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setup);else setup();
})();
