window.openQrPrint = function(items) {
  if (!items.length) return alert('Nessun QR selezionato.');
  if (items.length > 2000) return alert('Seleziona al massimo 2000 QR.');
  const key = 'qr-print-' + crypto.randomUUID();
  try { sessionStorage.setItem(key, JSON.stringify(items)); }
  catch (_) { return alert('Troppi dati per la stampa: seleziona meno QR.'); }
  const popup = window.open('/static/qr-print.html#' + key, '_blank');
  if (!popup) alert('Abilita le finestre popup per aprire la stampa.');
  sessionStorage.removeItem(key);
};
