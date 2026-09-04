(() => {
  const token = sessionStorage.getItem('stqc_token');
  const profile = sessionStorage.getItem('stqc_profilo');
  if (!token) { location.replace('/login'); return; }
  if (!['Direttore','Capo Officina','Progettazione','Admin'].includes(profile)) { location.replace('/'); return; }
  const sections = {
    '/dashboard/monitoring': ['Monitoring commesse', 'Stato e avanzamento delle commesse', 'Qui costruiremo la vista a lista delle commesse, con i relativi stati e l’accesso al dettaglio.'],
    '/dashboard/statistiche-reportistica': ['Statistiche&Reportistica', 'Analisi dei dati e report', 'Qui definiremo le statistiche e i report, con le informazioni da consultare e confrontare.']
  };
  const section = sections[location.pathname];
  if (!section) return;
  document.title = section[0] + ' · MCC';
  document.getElementById('section-name').textContent = section[0];
  document.getElementById('page-title').textContent = section[0];
  document.getElementById('page-intro').textContent = section[1];
  document.getElementById('section-description').textContent = section[2];
  if (location.pathname !== '/dashboard/monitoring') return;

  document.querySelector('main').classList.add('monitor-page');
  document.getElementById('page-intro').hidden = true;
  document.querySelector('.eyebrow').hidden = true;
  const workspace = document.querySelector('.workspace');
  workspace.classList.add('monitoring');
  const selected = new URLSearchParams(location.search).get('commessa');
  if (selected) {
    showCommessa(selected);
    return;
  }
  workspace.innerHTML = `<div class="monitor-toolbar"><label class="sr-only" for="commessa-search">Cerca commessa</label><input id="commessa-search" type="search" placeholder="Cerca per codice, cliente o descrizione"><button type="button" id="refresh">Aggiorna</button></div>
    <p id="monitor-status" role="status" aria-live="polite"></p><div id="monitor-list"></div>`;
  const status = document.getElementById('monitor-status');
  const list = document.getElementById('monitor-list');
  const search = document.getElementById('commessa-search');
  const refresh = document.getElementById('refresh');
  let commesse = [];
  const labels = { APERTA: 'Aperta', IN_PRODUZIONE: 'In produzione', SOSPESA: 'Sospesa', CHIUSA: 'Chiusa' };
  function render() {
    const query = search.value.trim().toLocaleLowerCase('it');
    const rows = commesse.filter(c => [c.codice, c.cliente, c.descrizione].some(value => String(value || '').toLocaleLowerCase('it').includes(query)));
    list.replaceChildren();
    status.textContent = `${rows.length} commesse visualizzate su ${commesse.length}`;
    if (!rows.length) {
      status.textContent = query ? 'Nessuna commessa corrisponde alla ricerca.' : 'Nessuna commessa presente.';
      return;
    }
    const table = document.createElement('table');
    table.innerHTML = '<caption class="sr-only">Elenco commesse in tutti gli stati</caption><thead><tr><th scope="col">Codice</th><th scope="col">Cliente</th><th scope="col">Descrizione</th><th scope="col">Stato</th><th scope="col">Consegna prevista</th></tr></thead>';
    const body = document.createElement('tbody');
    for (const c of rows) {
      const row = document.createElement('tr');
      const date = c.data_consegna_prevista ? c.data_consegna_prevista.split('-').reverse().join('/') : '—';
      for (const value of [c.codice, c.cliente, c.descrizione, labels[c.status] || c.status, date]) {
        const cell = document.createElement('td');
        cell.textContent = value || '—';
        row.appendChild(cell);
      }
      body.appendChild(row);
      const link = document.createElement('a');
      link.href = `/dashboard/monitoring?commessa=${encodeURIComponent(c.id)}`;
      link.textContent = c.codice;
      row.firstChild.replaceChildren(link);
    }
    table.appendChild(body);
    list.appendChild(table);
  }
  async function load() {
    refresh.disabled = true;
    search.disabled = true;
    list.replaceChildren();
    status.textContent = 'Caricamento commesse…';
    try {
      const items = [];
      const pageSize = 100;
      for (let skip = 0; ; skip += pageSize) {
        const response = await fetch(`/api/v1/commesse?skip=${skip}&limit=${pageSize}`, { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' });
        if (response.status === 401) { location.replace('/login'); return; }
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const page = await response.json();
        if (!Array.isArray(page)) throw new Error('Risposta non valida');
        items.push(...page);
        if (page.length < pageSize) break;
      }
      commesse = items;
      render();
    } catch (error) {
      status.textContent = 'Impossibile caricare le commesse. Premi Aggiorna per riprovare.';
    } finally {
      refresh.disabled = false;
      search.disabled = false;
    }
  }
  search.addEventListener('input', render);
  refresh.addEventListener('click', load);
  load();

  async function showCommessa(id) {
    workspace.replaceChildren();
    const back = document.createElement('a');
    back.href = '/dashboard/monitoring';
    back.textContent = '← Tutte le commesse';
    back.className = 'monitor-back';
    workspace.append(back);
    const result = document.createElement('div');
    result.setAttribute('aria-live', 'polite');
    result.textContent = 'Caricamento riepilogo…';
    workspace.append(result);
    const liveStatus = document.createElement('p');
    liveStatus.className = 'monitor-live';
    liveStatus.setAttribute('role', 'status');
    workspace.insertBefore(liveStatus, result);
    let previousData = null;
    let grouped = false;
    let busy = false;
    let stopped = false;
    let timer;
    const controller = new AbortController();
    const date = value => value ? new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).toLocaleString('it-IT') : 'Non registrato';
    const readable = value => value ? String(value).replaceAll('_', ' ') : 'Non registrato';
    function section(title, note, headers, rows) {
      const panel = document.createElement('details');
      panel.className = 'monitor-phase';
      panel.dataset.phase = title;
      panel.open = true;
      const summary = document.createElement('summary');
      summary.textContent = title;
      panel.append(summary);
      const info = document.createElement('p');
      info.textContent = note;
      panel.append(info);
      if (rows.length) {
        const wrapper = document.createElement('div');
        wrapper.className = 'phase-table';
        const table = document.createElement('table');
        const head = document.createElement('thead');
        const tr = document.createElement('tr');
        headers.forEach(label => { const th = document.createElement('th'); th.scope = 'col'; th.textContent = label; tr.append(th); });
        head.append(tr); table.append(head);
        const body = document.createElement('tbody');
        rows.forEach(values => {
          const row = document.createElement('tr');
          values.forEach((value, index) => {
            const td = document.createElement('td');
            const text = value ?? 'Non registrato';
            if (headers[index] === 'Stato' || headers[index] === 'Esito') {
              const badge = document.createElement('span');
              badge.className = 'monitor-badge';
              const state = String(text).toUpperCase();
              badge.dataset.tone = /^(COMPLETATA|OK)/.test(state) ? 'success' : /^(ON GOING|IN CORSO)/.test(state) ? 'active' : /^(WARNING|ERROR|KO)/.test(state) ? 'warning' : 'neutral';
              badge.textContent = text;
              td.append(badge);
            } else {
              td.textContent = text;
              if (String(text).startsWith('Non registrat') || text === '—') td.className = 'monitor-missing';
            }
            row.append(td);
          });
          body.append(row);
        });
        table.append(body); wrapper.append(table); panel.append(wrapper);
      }
      result.append(panel);
      return panel;
    }
    async function refreshDetail() {
    if (busy || stopped || document.hidden) return;
    busy = true;
    try {
      const response = await fetch(`/api/v1/commesse/${encodeURIComponent(id)}/monitoring`, {headers: {Authorization: `Bearer ${token}`}, cache: 'no-store', signal: controller.signal});
      if (response.status === 401) { stopped = true; location.replace('/login'); return; }
      if (!response.ok) {
        const failure = await response.json().catch(() => ({}));
        throw new Error(response.status === 404
          ? (failure.detail === 'Commessa non trovata' ? 'Commessa non trovata.' : 'Endpoint Monitoring non disponibile: riavviare il server locale.')
          : 'Caricamento non riuscito.');
      }
      const data = await response.json();
      liveStatus.textContent = `Aggiornamento automatico ogni 3 secondi · Ultimo controllo ${new Date().toLocaleTimeString('it-IT')}`;
      liveStatus.dataset.state = 'connected';
      const serialized = JSON.stringify(data);
      if (serialized === previousData) return;
      const openSections = new Map(Array.from(result.querySelectorAll('details')).map(panel => [panel.querySelector('summary').textContent, panel.open]));
      const scrollX = window.scrollX, scrollY = window.scrollY;
      const horizontal = Array.from(result.querySelectorAll('.phase-table')).map(table => table.scrollLeft);
      const groupedFocused = document.activeElement === result.querySelector('input[type="checkbox"]');
      document.getElementById('page-title').textContent = data.commessa.codice;
      document.title = `${data.commessa.codice} · Monitoring`;
      result.replaceChildren();
      const meta = document.createElement('p');
      meta.className = 'monitor-meta';
      meta.textContent = `${data.commessa.cliente || 'Cliente non indicato'} · ${readable(data.commessa.stato)} · Consegna: ${data.commessa.consegna || 'Non indicata'} · Revisione: ${data.revisione || 'Non presente'}`;
      result.append(meta);
      section('Progettazione', 'Le date non disponibili per le attività precedenti sono indicate come non registrate.', ['Fase', 'Stato', 'Inizio', 'Fine'], data.progettazione.map(r => [r.label, r.fine ? 'Completata' : r.inizio ? 'On going' : 'Da fare', r.inizio ? date(r.iniziata_at) : '—', r.fine ? date(r.completata_at) : '—']));
      const readings = data.officina_letture || [];
      const workshop = section('Officina', 'Una riga per lettura fisica del pezzo, comprese le ripetizioni. Posizione = marca/posizione del pezzo. Tempi da definire.', [], []);
      const toggleLabel = document.createElement('label');
      toggleLabel.className = 'monitor-group-toggle';
      const toggle = document.createElement('input');
      toggle.type = 'checkbox';
      toggle.checked = grouped;
      toggle.style.width = 'auto';
      toggleLabel.append(toggle, ' Raggruppa per posizione');
      workshop.append(toggleLabel);
      const readingList = document.createElement('div');
      workshop.append(readingList);
      function renderReadings() {
        readingList.replaceChildren();
        if (!readings.length) { readingList.textContent = 'Nessuna lettura fisica collegata ai pezzi della commessa.'; return; }
        const groups = new Map();
        readings.forEach(r => { const key = toggle.checked ? (r.posizione || 'Posizione non registrata') : ''; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(r); });
        for (const [position, rows] of groups) {
          if (position) { const heading = document.createElement('h3'); heading.textContent = `${position} · ${rows.length} scansioni`; readingList.append(heading); }
          const panel = section('Letture', '', ['Scan', 'Posizione / Marca', 'Pezzo', 'QR', 'Lavorazione', 'Postazione', 'Esito'], rows.map(r => [r.scan_id, r.posizione, `#${r.piece_id} · progressivo ${r.progressivo}`, r.qr, r.lavorazione, r.postazione, `${r.esito} · ${r.messaggio}`]));
          readingList.append(panel.querySelector('.phase-table'));
          panel.remove();
        }
      }
      toggle.addEventListener('change', () => { grouped = toggle.checked; renderReadings(); });
      renderReadings();
      for (const [key, title] of [['assemblaggi', 'Assemblaggi']]) {
        section(title, data[key].length ? 'Sequenza cronologica, tutte le revisioni. Durata solo per sessioni chiuse e collegate; non è il tempo tra due scansioni.' : 'Nessuna scansione operativa registrata.', ['Marca', 'Postazione', 'Evento', 'Data e ora', 'Durata sessione'], data[key].map(r => [r.marca, r.postazione, readable(r.evento), date(r.data), r.durata_secondi == null ? 'Non registrata' : `${Math.floor(r.durata_secondi / 60)} min ${r.durata_secondi % 60} s`]));
      }
      const counts = rows => Object.entries(rows.reduce((acc, r) => {acc[r.stato] = (acc[r.stato] || 0) + 1; return acc;}, {})).map(([state, n]) => [readable(state), n]);
      section('Lavorazioni esterne', 'Stati della lista corrente. Cronologia scan e destinazione delle spedizioni esterne non disponibili nei dati collegati.', ['Stato registrato', 'Righe lista'], counts(data.lavorazioni_esterne));
      const shipping = data.spedizione;
      section('Spedizione', `${shipping.spediti ?? 'Non disponibile'} pezzi spediti / ${shipping.previsti ?? 'Non disponibile'} previsti nella lista spedizione della revisione corrente. Storico DDT di tutte le revisioni; DDT generato non equivale a consegna confermata.`, ['DDT', 'Titolo', 'Data', 'Quantità nel DDT'], shipping.ddt.map(d => [d.numero, d.titolo, date(d.created_at), d.materiali.reduce((n, r) => n + Number(r.quantita || 0), 0)]));
      if (shipping.scan.length) section('Letture spedizione ad hoc', 'Ultima lettura conservata per riga, non cronologia completa e non prova di ricezione in cantiere.', ['Marca', 'Data e ora', 'Stato'], shipping.scan.map(r => [r.marca, date(r.data), readable(r.stato)]));
      section('Cantiere', 'Stati registrati nella lista corrente: non certificano la ricezione in cantiere. Scan di arrivo e spedizioni con destinazione cantiere non sono distinguibili nei dati attuali.', ['Stato registrato', 'Righe lista'], counts(data.cantiere));
      result.querySelectorAll('details').forEach(panel => {
        const name = panel.querySelector('summary').textContent;
        if (openSections.has(name)) panel.open = openSections.get(name);
      });
      result.querySelectorAll('.phase-table').forEach((table, index) => { table.scrollLeft = horizontal[index] || 0; });
      if (groupedFocused) toggle.focus({preventScroll: true});
      window.scrollTo(scrollX, scrollY);
      previousData = serialized;
    } catch (error) {
      if (stopped) return;
      liveStatus.textContent = `${error.message} Connessione interrotta: nuovo tentativo automatico tra 3 secondi.`;
      liveStatus.dataset.state = 'error';
      if (previousData === null) result.textContent = 'In attesa dei dati della commessa…';
    } finally {
      busy = false;
      clearTimeout(timer);
      if (!stopped && !document.hidden) timer = setTimeout(refreshDetail, 3000);
    }
    }
    document.addEventListener('visibilitychange', () => {
      clearTimeout(timer);
      if (!document.hidden) refreshDetail();
    });
    window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); controller.abort(); }, {once: true});
    window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
    refreshDetail();
  }
})();
