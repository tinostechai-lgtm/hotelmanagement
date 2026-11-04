/* Servora motion: ripples, count-ups, reveals, tilt, spotlight, rotating words, scroll effects. */
(function () {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  /* Button ripple */
  document.addEventListener("pointerdown", (e) => {
    const b = e.target.closest(".btn, .chip");
    if (!b || reduce) return;
    const r = b.getBoundingClientRect(), d = Math.max(r.width, r.height);
    const s = document.createElement("span");
    s.className = "ripple";
    s.style.cssText = `width:${d}px;height:${d}px;left:${e.clientX - r.left - d / 2}px;top:${e.clientY - r.top - d / 2}px`;
    if (getComputedStyle(b).position === "static") b.style.position = "relative";
    b.appendChild(s);
    setTimeout(() => s.remove(), 650);
  });

  /* Count-up: animates any number that appears in .kpi .v or [data-count] */
  const fmt = (n, tpl) => tpl.replace(/[\d,]+(\.\d+)?/, Math.round(n).toLocaleString("en-IN"));
  function countUp(el) {
    if (el._counting) return;
    const txt = el.textContent.trim(), m = txt.match(/[\d,]+(\.\d+)?/);
    if (!m || reduce) return;
    const target = parseFloat(m[0].replace(/,/g, ""));
    if (!isFinite(target) || target === 0 || el._last === txt) return;
    el._counting = true;
    const start = performance.now(), dur = 900 + Math.min(700, Math.log10(target + 1) * 200);
    const step = (t) => {
      const k = Math.min(1, (t - start) / dur), e = 1 - Math.pow(1 - k, 4);
      el.textContent = fmt(target * e, txt);
      if (k < 1) requestAnimationFrame(step); else { el.textContent = txt; el._last = txt; el._counting = false; }
    };
    requestAnimationFrame(step);
  }
  const watchCount = (el) => {
    countUp(el);
    new MutationObserver(() => { if (!el._counting) countUp(el); }).observe(el, { childList: true, characterData: true, subtree: true });
  };
  const countIO = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { watchCount(e.target); countIO.unobserve(e.target); } }), { threshold: .4 });
  const initCounts = () => $$(".kpi .v, [data-count]").forEach((el) => countIO.observe(el));

  /* Scroll reveals */
  const revealIO = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); revealIO.unobserve(e.target); } }), { threshold: .12, rootMargin: "0px 0px -40px 0px" });
  const initReveal = () => $$(".reveal, .reveal-left, .reveal-right").forEach((el, i) => { el.style.transitionDelay = el.dataset.delay || (i % 4) * 70 + "ms"; revealIO.observe(el); });

  /* Spotlight on feature cards */
  document.addEventListener("pointermove", (e) => {
    const c = e.target.closest && e.target.closest(".feat .card, [data-spotlight]");
    if (!c) return;
    const r = c.getBoundingClientRect();
    c.style.setProperty("--mx", e.clientX - r.left + "px");
    c.style.setProperty("--my", e.clientY - r.top + "px");
  });

  /* 3D tilt */
  function initTilt() {
    $$("[data-tilt]").forEach((el) => {
      if (reduce || matchMedia("(hover: none)").matches) return;
      const wrap = el.parentElement;
      wrap.addEventListener("pointermove", (e) => {
        const r = wrap.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
        el.style.transform = `rotateY(${x * 14}deg) rotateX(${-y * 10}deg) translateZ(0)`;
      });
      wrap.addEventListener("pointerleave", () => (el.style.transform = ""));
    });
  }

  /* Rotating words: <span class="rotator" data-words="faster,smarter"></span> */
  function initRotator() {
    $$(".rotator[data-words]").forEach((el) => {
      const words = el.dataset.words.split(",");
      el.innerHTML = words.map((w, i) => `<em class="${i === 0 ? "on" : ""}">${w}</em>`).join("");
      if (reduce) return;
      let i = 0;
      setInterval(() => {
        const items = el.children, prev = items[i];
        i = (i + 1) % items.length;
        prev.classList.remove("on"); prev.classList.add("off");
        items[i].classList.remove("off"); items[i].classList.add("on");
        setTimeout(() => prev.classList.remove("off"), 700);
      }, 2400);
    });
  }

  /* Split headline into words that rise in */
  function initSplit() {
    $$("[data-split]").forEach((el) => {
      let n = 0;
      const walk = (node) => [...node.childNodes].forEach((c) => {
        if (c.nodeType === 3) {
          const frag = document.createDocumentFragment();
          c.textContent.split(/(\s+)/).forEach((w) => {
            if (!w.trim()) return frag.appendChild(document.createTextNode(w));
            const s = document.createElement("span"); s.textContent = w; s.style.animationDelay = 0.25 + n++ * 0.07 + "s"; frag.appendChild(s);
          });
          c.replaceWith(frag);
        } else if (c.nodeType === 1 && !c.classList.contains("rotator")) { c.style.animationDelay = 0.25 + n++ * 0.07 + "s"; }
        else if (c.nodeType === 1) { c.style.animationDelay = 0.25 + n++ * 0.07 + "s"; }
      });
      walk(el);
      el.classList.add("split-in");
    });
  }

  /* Rising steam particles */
  function initSteam() {
    $$(".steam-particles").forEach((box) => {
      if (reduce) return;
      for (let i = 0; i < 26; i++) {
        const p = document.createElement("i");
        const size = 3 + Math.random() * 7;
        p.style.cssText = `left:${Math.random() * 100}%;width:${size}px;height:${size}px;animation-duration:${9 + Math.random() * 12}s;animation-delay:${-Math.random() * 20}s;opacity:${0.3 + Math.random() * 0.6}`;
        box.appendChild(p);
      }
    });
  }

  /* Scroll progress + shrinking nav */
  function initScroll() {
    const bar = document.querySelector(".scroll-progress"), nav = document.querySelector(".mk-nav");
    if (!bar && !nav) return;
    const on = () => {
      const h = document.documentElement, max = h.scrollHeight - h.clientHeight;
      if (bar) bar.style.transform = `scaleX(${max > 0 ? h.scrollTop / max : 0})`;
      if (nav) nav.classList.toggle("scrolled", h.scrollTop > 20);
    };
    addEventListener("scroll", on, { passive: true }); on();
  }

  /* Live demo pulses in the hero mock */
  function initMockPulse() {
    const tiles = $$(".mock .t");
    if (!tiles.length || reduce) return;
    setInterval(() => { const t = tiles[Math.floor(Math.random() * tiles.length)]; t.classList.remove("pulse"); void t.offsetWidth; t.classList.add("pulse"); }, 1800);
  }

  const init = () => { initSplit(); initRotator(); initReveal(); initCounts(); initTilt(); initSteam(); initScroll(); initMockPulse(); };
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", init) : init();
  window.SVMotion = { countUp, initReveal, initCounts };
})();
