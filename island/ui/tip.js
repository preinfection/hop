// Hop's own hover tips, in place of Windows' plain tooltip. Only for things
// that already have a title: the title moves into data-tip (so the native one
// never shows) and a small dark bubble appears above it after a short rest,
// kept inside the window.
(() => {
  const css = document.createElement("style");
  css.textContent = `
    .hop-tip { position: fixed; left: 0; top: 0; z-index: 2147483647; pointer-events: none;
      max-width: 240px; padding: 6px 10px; border-radius: 9px;
      background: var(--tip-bg, rgba(28, 28, 32, 0.96)); color: var(--tip-fg, #f2f2f5);
      border: 1px solid var(--tip-line, rgba(255,255,255,0.1));
      box-shadow: 0 8px 24px rgba(0,0,0,0.45); backdrop-filter: blur(12px);
      font: 500 12px/1.35 "Outfit", "Inter Island", "Segoe UI", system-ui, sans-serif; letter-spacing: 0.01em;
      opacity: 0; transform: translate(var(--x), calc(var(--y) + 4px)) scale(0.97);
      transition: opacity 140ms ease, transform 180ms cubic-bezier(.2,.9,.3,1.2); }
    .hop-tip.on { opacity: 1; transform: translate(var(--x), var(--y)) scale(1); }`;
  document.head.appendChild(css);
  const tip = document.createElement("div");
  tip.className = "hop-tip";
  tip.setAttribute("role", "tooltip");
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(tip));
  if (document.body) document.body.appendChild(tip);

  let cur = null, timer = 0;
  function place(el) {
    const r = el.getBoundingClientRect(), t = tip.getBoundingClientRect();
    const x = Math.max(4, Math.min(innerWidth - t.width - 4, r.left + r.width / 2 - t.width / 2));
    let y = r.top - t.height - 6;
    if (y < 4) y = r.bottom + 6;                       // no room above: below it
    tip.style.setProperty("--x", `${Math.round(x)}px`);
    tip.style.setProperty("--y", `${Math.round(y)}px`);
  }
  function hide() { clearTimeout(timer); cur = null; tip.classList.remove("on"); }

  document.addEventListener("mouseover", (e) => {
    const el = e.target.closest && e.target.closest("[title], [data-tip]");
    if (!el || el === cur) return;
    if (el.hasAttribute("title")) {
      if (el.getAttribute("title")) el.dataset.tip = el.getAttribute("title");
      el.removeAttribute("title");
    }
    if (!el.dataset.tip) return;
    hide();
    cur = el;
    timer = setTimeout(() => {
      if (cur !== el) return;
      tip.textContent = el.dataset.tip;
      place(el);
      tip.classList.add("on");
    }, 350);
  });
  // Hide only when the pointer has really left the element. Something sliding
  // in under a still pointer (the volume slider opening under the speaker)
  // also fires mouseout, and used to cancel the tip before it showed.
  document.addEventListener("mouseout", (e) => {
    if (!cur || cur.contains(e.relatedTarget)) return;
    const r = cur.getBoundingClientRect();
    if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) return;
    hide();
  });
  document.addEventListener("mousedown", hide, true);
  window.addEventListener("blur", hide);
})();
