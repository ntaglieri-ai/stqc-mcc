/* Polling leggero condiviso.
   Interroga a intervalli brevi un endpoint "pulse" che restituisce solo una
   firma compatta (conteggi / ultimo id). Il refresh pesante parte solo quando
   la firma cambia davvero: a riposo l'interfaccia resta ferma. */
(function (global) {
  'use strict';

  function createPulsePoller(config) {
    const intervalMs = config.intervalMs || 500;
    const sign = config.signature || (data => JSON.stringify(data));
    const onStatus = config.onStatus || function () {};
    let timer = null;
    let inFlight = false;
    let baseline = null;
    let failures = 0;
    let degraded = false;

    async function tick() {
      if (inFlight || document.hidden) return;        // niente chiamate sovrapposte
      inFlight = true;
      try {
        const url = typeof config.url === 'function' ? config.url() : config.url;
        const headers = typeof config.headers === 'function' ? config.headers() : (config.headers || {});
        const res = await fetch(url, { headers });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        const current = sign(data);
        failures = 0;
        if (degraded) { degraded = false; onStatus(true); }
        if (baseline === null) { baseline = current; return; }  // primo giro: solo baseline
        if (current !== baseline) {
          baseline = current;                          // aggiornata PRIMA del refresh:
          await config.onChange(data);                 // se arriva altro nel frattempo
        }                                              // il tick dopo lo vede ancora diverso
      } catch (err) {
        failures += 1;                                 // errori silenziosi, nessun toast
        if (!degraded && failures >= 5) { degraded = true; onStatus(false); }
      } finally {
        inFlight = false;
      }
    }

    function start() {
      if (timer) return;
      timer = setInterval(tick, intervalMs);
      tick();
    }

    function stop() {
      clearInterval(timer);
      timer = null;
    }

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) stop(); else start();
    });

    return { start, stop, tick };
  }

  global.createPulsePoller = createPulsePoller;
})(window);
