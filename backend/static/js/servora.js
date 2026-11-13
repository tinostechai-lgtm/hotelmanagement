/* Servora front-end helpers (no build step). */
(function () {
  const S = (window.S = {});

  S.csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "";
  S.esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  S.money = (v) => "₹" + Number(v || 0).toLocaleString("en-IN", { minimumFractionDigits: Number(v) % 1 ? 2 : 0, maximumFractionDigits: 2 });
  S.qty = (v) => String(Number(v));
  S.ago = (d) => {
    const s = Math.max(0, (Date.now() - new Date(d).getTime()) / 1000);
    if (s < 60) return Math.floor(s) + "s";
    if (s < 3600) return Math.floor(s / 60) + "m";
    return Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m";
  };
  S.time = (d) => new Date(d).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
  S.date = (d) => new Date(d).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  S.$ = (sel, root = document) => root.querySelector(sel);
  S.$$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  S.icons = () => window.lucide && lucide.createIcons();

  S.api = async function (path, opts = {}) {
    const o = { method: opts.method || (opts.body ? "POST" : "GET"), headers: { Accept: "application/json" }, credentials: "same-origin" };
    if (opts.body !== undefined) {
      o.headers["Content-Type"] = "application/json";
      o.body = JSON.stringify(opts.body);
    }
    if (o.method !== "GET") o.headers["X-CSRFToken"] = S.csrf();
    const res = await fetch("/api/" + path.replace(/^\//, ""), o);
    let data = null;
    try { data = res.status === 204 ? null : await res.json(); } catch (e) { data = null; }
    if (!res.ok) {
      let msg = (data && (data.detail || Object.entries(data).map(([k, v]) => `${k}: ${[].concat(v).join(" ")}`).join(" · "))) || `Error ${res.status}`;
      if (!opts.quiet) S.toast(msg, "err");
      const err = new Error(msg); err.status = res.status; err.data = data; throw err;
    }
    return data;
  };
  S.list = async (path) => { const d = await S.api(path); return Array.isArray(d) ? d : d.results || []; };

  S.toast = function (msg, kind = "") {
    const t = document.createElement("div");
    t.className = "toast " + kind;
    t.textContent = msg;
    S.$("#toasts").appendChild(t);
    setTimeout(() => t.remove(), kind === "err" ? 5000 : 2800);
  };

  S.modal = function ({ title, body, footer, wide, onOpen }) {
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    bg.innerHTML = `<div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true">
      <div class="modal-h"><h3>${S.esc(title)}</h3><button class="btn btn-ghost icon-btn" data-close aria-label="Close"><i data-lucide="x"></i></button></div>
      <div class="modal-b">${body || ""}</div>${footer ? `<div class="modal-f">${footer}</div>` : ""}</div>`;
    const close = () => { bg.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => e.key === "Escape" && close();
    bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) close(); });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(bg);
    S.icons();
    const m = { el: bg, close, $: (s) => bg.querySelector(s), $$: (s) => [...bg.querySelectorAll(s)] };
    onOpen && onOpen(m);
    const first = bg.querySelector("input,select,textarea");
    first && setTimeout(() => first.focus(), 50);
    return m;
  };

  S.confirm = (text, okLabel = "Confirm", danger = false) => new Promise((resolve) => {
    const m = S.modal({ title: "Please confirm", body: `<p>${S.esc(text)}</p>`,
      footer: `<button class="btn" data-close>Cancel</button><button class="btn ${danger ? "btn-danger" : "btn-primary"}" data-ok>${S.esc(okLabel)}</button>` });
    m.$("[data-ok]").onclick = () => { m.close(); resolve(true); };
    m.el.addEventListener("click", (e) => { if (e.target.closest("[data-close]") || e.target === m.el) resolve(false); });
  });

  S.prompt = (title, fields, okLabel = "Save") => new Promise((resolve) => {
    const m = S.modal({ title, body: `<form>${S.formFields(fields, {})}</form>`,
      footer: `<button class="btn" data-close>Cancel</button><button class="btn btn-primary" data-ok>${S.esc(okLabel)}</button>` });
    const submit = (e) => { e && e.preventDefault(); const v = S.readForm(m.el, fields); m.close(); resolve(v); };
    m.$("[data-ok]").onclick = submit;
    m.$("form").onsubmit = submit;
  });

  S.beep = function () {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      [0, 0.18].forEach((t) => {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.frequency.value = 880; o.connect(g); g.connect(ctx.destination);
        g.gain.setValueAtTime(0.2, ctx.currentTime + t); g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + t + 0.15);
        o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.16);
      });
    } catch (e) { /* audio unavailable */ }
  };

  S.poll = function (fn, ms) {
    let stopped = false, timer;
    const run = async () => {
      if (stopped) return;
      if (!document.hidden) { try { await fn(); } catch (e) { /* keep polling */ } }
      timer = setTimeout(run, ms);
    };
    run();
    return () => { stopped = true; clearTimeout(timer); };
  };

  /* ---------- Generic forms ---------- */
  // field: {name, label, type: text|number|select|checkbox|textarea|multiselect|password|tel|email|date, options:[[v,l]], help, required, step}
  S.formFields = function (fields, values) {
    return fields.map((f) => {
      const v = values[f.name] ?? f.default ?? "";
      const req = f.required ? "required" : "";
      const help = f.help ? `<div class="help">${S.esc(f.help)}</div>` : "";
      if (f.type === "checkbox")
        return `<div class="field"><label class="check"><input type="checkbox" name="${f.name}" ${v ? "checked" : ""}> ${S.esc(f.label)}</label>${help}</div>`;
      if (f.type === "section") return `<h4 style="margin:18px 0 10px">${S.esc(f.label)}</h4>`;
      let input;
      if (f.type === "select" || f.type === "multiselect") {
        const vals = [].concat(v).map(String);
        input = `<select name="${f.name}" ${f.type === "multiselect" ? "multiple size=5" : ""} ${req}>${f.type === "select" && !f.required ? '<option value="">—</option>' : ""}${(f.options || [])
          .map(([ov, ol]) => `<option value="${S.esc(ov)}" ${vals.includes(String(ov)) ? "selected" : ""}>${S.esc(ol)}</option>`).join("")}</select>`;
      } else if (f.type === "textarea") input = `<textarea name="${f.name}" ${req}>${S.esc(v)}</textarea>`;
      else input = `<input type="${f.type || "text"}" name="${f.name}" value="${S.esc(v)}" ${f.step ? `step="${f.step}"` : f.type === "number" ? 'step="any"' : ""} ${req} ${f.placeholder ? `placeholder="${S.esc(f.placeholder)}"` : ""}>`;
      return `<div class="field ${f.half ? "half" : ""}"><label>${S.esc(f.label)}</label>${input}${help}</div>`;
    }).join("");
  };
  S.readForm = function (root, fields) {
    const out = {};
    fields.forEach((f) => {
      if (f.type === "section") return;
      const el = root.querySelector(`[name="${f.name}"]`);
      if (!el) return;
      if (f.type === "checkbox") out[f.name] = el.checked;
      else if (f.type === "multiselect") out[f.name] = [...el.selectedOptions].map((o) => (isNaN(o.value) ? o.value : Number(o.value)));
      else if (f.type === "number") out[f.name] = el.value === "" ? (f.nullable ? null : 0) : el.value;
      else if (f.type === "select") out[f.name] = el.value === "" ? null : el.value;
      else out[f.name] = el.value;
    });
    return out;
  };

  /* ---------- Generic CRUD table ---------- */
  S.crud = function (el, cfg) {
    // cfg: {endpoint, title, columns:[{key,label,render}], fields, defaults, actions:[{label, icon, run(row, reload)}], canCreate}
    // cfg.bulkDelete: endpoint for POST {ids:[...]} - adds row checkboxes + "Delete selected".
    let rows = [];
    const selected = new Set();
    let shown = [];
    const syncBulk = () => {
      const b = el.querySelector("[data-bulk-del]");
      if (!b) return;
      b.classList.toggle("hidden", !selected.size);
      b.querySelector("span").textContent = `Delete selected (${selected.size})`;
      const all = el.querySelector("[data-sel-all]");
      if (all) all.checked = shown.length > 0 && shown.every((r) => selected.has(r.id));
    };
    const render = () => {
      const q = (el.querySelector("[data-q]")?.value || "").toLowerCase();
      shown = rows.filter((r) => !q || JSON.stringify(r).toLowerCase().includes(q));
      const sel = (r) => cfg.bulkDelete ? `<td style="width:34px"><input type="checkbox" data-sel="${r.id}" ${selected.has(r.id) ? "checked" : ""} aria-label="Select"></td>` : "";
      el.querySelector("[data-body]").innerHTML = shown.length ? `<div class="table-wrap"><table class="data"><thead><tr>${cfg.bulkDelete ? `<th style="width:34px"><input type="checkbox" data-sel-all title="Select all shown" aria-label="Select all"></th>` : ""}${cfg.columns.map((c) => `<th class="${c.cls || ""}">${S.esc(c.label)}</th>`).join("")}<th></th></tr></thead><tbody>${shown
        .map((r) => `<tr data-id="${r.id}">${sel(r)}${cfg.columns.map((c) => `<td class="${c.cls || ""}">${c.render ? c.render(r) : S.esc(r[c.key])}</td>`).join("")}
          <td class="right nowrap">${(cfg.actions || []).map((a, i) => `<button class="btn btn-sm btn-ghost" data-act="${i}" title="${S.esc(a.label)}"><i data-lucide="${a.icon}"></i></button>`).join("")}
          ${cfg.fields ? `<button class="btn btn-sm btn-ghost" data-edit title="Edit"><i data-lucide="pencil"></i></button>` : ""}
          ${cfg.noDelete ? "" : `<button class="btn btn-sm btn-ghost" data-del title="Delete"><i data-lucide="trash-2"></i></button>`}</td></tr>`).join("")}</tbody></table></div>`
        : `<div class="card empty"><i data-lucide="${cfg.emptyIcon || "inbox"}"></i><div>${S.esc(cfg.empty || "Nothing here yet")}</div></div>`;
      S.icons();
      syncBulk();
    };
    const load = async () => {
      rows = await S.list(cfg.endpoint);
      const ids = new Set(rows.map((r) => r.id));
      [...selected].forEach((id) => ids.has(id) || selected.delete(id));
      render(); cfg.onLoad && cfg.onLoad(rows);
    };
    const fields = () => (typeof cfg.fields === "function" ? cfg.fields() : cfg.fields);
    const edit = (row) => {
      const f = fields();
      const m = S.modal({ title: (row ? "Edit " : "New ") + cfg.title, wide: f.length > 8, body: `<form class="grid g2" style="gap:0 16px">${S.formFields(f, row || cfg.defaults || {})}</form>`,
        footer: `<button class="btn" data-close>Cancel</button><button class="btn btn-primary" data-save>Save</button>` });
      m.$$(".field").forEach((x) => { if (!x.classList.contains("half")) x.style.gridColumn = "1 / -1"; });
      const save = async (e) => {
        e && e.preventDefault();
        let body = S.readForm(m.el, f);
        if (cfg.beforeSave) body = cfg.beforeSave(body, row);
        try {
          await S.api(cfg.endpoint.split("?")[0] + (row ? `/${row.id}` : ""), { method: row ? "PATCH" : "POST", body });
          m.close(); S.toast("Saved", "ok"); load();
        } catch (err) { /* toast shown */ }
      };
      m.$("[data-save]").onclick = save;
      m.$("form").onsubmit = save;
    };
    el.innerHTML = `<div class="row between wrap" style="margin-bottom:14px"><input type="search" data-q placeholder="Search ${S.esc(cfg.title.toLowerCase())}…" style="max-width:320px">
      <div class="row">${cfg.bulkDelete ? `<button class="btn btn-danger hidden" data-bulk-del><i data-lucide="trash-2"></i><span>Delete selected</span></button>` : ""}${cfg.toolbar || ""}${cfg.fields && cfg.canCreate !== false ? `<button class="btn btn-primary" data-new><i data-lucide="plus"></i> Add ${S.esc(cfg.title)}</button>` : ""}</div></div><div data-body><div class="skeleton" style="height:120px"></div></div>`;
    el.querySelector("[data-q]").oninput = render;
    if (cfg.bulkDelete) {
      el.addEventListener("change", (e) => {
        const one = e.target.closest("[data-sel]"), all = e.target.closest("[data-sel-all]");
        if (one) { const id = rows.find((r) => String(r.id) === one.dataset.sel)?.id; one.checked ? selected.add(id) : selected.delete(id); syncBulk(); }
        if (all) { shown.forEach((r) => (all.checked ? selected.add(r.id) : selected.delete(r.id))); render(); }
      });
      el.querySelector("[data-bulk-del]").onclick = async () => {
        const n = selected.size;
        if (!n) return;
        const warn = cfg.bulkWarning ? "\n\n" + cfg.bulkWarning : "";
        if (!(await S.confirm(`Delete ${n} ${cfg.title.toLowerCase()}${n > 1 ? "s" : ""}? This can't be undone.${warn}`, `Delete ${n}`, true))) return;
        const r = await S.api(cfg.bulkDelete, { body: { ids: [...selected] } });
        selected.clear();
        S.toast(`Deleted ${r.deleted}`, "ok");
        load();
      };
    }
    el.querySelector("[data-new]") && (el.querySelector("[data-new]").onclick = () => edit(null));
    el.addEventListener("click", async (e) => {
      const tr = e.target.closest("tr[data-id]");
      if (!tr) return;
      const row = rows.find((r) => String(r.id) === tr.dataset.id);
      if (e.target.closest("[data-edit]")) edit(row);
      else if (e.target.closest("[data-del]")) {
        if (await S.confirm(`Delete this ${cfg.title.toLowerCase()}?${cfg.bulkWarning ? "\n\n" + cfg.bulkWarning : ""}`, "Delete", true)) {
          await S.api(cfg.endpoint.split("?")[0] + "/" + row.id, { method: "DELETE" }); S.toast("Deleted"); load();
        }
      } else if (e.target.closest("[data-act]")) cfg.actions[e.target.closest("[data-act]").dataset.act].run(row, load);
    });
    S.icons();
    load();
    return { reload: load, edit };
  };

  /* ---------- Browser hardware (no agent needed) ---------- */
  S.hw = {
    // Print raw ESC/POS bytes (base64) via WebUSB, WebSerial or Web Bluetooth.
    async print(b64, kind = localStorage.getItem("sv_print_via") || "usb") {
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      if (kind === "usb") return S.hw.usb(bytes);
      if (kind === "serial") return S.hw.serial(bytes);
      if (kind === "bluetooth") return S.hw.bluetooth(bytes);
      throw new Error("Unknown printer connection");
    },
    async usb(bytes) {
      if (!navigator.usb) throw new Error("WebUSB not supported in this browser (use Chrome/Edge)");
      // classCode 7 = USB printer class; most ESC/POS printers report it.
      const dev = (await navigator.usb.getDevices())[0] || (await navigator.usb.requestDevice({ filters: [{ classCode: 7 }] }));
      await dev.open();
      if (dev.configuration === null) await dev.selectConfiguration(1);
      const iface = dev.configuration.interfaces.find((i) => i.alternates[0].endpoints.some((e) => e.direction === "out"));
      await dev.claimInterface(iface.interfaceNumber);
      const ep = iface.alternates[0].endpoints.find((e) => e.direction === "out");
      await dev.transferOut(ep.endpointNumber, bytes);
      await dev.close();
    },
    async serial(bytes) {
      if (!navigator.serial) throw new Error("WebSerial not supported in this browser (use Chrome/Edge)");
      const port = (await navigator.serial.getPorts())[0] || (await navigator.serial.requestPort());
      await port.open({ baudRate: Number(localStorage.getItem("sv_baud") || 9600) });
      const w = port.writable.getWriter();
      await w.write(bytes); w.releaseLock(); await port.close();
    },
    _bt: null,
    async bluetooth(bytes) {
      if (!navigator.bluetooth) throw new Error("Web Bluetooth not supported in this browser");
      const SVC = ["000018f0-0000-1000-8000-00805f9b34fb", "e7810a71-73ae-499d-8c15-faa9aef0c3f2", "49535343-fe7d-4ae5-8fa9-9fafd205e455"];
      if (!S.hw._bt || !S.hw._bt.service.device.gatt.connected) {
        const device = await navigator.bluetooth.requestDevice({ acceptAllDevices: true, optionalServices: SVC });
        const server = await device.gatt.connect();
        let ch = null;
        for (const uuid of SVC) {
          try {
            const svc = await server.getPrimaryService(uuid);
            for (const c of await svc.getCharacteristics()) if (c.properties.write || c.properties.writeWithoutResponse) { ch = c; break; }
          } catch (e) { /* try next */ }
          if (ch) break;
        }
        if (!ch) throw new Error("No writable printer characteristic found");
        S.hw._bt = ch;
      }
      for (let i = 0; i < bytes.length; i += 180) await S.hw._bt.writeValueWithoutResponse(bytes.slice(i, i + 180));
    },
    // Weighing scale over WebSerial: returns a number in kg.
    async readScale() {
      if (!navigator.serial) throw new Error("WebSerial not supported");
      const port = (await navigator.serial.getPorts())[0] || (await navigator.serial.requestPort());
      await port.open({ baudRate: Number(localStorage.getItem("sv_scale_baud") || 9600) });
      const reader = port.readable.getReader();
      let txt = "", weight = null;
      const deadline = Date.now() + 3000;
      while (Date.now() < deadline && weight === null) {
        const { value, done } = await reader.read();
        if (done) break;
        txt += new TextDecoder().decode(value);
        const m = txt.match(/([0-9]+\.[0-9]+)/);
        if (m) weight = parseFloat(m[1]);
      }
      reader.releaseLock(); await port.close();
      return weight;
    },
  };

  // Auto-print queued "browser" jobs on this terminal when enabled.
  S.startBrowserPrinting = function () {
    if (localStorage.getItem("sv_browser_print") !== "1") return;
    S.poll(async () => {
      const jobs = await S.api("print-jobs?status=queued&unrouted=1", { quiet: true }).then((d) => d.results || d);
      for (const j of jobs) {
        try { await S.hw.print(j.escpos_b64); await S.api(`print-jobs/${j.id}/ack`, { body: { ok: true }, quiet: true }); }
        catch (e) { await S.api(`print-jobs/${j.id}/ack`, { body: { ok: false, error: String(e.message || e) }, quiet: true }); }
      }
    }, 4000);
  };

  /* ---------- Razorpay ---------- */
  S.razorpay = function (opts, onSuccess) {
    const finish = (resp) => onSuccess(resp);
    if (opts.demo) {
      const m = S.modal({
        title: "Razorpay (demo mode)",
        body: `<p>Razorpay keys are not configured yet, so this is a simulated checkout.</p><div class="card" style="background:var(--surface-2)"><div class="row between"><b>${S.esc(opts.name || "Servora")}</b><b>${S.money(opts.amount / 100)}</b></div><div class="muted small">${S.esc(opts.description || "")}</div></div>
          <p class="small muted" style="margin-top:12px">Set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in Vercel to accept real UPI, cards, netbanking & wallets.</p>`,
        footer: `<button class="btn" data-close>Cancel</button><button class="btn btn-primary" data-pay>Simulate successful payment</button>`,
      });
      m.$("[data-pay]").onclick = () => { m.close(); finish({ razorpay_order_id: opts.order_id, razorpay_payment_id: "pay_demo_" + Date.now(), razorpay_signature: "demo" }); };
      return;
    }
    const load = window.Razorpay ? Promise.resolve() : new Promise((res, rej) => {
      const s = document.createElement("script"); s.src = "https://checkout.razorpay.com/v1/checkout.js"; s.onload = res; s.onerror = rej; document.head.appendChild(s);
    });
    load.then(() => {
      const rz = new window.Razorpay({ key: opts.key, order_id: opts.order_id, amount: opts.amount, currency: opts.currency || "INR", name: opts.name,
        description: opts.description, prefill: opts.prefill, theme: { color: "#F4632F" }, handler: finish });
      rz.on("payment.failed", (r) => S.toast(r.error.description || "Payment failed", "err"));
      rz.open();
    }).catch(() => S.toast("Could not load Razorpay", "err"));
  };

  /* ---------- Shell ---------- */
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-menu-toggle]")) {
      const sb = S.$(".sidebar");
      sb.classList.toggle("open");
      if (sb.classList.contains("open")) {
        const scrim = document.createElement("div"); scrim.className = "scrim"; scrim.onclick = () => { sb.classList.remove("open"); scrim.remove(); };
        document.body.appendChild(scrim);
      } else S.$(".scrim")?.remove();
    }
    if (e.target.closest("[data-theme-toggle]")) {
      const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      const next = cur === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("sv_theme", next); } catch (err) { /* ignore */ }
    }
  });
  try { const t = localStorage.getItem("sv_theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* ignore */ }
})();
