(() => {
 const $=id=>document.getElementById(id),token=encodeURIComponent(decodeURIComponent(location.pathname.split('/').pop()));
 const base='/api/v1/scanner/netum/'+token;
 const labels={officina:'Lavorazioni officina',assemblaggi:'Assemblaggi',saldature:'Saldature',lavorazioni:'Lavorazioni','in-cantiere':'Spedizione',magazzino:'Magazzino'};
 let context=null,busy=false,loading=false;
 async function api(path,options={}){const response=await fetch(base+path,options);const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.detail||'Errore server '+response.status);return data;}
 function renderContext(){
  $('name').textContent=context.name+' - '+context.code;
  const multi=context.mode==='MULTI_POSTAZIONE';$('station-label').hidden=!multi;$('station').disabled=!multi||busy;
  $('station').replaceChildren(new Option('Scegli la postazione',''));
  context.stations.forEach(s=>$('station').add(new Option((labels[s.fase]||s.fase)+' - '+s.name,String(s.id))));
  $('station').value=context.postazione_id||'';
  const station=context.stations.find(s=>s.id===context.postazione_id);
  $('phase').textContent=multi?(station?'Fase: '+(labels[station.fase]||station.fase):'Seleziona la postazione prima di scansionare.'):'Configurazione: '+context.mode;
  $('mode-note').textContent=multi?'Le letture vengono raccolte per commessa, nella fase della postazione selezionata.':'Questo scanner usa la configurazione impostata nelle Impostazioni.';
  $('send').disabled=busy||(multi&&!station);$('payload').disabled=multi&&!station;
  $('events').replaceChildren();
  context.events.forEach(e=>{const row=document.createElement('div');row.className='row';const title=document.createElement('strong');title.textContent=e.code;const detail=document.createElement('span');detail.textContent=(labels[e.fase]||e.fase)+' - '+e.station+' - '+new Date(e.timestamp+'Z').toLocaleString('it-IT');row.append(title,detail);$('events').append(row);});
  if(!context.events.length)$('events').textContent='Nessuna lettura multi-postazione registrata.';
 }
 async function load(){if(busy||loading)return;loading=true;try{context=await api('/context');renderContext();$('context-error').textContent='';}catch(e){$('context-error').textContent=e.message;$('send').disabled=true;}finally{loading=false;}}
 $('station').onchange=async()=>{busy=true;$('station').disabled=true;$('send').disabled=true;try{await api('/station',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({postazione_id:Number($('station').value)})});$('feedback').textContent='Postazione aggiornata.';}catch(e){$('feedback').textContent=e.message;}finally{busy=false;await load();$('payload').focus();}};
 $('scan-form').onsubmit=async event=>{event.preventDefault();if(busy)return;busy=true;$('send').disabled=true;$('station').disabled=true;try{const data=await api('/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({msg:$('payload').value,id:crypto.randomUUID()})});$('feedback').textContent=data.msg;if(data.ok)$('payload').value='';}catch(e){$('feedback').textContent=e.message;}finally{busy=false;await load();$('payload').focus();}};
 $('camera').href='/mobile-scan/'+token;load();setInterval(load,3000);
})();
