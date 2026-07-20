(() => {
  const embedded = new URLSearchParams(location.search).get("embed") === "1";
  if (!embedded) return;

  const parts = location.pathname.split("/").filter(Boolean);
  const ref = parts[1] || "";
  const view = parts[2] || "analisi";
  document.documentElement.classList.add("stqc-embedded");
  document.documentElement.dataset.embeddedView = view;

  const style = document.createElement("style");
  style.textContent = `
    html.stqc-embedded .top, html.stqc-embedded .nav, html.stqc-embedded .macro-flow { display:none !important; }
    html.stqc-embedded body { min-height:100vh; }
    html.stqc-embedded[data-embedded-view="officina"] body,
    html.stqc-embedded[data-embedded-view="assemblaggi"] body,
    html.stqc-embedded[data-embedded-view="lavorazioni"] body,
    html.stqc-embedded[data-embedded-view="in-cantiere"] body { height:100vh; overflow:hidden; }
    html.stqc-embedded .layout { height:100vh !important; min-height:100vh !important; }
    html.stqc-embedded .filter-side { height:100vh !important; }
    html.stqc-embedded .layout .wrap { height:100vh !important; }
    html.stqc-embedded[data-embedded-view="analisi"] .page { padding-top:22px; }
  `;
  document.head.appendChild(style);

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
    if (url.origin !== location.origin || !/^\/commesse\/[^/]+\/(analisi|officina|assemblaggi|lavorazioni|in-cantiere)$/.test(url.pathname)) return;
    event.preventDefault();
    window.stqcNavigate(url.pathname);
  });

  window.stqcCommessaRef = ref;
})();
