(() => {
  const embedded = new URLSearchParams(location.search).get("embed") === "1";
  if (!embedded) return;

  const parts = location.pathname.split("/").filter(Boolean);
  const ref = parts[1] || "";
  const view = parts[2] || "analisi";
  document.documentElement.classList.add("stqc-embedded");
  document.documentElement.dataset.embeddedView = view === "spedizione-qr-registry" ? "in-cantiere" : view;

  const embeddedCss = `
    html.stqc-embedded .top,
    html.stqc-embedded .nav,
    html.stqc-embedded .macro-flow,
    html.stqc-embedded #macro,
    html.stqc-embedded #macro-flow-host {
      display:none !important;
    }

    html.stqc-embedded body {
      min-height:100vh !important;
      background:#07111f !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] body,
    html.stqc-embedded[data-embedded-view="assemblaggi"] body,
    html.stqc-embedded[data-embedded-view="lavorazioni"] body,
    html.stqc-embedded[data-embedded-view="in-cantiere"] body {
      height:100vh !important;
      overflow:hidden !important;
    }

    html.stqc-embedded .layout {
      height:100vh !important;
      min-height:0 !important;
      overflow:hidden !important;
    }

    html.stqc-embedded .filter-side {
      height:100vh !important;
      min-height:0 !important;
    }

    html.stqc-embedded .layout .wrap,
    html.stqc-embedded main.wrap {
      height:100vh !important;
      min-height:0 !important;
      overflow:auto !important;
      padding-top:22px !important;
    }

    html.stqc-embedded[data-embedded-view="analisi"] .page {
      padding-top:22px !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] main {
      height:100vh !important;
      min-height:0 !important;
      overflow:hidden !important;
      display:flex !important;
      flex-direction:column !important;
      gap:12px !important;
      padding:14px 18px 14px !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .map-callout {
      flex:0 0 auto !important;
      margin:0 !important;
      padding:14px 22px !important;
      border-radius:22px !important;
      background:
        radial-gradient(circle at 88% 10%, rgba(96,165,250,.18), transparent 30%),
        linear-gradient(110deg, rgba(18,44,80,.96), rgba(9,21,38,.90)) !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .qr-workbench {
      flex:1 1 auto !important;
      min-height:0 !important;
      display:flex !important;
      flex-direction:column !important;
      margin:0 !important;
      padding:18px 20px 0 !important;
      border-radius:26px !important;
      background:
        radial-gradient(circle at 5% 0%, rgba(59,130,246,.20), transparent 26%),
        radial-gradient(circle at 96% 2%, rgba(124,58,237,.13), transparent 28%),
        linear-gradient(145deg, #0f2747 0%, #071525 55%, #050d18 100%) !important;
      box-shadow:0 28px 74px rgba(0,0,0,.32), inset 0 1px 0 rgba(255,255,255,.045) !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .qr-workbench .section-head {
      margin:0 !important;
      padding:0 0 12px !important;
      border-bottom:1px solid rgba(147,197,253,.12) !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .qr-workbench .section-head h2 {
      font-size:30px !important;
      letter-spacing:-.045em !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .qr-workbench .section-head p {
      max-width:1160px !important;
      font-size:13px !important;
      line-height:1.4 !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .qr-action-bar,
    html.stqc-embedded[data-embedded-view="officina"] .show-all-row {
      flex:0 0 auto !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .qr-action-bar {
      padding:10px 0 !important;
      border-bottom:1px solid rgba(147,197,253,.10) !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .show-all-row {
      padding:10px 0 !important;
      border-bottom:1px solid rgba(147,197,253,.10) !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .qr-panel-frame {
      flex:1 1 auto !important;
      min-height:0 !important;
      display:flex !important;
      flex-direction:column !important;
      border-radius:0 !important;
      border:0 !important;
      overflow:hidden !important;
      background:rgba(4,10,18,.58) !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .qr-scroll-window {
      flex:1 1 auto !important;
      min-height:0 !important;
      max-height:none !important;
      overflow:auto !important;
      padding:0 !important;
      scrollbar-width:auto !important;
      scrollbar-color:#6fa0ff #07101c !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .qr-scroll-window::-webkit-scrollbar {
      width:18px !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .qr-scroll-window::-webkit-scrollbar-track {
      background:#07101c !important;
      border-left:1px solid rgba(96,165,250,.16) !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .qr-scroll-window::-webkit-scrollbar-thumb {
      background:linear-gradient(180deg,#7da9ff,#3f6ee8) !important;
      border:5px solid #07101c !important;
      border-radius:999px !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .group-head {
      min-height:56px !important;
      padding:9px 18px !important;
      border-radius:0 !important;
      background:linear-gradient(90deg, rgba(22,42,72,.86), rgba(8,17,30,.72)) !important;
      border-bottom:1px solid rgba(96,165,250,.15) !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .group-block:nth-child(even) .group-head {
      background:linear-gradient(90deg, rgba(18,35,60,.86), rgba(7,15,28,.72)) !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .group-block:hover .group-head {
      background:linear-gradient(90deg, rgba(34,63,101,.96), rgba(13,27,48,.86)) !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .group-title {
      font-size:19px !important;
      letter-spacing:-.035em !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .group-sub {
      font-size:11px !important;
      margin-top:2px !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .group-actions .btn {
      padding:8px 12px !important;
      font-size:12px !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .group-grid {
      padding:12px !important;
      background:rgba(5,12,22,.52) !important;
    }

    html.stqc-embedded[data-embedded-view="officina"] .qr-window-footer {
      flex:0 0 auto !important;
      min-height:56px !important;
      border-top:1px solid rgba(96,165,250,.20) !important;
      background:linear-gradient(180deg,rgba(10,21,38,.98),rgba(5,11,20,1)) !important;
    }

    html.stqc-embedded[data-embedded-view="assemblaggi"] .wrap {
      padding:14px 18px 14px !important;
      gap:12px !important;
    }

    html.stqc-embedded[data-embedded-view="assemblaggi"] .assembly-workbench {
      flex:1 1 auto !important;
      min-height:0 !important;
      border-radius:28px !important;
      background:
        radial-gradient(circle at 6% 0%, rgba(59,130,246,.22), transparent 28%),
        radial-gradient(circle at 96% 4%, rgba(124,58,237,.16), transparent 30%),
        linear-gradient(145deg, #10284a 0%, #081525 58%, #06101c 100%) !important;
    }

    html.stqc-embedded[data-embedded-view="assemblaggi"] .assembly-scroll-window {
      max-height:none !important;
      min-height:0 !important;
      overflow:auto !important;
      scrollbar-width:auto !important;
      scrollbar-color:#6fa0ff #07101c !important;
    }

    html.stqc-embedded[data-embedded-view="assemblaggi"] .assembly-scroll-window::-webkit-scrollbar {
      width:18px !important;
    }

    html.stqc-embedded[data-embedded-view="assemblaggi"] .assembly-scroll-window::-webkit-scrollbar-track {
      background:#07101c !important;
      border-left:1px solid rgba(96,165,250,.16) !important;
    }

    html.stqc-embedded[data-embedded-view="assemblaggi"] .assembly-scroll-window::-webkit-scrollbar-thumb {
      background:linear-gradient(180deg,#7da9ff,#3f6ee8) !important;
      border:5px solid #07101c !important;
      border-radius:999px !important;
    }
  `;

  const injectEmbeddedStyle = () => {
    const style = document.createElement("style");
    style.id = "stqc-embedded-overrides";
    style.textContent = embeddedCss;
    document.head.appendChild(style);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectEmbeddedStyle, { once: true });
  } else {
    injectEmbeddedStyle();
  }

  window.stqcNavigate = (target) => {
    const url = new URL(target, location.origin);
    if (window.parent !== window) {
      window.parent.postMessage({ type: "stqc:commessa-nav", url: url.pathname }, location.origin);
      return;
    }
    location.href = url.pathname;
  };

  document.addEventListener("click", (event) => {
    const anchor = event.target.closest("a[href]");
    if (!anchor || anchor.target || event.defaultPrevented) return;
    const url = new URL(anchor.href, location.origin);
    if (url.origin !== location.origin || !/^\/commesse\/[^/]+\/(analisi|officina|assemblaggi|lavorazioni|in-cantiere|spedizione-qr-registry)$/.test(url.pathname)) return;
    event.preventDefault();
    window.stqcNavigate(url.pathname);
  });

  window.stqcCommessaRef = ref;
})();
