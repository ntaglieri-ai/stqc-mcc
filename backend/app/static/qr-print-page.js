const $ = id => document.getElementById(id);
const fields=['width','height','margin','cols','rows','sizeMode','qr','font','format'];
let items=[],profiles={};
try {const key=location.hash.slice(1);items=JSON.parse(sessionStorage.getItem(key)||'[]');sessionStorage.removeItem(key);profiles=JSON.parse(localStorage.getItem('qr-print-profiles')||'{}');}catch(_){}
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function values(){return Object.fromEntries(fields.map(k=>[k,$(k).value]));}
function apply(s){fields.forEach(k=>{if(s[k]!=null)$(k).value=s[k]});render();}
function profileOptions(){ $('profiles').innerHTML='<option value="">Personalizzato</option>'+Object.keys(profiles).map(k=>`<option value="${esc(k)}">${esc(k)}</option>`).join(''); }
function render(){
 $('print').disabled=true;$('error').textContent='';
 const s=values(),w=+s.width,h=+s.height,m=+s.margin,c=+s.cols,r=+s.rows,f=+s.font;
 if(!items.length){$('error').textContent='Nessun QR disponibile. Riapri la stampa dalla pagina di origine.';return;}
 if(fields.some(k=>$(k).type==='number'&&!$(k).checkValidity())||!Number.isInteger(c)||!Number.isInteger(r)){ $('error').textContent='Controlla i valori inseriti.';return; }
 const cellW=(w-2*m)/c,cellH=(h-2*m)/r;
 const horizontal=cellW/cellH>1.4;
 const maxQr=horizontal?Math.min(cellH-6,cellW*.45-4):Math.min(cellW-6,cellH-6-f*.3528*5);
 const qr=s.sizeMode==='auto'?maxQr:+s.qr;
 if(qr<10||qr>maxQr){$('error').textContent='Il QR e il testo non entrano: riduci righe/colonne, margini o dimensioni.';$('preview').innerHTML='';return;}
 $('dimensions').textContent=`@page{size:${w}mm ${h}mm;margin:0}.sheet{width:${w}mm;height:${h}mm;padding:${m}mm;grid-template-columns:repeat(${c},1fr);grid-template-rows:repeat(${r},1fr)}.label{font-size:${f}pt}.label img{width:${qr}mm;height:${qr}mm}.label.horizontal{flex-direction:row;gap:3mm}.label.horizontal .copy{flex:1;min-width:0}.copy{width:100%}`;
 let html='';for(let i=0;i<items.length;i+=c*r){html+='<section class="sheet">'+items.slice(i,i+c*r).map(x=>`<article class="label ${horizontal?'horizontal':''}"><img src="${esc(x.image)}" alt="QR"><div class="copy"><div class="text title">${esc(x.title)}</div><div class="text">${esc(x.action||'')}</div><div class="text detail">${esc(x.detail||'')}</div></div></article>`).join('')+'</section>';}
 $('preview').innerHTML=html;
 const overflow=[...document.querySelectorAll('.label')].some(el=>el.scrollHeight>el.clientHeight+2||el.scrollWidth>el.clientWidth+2);
 $('error').textContent=overflow?'Il testo non entra: riduci il carattere o il QR, oppure usa meno righe/colonne.':`${items.length} QR · ${Math.ceil(items.length/(c*r))} fogli · QR ${qr.toFixed(1)} mm`;
 $('print').disabled=overflow;
}
fields.forEach(k=>$(k).addEventListener('change',render));
$('format').addEventListener('change',()=>{const sizes={a4:[210,297],a5:[148,210],label:[100,50]};const size=sizes[$('format').value];if(size){$('width').value=size[0];$('height').value=size[1];$('cols').value=1;$('rows').value=1;if($('format').value==='label')$('margin').value=2;}render();});
$('rotate').onclick=()=>{const w=$('width').value;$('width').value=$('height').value;$('height').value=w;render();};
$('save').onclick=()=>{const name=$('profileName').value.trim();if(!name)return alert('Indica un nome per il profilo.');profiles[name]=values();try{localStorage.setItem('qr-print-profiles',JSON.stringify(profiles));profileOptions();$('profiles').value=name;}catch(_){alert('Impossibile salvare il profilo nel browser.');}};
$('profiles').onchange=()=>{const name=$('profiles').value;if(profiles[name]){$('profileName').value=name;apply(profiles[name]);}};
$('print').onclick=async()=>{const button=$('print');button.disabled=true;try{await Promise.all([...document.images].map(img=>img.decode()));window.print();}catch(_){$('error').textContent='Immagine QR non disponibile: ricarica la stampa.';return;}finally{button.disabled=false;}};
profileOptions();render();
