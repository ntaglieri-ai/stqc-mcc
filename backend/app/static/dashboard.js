(() => {
  const token = sessionStorage.getItem('stqc_token');
  const profile = sessionStorage.getItem('stqc_profilo');
  if (!token) { location.replace('/login'); return; }
  if (!['Direttore','Capo Officina','Progettazione','Admin'].includes(profile)) { location.replace('/'); return; }
  const sections = {
    '/dashboard/monitoring': ['Monitoring Produzione&Commesse', 'Registro giornaliero di scansioni, ingressi e uscite', 'Le stesse registrazioni sono organizzate per commessa, magazzino o sequenza giornaliera.'],
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
  document.body.classList.add('monitor-fixed-layout');
  document.getElementById('page-intro').hidden = false;
  document.querySelector('.eyebrow').hidden = true;
  const workspace = document.querySelector('.workspace');
  workspace.classList.add('monitoring');
  {
    workspace.innerHTML = `<div class="monitor-commandbar"><div class="monitor-tabs" role="tablist" aria-label="Organizzazione registrazioni">
        <button type="button" class="monitor-tab active" data-view="commesse" role="tab" aria-selected="true"><span>01</span>Commesse</button>
        <button type="button" class="monitor-tab" data-view="magazzino" role="tab" aria-selected="false"><span>02</span>Magazzino</button>
        <button type="button" class="monitor-tab" data-view="giornaliera" role="tab" aria-selected="false"><span>03</span>Giornaliera</button>
      </div><button type="button" id="refresh" class="monitor-refresh" aria-label="Aggiorna dati" title="Aggiorna dati">↻ <span>Aggiorna</span></button></div>
      <div class="monitor-datebar">
        <button type="button" id="day-prev" aria-label="Giorno precedente" title="Giorno precedente">‹</button>
        <label for="monitor-day">Giorno</label><input id="monitor-day" type="date">
        <button type="button" id="day-next" aria-label="Giorno successivo" title="Giorno successivo">›</button>
        <button type="button" id="day-today">Oggi</button>
        <p id="monitor-status" role="status" aria-live="polite"></p>
      </div>
      <div class="monitor-cleanup-bar"><label class="monitor-visibility-switch"><input type="checkbox" role="switch" id="show-hidden-events"><span>Mostra eventi nascosti</span></label><button type="button" id="cleanup-open" class="monitor-cleanup-button"><svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="m15 3-6 9m-3-1 8 5-4 5-8-5 4-5Z M15 21h6"/></svg>Pulisci eventi</button></div>
      <dialog id="cleanup-dialog" class="monitor-cleanup-dialog">
        <form method="dialog"><h2>Pulisci il registro</h2><p>Nascondi gli eventi del giorno selezionato. Storico, giacenze e movimenti restano invariati.</p>
        <label>Gruppo<select id="cleanup-scope"><option value="all">Tutti gli eventi</option><option value="magazzino">Magazzino</option><option value="commessa">Commesse</option></select></label>
        <p id="cleanup-preview" role="status"></p><p class="cleanup-note">La visibilità è condivisa con gli altri utenti. Le nuove registrazioni resteranno visibili.</p>
        <div class="cleanup-actions"><button value="cancel">Annulla</button><button type="button" id="cleanup-restore">Ripristina</button><button type="button" id="cleanup-hide">Nascondi eventi</button></div>
        <p id="cleanup-error" role="alert"></p></form>
      </dialog>
      <section id="event-register" aria-live="polite" aria-label="Registro eventi" tabindex="0"></section>`;

    const register = document.getElementById('event-register');
    const status = document.getElementById('monitor-status');
    const dayInput = document.getElementById('monitor-day');
    const refresh = document.getElementById('refresh');
    let currentView = 'commesse';
    let events = [];
    let allEvents = [];
    let activeCommesse = [];
    let selectedCommessa = null;
    const showHidden = document.getElementById('show-hidden-events');
    const cleanupDialog = document.getElementById('cleanup-dialog');
    const cleanupScope = document.getElementById('cleanup-scope');
    const cleanupPreview = () => {
      const rows = allEvents.filter(row => cleanupScope.value === 'all' || row.vista === cleanupScope.value);
      const hidden = rows.filter(row => row.hidden).length;
      document.getElementById('cleanup-preview').textContent = `${dayInput.value}: ${rows.length-hidden} eventi da nascondere · ${hidden} ripristinabili`;
      document.getElementById('cleanup-hide').disabled = rows.length === hidden;
      document.getElementById('cleanup-restore').disabled = hidden === 0;
    };
    const localIsoDay = date => {
      const copy = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
      return copy.toISOString().slice(0, 10);
    };
    dayInput.value = localIsoDay(new Date());

    const eventTime = value => value ? new Date(`${value}${/[zZ]|[+-]\d\d:\d\d$/.test(value) ? '' : 'Z'}`).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—';
    const createTable = rows => {
      const wrapper = document.createElement('div');
      wrapper.className = 'monitor-table-wrap';
      const table = document.createElement('table');
      table.innerHTML = '<thead><tr><th>Ora</th><th>Tipo registrazione</th><th>Commessa</th><th>Postazione / materiale</th><th>Dettaglio</th></tr></thead>';
      const body = document.createElement('tbody');
      rows.forEach(event => {
        const row = document.createElement('tr');
        if (event.errore) row.className = 'monitor-error-row';
        if (event.hidden) row.classList.add('monitor-hidden-event');
        [eventTime(event.data), event.origine === 'Scan inventario' ? 'Scansione inventario' : event.origine, event.commessa || '—', event.dettaglio || '—', event.esito || '—'].forEach(value => {
          const cell = document.createElement('td');
          cell.textContent = value;
          row.append(cell);
        });
        body.append(row);
      });
      table.append(body);
      wrapper.append(table);
      return wrapper;
    };
    const emptyState = message => {
      const box = document.createElement('div');
      box.className = 'monitor-empty';
      box.textContent = message;
      return box;
    };
    const section = (title, subtitle, rows) => {
      const block = document.createElement('section');
      block.className = 'event-group';
      const heading = document.createElement('div');
      heading.className = 'event-group-head';
      const h2 = document.createElement('h2');
      h2.textContent = title;
      const p = document.createElement('p');
      p.textContent = subtitle;
      heading.append(h2, p);
      block.append(heading, rows.length ? createTable(rows) : emptyState('Nessuna registrazione per questo gruppo.'));
      return block;
    };
    const renderEvents = () => {
      events = allEvents.filter(event => showHidden.checked || !event.hidden);
      register.replaceChildren();
      if (!events.length && (currentView !== 'commesse' || !activeCommesse.length)) {
        register.append(emptyState('Nessuna scansione, entrata o uscita registrata per il giorno selezionato.'));
        return;
      }
      if (currentView === 'giornaliera') {
        register.append(section('Sequenza giornaliera', 'Tutte le registrazioni in ordine cronologico.', events));
        return;
      }
      if (currentView === 'magazzino') {
        const incoming = events.filter(event => event.origine === 'Ingresso magazzino');
        const outgoing = events.filter(event => event.origine === 'Uscita magazzino');
        const scans = events.filter(event => event.vista === 'magazzino' && (event.origine.startsWith('Scan ') || event.origine === 'Scansione inventario'));
        const decisions = events.filter(event => event.origine === 'Esito notifica inventario');
        register.append(
          section('Ingressi', 'Materiale registrato in entrata.', incoming),
          section('Uscite', 'Materiale registrato in uscita o a sfrido.', outgoing),
          section('Scansioni magazzino', 'Letture effettuate dalle postazioni di magazzino.', scans),
          section('Esiti notifiche inventario', 'Operazioni confermate o rifiutate dopo la scansione.', decisions),
        );
        return;
      }
      const production = events.filter(event => event.vista === 'commessa');
      const groups = new Map(activeCommesse.map(c => [c.codice, []]));
      production.forEach(event => {
        const keys = event.commesse?.length ? event.commesse : [event.commessa || 'Commessa non indicata'];
        keys.forEach(key => {
          if (!groups.has(key)) groups.set(key, []);
          groups.get(key).push(event);
        });
      });
      if (!groups.size) {
        register.append(emptyState('Nessuna scansione di produzione collegata a commesse per il giorno selezionato.'));
        return;
      }
      const grid = document.createElement('div');
      grid.className = 'monitor-job-grid';
      grid.setAttribute('aria-label', 'Commesse e registrazioni del giorno');
      const jobStates = {APERTA:'Aperta', IN_PRODUZIONE:'In produzione', SOSPESA:'Sospesa', CHIUSA:'Chiusa'};
      if (!groups.has(selectedCommessa)) selectedCommessa = null;
      groups.forEach((rows, name) => {
        const job = activeCommesse.find(item => item.codice === name);
        const errors = rows.filter(item => item.errore).length;
        const card = document.createElement('button');
        card.type = 'button'; card.className = 'monitor-job-card';
        if (errors) card.classList.add('has-errors');
        card.setAttribute('aria-pressed', String(selectedCommessa === name));
        card.setAttribute('aria-controls', 'selected-job-events');
        const top = document.createElement('span'); top.className = 'job-card-top';
        const state = document.createElement('span'); state.className = 'job-state';
        state.textContent = jobStates[job?.status] || (job ? 'In corso' : 'Registrazioni');
        const arrow = document.createElement('span'); arrow.className = 'job-arrow'; arrow.textContent = '↗'; arrow.setAttribute('aria-hidden','true');
        top.append(state, arrow);
        const title = document.createElement('strong'); title.className = 'job-card-title'; title.textContent = name;
        const description = document.createElement('span'); description.className = 'job-description';
        description.textContent = job?.descrizione || (name === 'Commessa non indicata' ? 'Eventi non associati a una commessa' : 'Registro delle attività');
        const footer = document.createElement('span'); footer.className = 'job-card-footer';
        const count = document.createElement('span'); count.textContent = `${rows.length} ${rows.length===1?'evento':'eventi'} nel giorno`;
        const badge = document.createElement('span'); badge.className = errors ? 'job-error-count' : 'job-view-label';
        badge.textContent = errors ? `${errors} ${errors===1?'errore':'errori'}` : 'Apri registro';
        footer.append(count, badge); card.append(top, title, description, footer);
        card.addEventListener('click', () => {
          selectedCommessa = selectedCommessa === name ? null : name;
          renderEvents();
          const cards = [...register.querySelectorAll('.monitor-job-card')];
          cards.find(item => item.querySelector('.job-card-title').textContent === name)?.focus({preventScroll:true});
          if (selectedCommessa) document.getElementById('selected-job-events').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
        });
        grid.append(card);
      });
      register.append(grid);
      const detail = document.createElement('div'); detail.id = 'selected-job-events';
      if (selectedCommessa) {
        const rows = groups.get(selectedCommessa);
        const block = section(selectedCommessa, 'Registrazioni del giorno selezionato', rows);
        const close = document.createElement('button'); close.type = 'button'; close.className = 'job-detail-close';
        close.textContent = 'Chiudi registro';
        close.addEventListener('click', () => {
          const name = selectedCommessa; selectedCommessa = null; renderEvents();
          [...register.querySelectorAll('.monitor-job-card')].find(item => item.querySelector('.job-card-title').textContent === name)?.focus();
        });
        block.querySelector('.event-group-head').append(close); detail.append(block);
      } else {
        const hint = document.createElement('p'); hint.className = 'job-selection-hint';
        hint.textContent = 'Seleziona una commessa per consultare le registrazioni.'; detail.append(hint);
      }
      register.append(detail);
    };
    const loadEvents = async () => {
      refresh.disabled = true;
      status.textContent = 'Caricamento registrazioni...';
      try {
        const response = await fetch(`/api/v1/commesse/dashboard/monitoring?day=${encodeURIComponent(dayInput.value)}`, { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' });
        if (response.status === 401) { location.replace('/login'); return; }
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        allEvents = data.giornaliera?.timeline || [];
        activeCommesse = data.commesse_in_corso || [];
        renderEvents();
        const errors = Number(data.giornaliera?.errori_assemblaggio || 0);
        status.textContent = `${events.length} registrazioni mostrate · ${allEvents.filter(event=>event.hidden).length} nascoste · aggiornato alle ${new Date().toLocaleTimeString('it-IT')}`;
      } catch (error) {
        register.replaceChildren(emptyState('Impossibile caricare le registrazioni. Premi Aggiorna per riprovare.'));
        status.textContent = 'Caricamento non riuscito.';
      } finally {
        refresh.disabled = false;
      }
    };
    const moveDay = offset => {
      const date = new Date(`${dayInput.value}T12:00:00`);
      date.setDate(date.getDate() + offset);
      dayInput.value = localIsoDay(date);
      loadEvents();
    };
    document.querySelectorAll('.monitor-tab').forEach(button => button.addEventListener('click', () => {
      currentView = button.dataset.view;
      document.querySelectorAll('.monitor-tab').forEach(tab => {
        const active = tab === button;
        tab.classList.toggle('active', active);
        tab.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      renderEvents();
    }));
    document.getElementById('day-prev').addEventListener('click', () => moveDay(-1));
    document.getElementById('day-next').addEventListener('click', () => moveDay(1));
    document.getElementById('day-today').addEventListener('click', () => { dayInput.value = localIsoDay(new Date()); loadEvents(); });
    dayInput.addEventListener('change', loadEvents);
    refresh.addEventListener('click', loadEvents);
    showHidden.addEventListener('change', renderEvents);
    document.getElementById('cleanup-open').addEventListener('click', () => {
      cleanupScope.value = currentView === 'magazzino' ? 'magazzino' : currentView === 'commesse' ? 'commessa' : 'all';
      document.getElementById('cleanup-error').textContent = '';
      cleanupPreview(); cleanupDialog.showModal();
    });
    cleanupScope.addEventListener('change', cleanupPreview);
    const cleanup = async operation => {
      document.getElementById('cleanup-hide').disabled = true;
      document.getElementById('cleanup-restore').disabled = true;
      try {
        const response = await fetch('/api/v1/commesse/dashboard/monitoring/cleanup', {
          method:'POST', headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},
          body:JSON.stringify({day:dayInput.value, scope:cleanupScope.value, operation})
        });
        if (!response.ok) throw new Error('Pulizia non riuscita. Riprova.');
        cleanupDialog.close(); await loadEvents();
      } catch(error) { document.getElementById('cleanup-error').textContent=error.message; }
      finally { cleanupPreview(); }
    };
    document.getElementById('cleanup-hide').addEventListener('click',()=>cleanup('hide'));
    document.getElementById('cleanup-restore').addEventListener('click',()=>cleanup('restore'));
    loadEvents();
    return;
  }
  const selected = new URLSearchParams(location.search).get('commessa');
  if (selected) {
    showCommessa(selected);
    return;
  }
  workspace.innerHTML = `<div class="monitor-commandbar"><div class="monitor-tabs" role="tablist" aria-label="Viste monitoring">
      <button type="button" class="monitor-tab active" data-tab="commesse" role="tab" aria-selected="true"><span>01</span>Commesse</button>
      <button type="button" class="monitor-tab" data-tab="magazzino" role="tab" aria-selected="false"><span>02</span>Magazzino</button>
      <button type="button" class="monitor-tab" data-tab="giornaliera" role="tab" aria-selected="false"><span>03</span>Giornaliera</button>
    </div><button type="button" id="refresh" class="monitor-refresh" aria-label="Aggiorna dati" title="Aggiorna dati">↻ <span>Aggiorna</span></button></div>
    <div id="monitor-summary" aria-live="polite"></div>
    <section class="monitor-panel active" id="panel-commesse" role="tabpanel"><div class="monitor-section-head"><div><p class="monitor-kicker">Portafoglio lavori</p><h2>Commesse</h2></div><div class="monitor-toolbar"><label class="sr-only" for="commessa-search">Cerca commessa</label><input id="commessa-search" type="search" placeholder="Cerca codice, cliente o descrizione"></div></div>
    <p id="monitor-status" role="status" aria-live="polite"></p><div id="monitor-list"></div></section>
    <section class="monitor-panel" id="panel-magazzino" role="tabpanel" hidden><p class="monitor-status" id="warehouse-status" role="status">Caricamento magazzino...</p><div id="warehouse-overview"></div></section>
    <section class="monitor-panel" id="panel-giornaliera" role="tabpanel" hidden><p class="monitor-status" id="daily-status" role="status">Caricamento vista giornaliera...</p><div id="daily-overview"></div></section>`;
  const status = document.getElementById('monitor-status');
  const list = document.getElementById('monitor-list');
  const search = document.getElementById('commessa-search');
  const refresh = document.getElementById('refresh');
  const warehouseStatus = document.getElementById('warehouse-status');
  const warehouseOverview = document.getElementById('warehouse-overview');
  const dailyStatus = document.getElementById('daily-status');
  const dailyOverview = document.getElementById('daily-overview');
  const summaryOverview = document.getElementById('monitor-summary');
  let commesse = [];
  let overview = null;
  const labels = { APERTA: 'Aperta', IN_PRODUZIONE: 'In produzione', SOSPESA: 'Sospesa', CHIUSA: 'Chiusa' };
  const number = value => Number(value || 0).toLocaleString('it-IT');
  const dateTime = value => value ? new Date(String(value).endsWith('Z') || /[+-]\d\d:\d\d$/.test(String(value)) ? value : `${value}Z`).toLocaleString('it-IT') : '—';
  function addCells(row, values) {
    values.forEach(value => {
      const cell = document.createElement('td');
      cell.textContent = value ?? '—';
      row.append(cell);
    });
  }
  function table(headers, rows) {
    const wrapper = document.createElement('div');
    wrapper.className = 'phase-table monitor-table-wrap';
    const el = document.createElement('table');
    const head = document.createElement('thead');
    const tr = document.createElement('tr');
    headers.forEach(label => { const th = document.createElement('th'); th.scope = 'col'; th.textContent = label; tr.append(th); });
    head.append(tr); el.append(head);
    const body = document.createElement('tbody');
    rows.forEach(values => { const row = document.createElement('tr'); addCells(row, values); body.append(row); });
    el.append(body); wrapper.append(el);
    return wrapper;
  }
  function metricGrid(items) {
    const grid = document.createElement('div');
    grid.className = 'monitor-metrics';
    items.forEach(([label, value, detail]) => {
      const box = document.createElement('div');
      box.className = 'monitor-metric';
      const small = document.createElement('span');
      small.textContent = label;
      const strong = document.createElement('strong');
      strong.textContent = value;
      box.append(small, strong);
      if (detail) { const p = document.createElement('p'); p.textContent = detail; box.append(p); }
      grid.append(box);
    });
    return grid;
  }
  function renderOverview() {
    if (!overview) return;
    const summary = overview.summary || {};
    const magazzino = overview.magazzino || {};
    const giornaliera = overview.giornaliera || {};
    summaryOverview.replaceChildren(metricGrid([
      ['Commesse', number(summary.commesse_total), `${number(summary.commesse_aperte)} aperte`],
      ['Magazzino', number(summary.pezzi_magazzino), `${number(summary.pezzi_disponibili)} disponibili`],
      ['Attività oggi', number(summary.eventi_giornalieri), overview.date ? overview.date.split('-').reverse().join('/') : 'Oggi'],
    ]));
    warehouseOverview.replaceChildren();
    warehouseOverview.append(metricGrid([
      ['Materiali', number(summary.materiali_magazzino)],
      ['Pezzi fisici', number(summary.pezzi_magazzino)],
      ['Disponibili', number(summary.pezzi_disponibili)],
      ['Prenotati', number(summary.pezzi_prenotati)],
      ['Usciti', number(summary.pezzi_usciti)],
      ['Movimenti oggi', number(magazzino.movimenti_oggi), `${number(magazzino.ingressi_oggi)} ingressi · ${number(magazzino.uscite_oggi)} uscite`],
    ]));
    const reservations = magazzino.prenotazioni || [];
    const movements = magazzino.movimenti || [];
    const reservedTitle = document.createElement('h3');
    reservedTitle.textContent = 'Prenotazioni per commessa';
    warehouseOverview.append(reservedTitle, reservations.length
      ? table(['Commessa', 'Pezzi', 'Prima prenotazione'], reservations.map(r => [r.commessa, number(r.pezzi), dateTime(r.prima_prenotazione)]))
      : emptyBlock('Nessuna prenotazione di magazzino registrata.'));
    const movementTitle = document.createElement('h3');
    movementTitle.textContent = 'Movimenti di oggi';
    warehouseOverview.append(movementTitle, movements.length
      ? table(['Ora', 'Tipo', 'Materiale', 'Quantità', 'Commessa', 'Causale'], movements.map(r => [dateTime(r.data), r.tipo, r.materiale || r.descrizione, number(r.quantita), r.commessa, r.causale]))
      : emptyBlock('Nessun movimento di magazzino registrato oggi.'));
    warehouseStatus.textContent = `Vista magazzino aggiornata alle ${new Date().toLocaleTimeString('it-IT')}`;

    dailyOverview.replaceChildren();
    dailyOverview.append(metricGrid([
      ['Eventi', number(summary.eventi_giornalieri), overview.date ? `Data ${overview.date.split('-').reverse().join('/')}` : 'Oggi'],
      ['Scan pezzi', number(giornaliera.scan_pezzi)],
      ['Scan fasi', number(giornaliera.scan_fasi)],
      ['DDT', number(giornaliera.ddt)],
      ['Movimenti magazzino', number(giornaliera.movimenti_magazzino)],
      ['Scan magazzino', number(giornaliera.scan_magazzino)],
    ]));
    const dailyTitle = document.createElement('h3');
    dailyTitle.textContent = 'Timeline giornaliera';
    const timeline = giornaliera.timeline || [];
    dailyOverview.append(dailyTitle, timeline.length
      ? table(['Ora', 'Vista', 'Origine', 'Commessa', 'Dettaglio', 'Esito'], timeline.map(r => [dateTime(r.data), r.vista, r.origine, r.commessa, r.dettaglio, r.esito]))
      : emptyBlock('Nessun dato raccolto oggi.'));
    dailyStatus.textContent = `Vista giornaliera aggiornata alle ${new Date().toLocaleTimeString('it-IT')}`;
  }
  function emptyBlock(message) {
    const box = document.createElement('div');
    box.className = 'monitor-empty';
    box.textContent = message;
    return box;
  }
  document.querySelectorAll('.monitor-tab').forEach(button => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.monitor-tab').forEach(tab => {
        const active = tab === button;
        tab.classList.toggle('active', active);
        tab.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      document.querySelectorAll('.monitor-panel').forEach(panel => {
        const active = panel.id === `panel-${button.dataset.tab}`;
        panel.classList.toggle('active', active);
        panel.hidden = !active;
      });
    });
  });
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
    warehouseStatus.textContent = 'Caricamento magazzino...';
    dailyStatus.textContent = 'Caricamento vista giornaliera...';
    const loadOverview = async () => {
      try {
        const overviewResponse = await fetch('/api/v1/commesse/dashboard/monitoring', { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' });
        if (overviewResponse.status === 401) { location.replace('/login'); return; }
        if (!overviewResponse.ok) throw new Error(`HTTP ${overviewResponse.status}`);
        overview = await overviewResponse.json();
        renderOverview();
      } catch (error) {
        summaryOverview.replaceChildren(emptyBlock('Riepilogo momentaneamente non disponibile. L’elenco commesse resta consultabile.'));
        warehouseStatus.textContent = 'Dati magazzino momentaneamente non disponibili.';
        dailyStatus.textContent = 'Dati giornalieri momentaneamente non disponibili.';
      }
    };
    try {
      const overviewPromise = loadOverview();
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
      await overviewPromise;
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
    const readable = value => value === 'PHASE_READ' ? 'Scansione registrata' : value ? String(value).replaceAll('_', ' ') : 'Non registrato';
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
        rows.forEach(entry => {
          const values = Array.isArray(entry) ? entry : entry.values;
          const row = document.createElement('tr');
          if (!Array.isArray(entry) && entry.error) row.className = 'monitor-error-row';
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
      const progettazioneTempi = data.progettazione_tempi || {};
      section('Progettazione', `Inizio generale: ${date(progettazioneTempi.inizio_generale)} · Fine generale: ${date(progettazioneTempi.fine_generale)}. Primo inizio e ultima fine registrati per la commessa, anche con attività ancora aperte.`, ['Fase', 'Stato', 'Inizio', 'Fine'], data.progettazione.map(r => [r.label, r.fine ? 'Completata' : r.inizio ? 'On going' : 'Da fare', r.inizio ? date(r.iniziata_at) : '—', r.fine ? date(r.completata_at) : '—']));
      const numero = value => Number(value || 0).toLocaleString('it-IT');
      const raccolta = data.raccolta_dati || {};
      const rdCommessa = raccolta.commessa || {};
      const rdMagazzino = raccolta.magazzino || {};
      const rdGiornaliera = raccolta.giornaliera || {};
      section('Raccolta dati', 'Vista di controllo separata per commesse, magazzino e giornata corrente.', ['Vista', 'Dati raccolti', 'Dettaglio'], [
        ['Commesse', `${numero(rdCommessa.pezzi_correnti)} pezzi · ${numero(rdCommessa.scan_operativi)} scan`, `${numero(rdCommessa.letture_officina)} letture officina · ${numero(rdCommessa.scan_fasi)} scan fasi · ${numero(rdCommessa.ddt)} DDT`],
        ['Magazzino', `${numero(rdMagazzino.grezzi_collegati)} grezzi collegati · ${numero(rdMagazzino.grezzi_prenotati)} prenotati`, `${numero(rdMagazzino.movimenti)} movimenti · ${numero(rdMagazzino.usciti)} usciti`],
        ['Giornaliera', `${numero(rdGiornaliera.totale)} eventi oggi`, `${numero(rdGiornaliera.scan_operativi)} scan pezzi · ${numero(rdGiornaliera.movimenti_magazzino)} movimenti magazzino · ${numero(rdGiornaliera.ddt)} DDT`],
      ]);
      if ((rdMagazzino.righe || []).length) {
        section('Magazzino collegato', 'Grezzi collegati o prenotati per questa commessa.', ['Materiale', 'Profilo', 'Stato', 'Prenotato per', 'Prenotato il', 'Uscito il'], rdMagazzino.righe.map(r => [r.materiale, r.profilo, r.stato, r.prenotato_per, date(r.prenotato_il), date(r.uscito_il)]));
      }
      const workshopPhase = section('Lavorazioni officina', 'Registro operativo della commessa alimentato dalle scansioni in officina.', [], []);
      const readings = data.officina_letture || [];
      const workshop = section('Letture fisiche', 'Ogni scansione resta registrata con pezzo, postazione ed esito.', [], []);
      workshopPhase.append(workshop);
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
      section('Blocchi officina', (data.officina || []).length ? 'Un rilevamento per ogni ciclo INIZIO-FINE, con il numero di pezzi scannerizzati nel mezzo.' : 'Nessun ciclo officina registrato.', ['Postazione', 'Inizio', 'Fine', 'Numero scan', 'Stato'], (data.officina || []).map(r => [r.postazione, date(r.inizio), date(r.fine), r.numero_scan, readable(r.stato)]));
      section('Progress assemblaggi', (data.assemblaggi_progress || []).length ? 'Avanzamento calcolato nel monitoring aggregando tutte le sessioni, anche su giorni diversi.' : 'Nessun avanzamento assemblaggio disponibile.', ['Assemblato', 'Pezzi scansionati', 'Pezzi previsti', 'Progress', 'Sessioni', 'Primo inizio', 'Ultima fine', 'Errori'], (data.assemblaggi_progress || []).map(r => [`${r.assemblato} / ${r.progressivo}`, r.pezzi_scansionati, r.pezzi_previsti, r.percentuale == null ? 'Non calcolabile' : `${r.percentuale}%`, r.sessioni, date(r.primo_inizio), date(r.ultima_fine), r.errori]));
      section(`Eventi assemblaggi · ${numero(data.errori_assemblaggio)} errori`, (data.assemblaggi || []).length ? 'Ogni scansione è registrata. I pezzi mantengono il collegamento al padre; gli errori sono evidenziati.' : 'Nessuna scansione assemblaggio registrata.', ['Codice letto', 'Assemblato padre', 'Postazione', 'Evento', 'Data e ora', 'Esito', 'Messaggio'], (data.assemblaggi || []).map(r => ({values: [r.marca, r.assemblato, r.postazione, readable(r.evento), date(r.data), r.esito, r.messaggio], error: r.errore})));
      section('Sessioni saldatura', (data.saldature_sessioni || []).length ? 'Ogni sessione comprende tutti gli assemblati padre letti tra INIZIO e FINE.' : 'Nessuna sessione saldatura registrata.', ['Postazione', 'Inizio', 'Fine', 'Assemblati scansionati', 'Stato'], (data.saldature_sessioni || []).map(r => [r.postazione, date(r.inizio), date(r.fine), r.assemblati_scansionati, readable(r.stato)]));
      section('Scansioni saldatura', (data.saldature || []).length ? 'Registro dei codici assemblato padre passati dal file Assemblaggi.' : 'Nessuna scansione saldatura registrata.', ['Assemblato', 'Postazione', 'Data e ora', 'Esito', 'Messaggio'], (data.saldature || []).map(r => ({values: [r.marca, r.postazione, date(r.data), r.esito, r.messaggio], error: r.errore})));
      for (const [key, title] of [['lavorazioni', 'Scansioni lavorazioni'], ['in-cantiere', 'Scansioni spedizione']]) {
        section(title, (data[key] || []).length ? 'Sequenza cronologica, tutte le revisioni. Durata solo per sessioni chiuse e collegate; non è il tempo tra due scansioni.' : 'Nessuna scansione operativa registrata.', ['Marca', 'Postazione', 'Evento', 'Data e ora', 'Durata sessione'], (data[key] || []).map(r => [r.marca, r.postazione, readable(r.evento), date(r.data), r.durata_secondi == null ? 'Non registrata' : `${Math.floor(r.durata_secondi / 60)} min ${r.durata_secondi % 60} s`]));
      }
      const counts = rows => Object.entries(rows.reduce((acc, r) => {acc[r.stato] = (acc[r.stato] || 0) + 1; return acc;}, {})).map(([state, n]) => [readable(state), n]);
      section('Lavorazioni esterne', 'Stati della lista corrente. Cronologia scan e destinazione delle spedizioni esterne non disponibili nei dati collegati.', ['Stato registrato', 'Righe lista'], counts(data.lavorazioni_esterne));
      const shipping = data.spedizione;
      section('Spedizione', `${shipping.spediti ?? 'Non disponibile'} pezzi spediti / ${shipping.previsti ?? 'Non disponibile'} previsti nella lista spedizione della revisione corrente. Storico DDT di tutte le revisioni; DDT generato non equivale a consegna confermata.`, ['DDT', 'Titolo', 'Data', 'Quantità nel DDT'], shipping.ddt.map(d => [d.numero, d.titolo, date(d.created_at), d.materiali.reduce((n, r) => n + Number(r.quantita || 0), 0)]));
      if (shipping.scan.length) section('Letture spedizione', 'Ultima lettura conservata per riga, non cronologia completa e non prova di ricezione in cantiere.', ['Marca', 'Data e ora', 'Stato'], shipping.scan.map(r => [r.marca, date(r.data), readable(r.stato)]));
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
