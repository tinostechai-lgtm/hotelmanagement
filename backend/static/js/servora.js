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

  // Stable id of this browser (table holds are per device, so two screens can't work one table).
  S.deviceId = () => {
    try {
      let id = localStorage.getItem("sv_device");
      if (!id) { id = "web-" + (crypto.randomUUID ? crypto.randomUUID() : Date.now() + "-" + Math.random().toString(36).slice(2)); localStorage.setItem("sv_device", id); }
      return id;
    } catch (e) { return ""; }
  };
  S.api = async function (path, opts = {}) {
    const o = { method: opts.method || (opts.body ? "POST" : "GET"), headers: { Accept: "application/json" }, credentials: "same-origin" };
    if (opts.body !== undefined) {
      o.headers["Content-Type"] = "application/json";
      o.body = JSON.stringify(opts.body);
    }
    if (o.method !== "GET") o.headers["X-CSRFToken"] = S.csrf();
    o.headers["X-Device-Id"] = S.deviceId();
    const res = await fetch("/api/" + path.replace(/^\//, ""), o);
    let data = null;
    try { data = res.status === 204 ? null : await res.json(); } catch (e) { data = null; }
    if (!res.ok) {
      let msg = (data && (data.detail || Object.entries(data).map(([k, v]) => `${k}: ${[].concat(v).join(" ")}`).join(" · "))) || `Error ${res.status}`;
      if (!opts.quiet) S.toast(msg, "err");
      const err = new Error(msg); err.status = res.status; err.data = data; err.shown = !opts.quiet; throw err;
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

  /* ---------- Direct printing from this browser ----------
     Pressing KOT / Bill / Print prints straight away on this screen's printer:
       via "dialog"   – a receipt-sized page goes to the system print dialog (any printer / Android print service)
       via usb|serial|bluetooth – raw ESC/POS straight to the thermal printer, no dialog at all (Chrome / Edge)
     Settings are per browser (Printer settings button in POS / Bills). */
  const PCFG_KEY = "sv_printer2";
  // Default: tickets go to the printer phone (Servora app with the Bluetooth / Wi-Fi printer) - no print window, no share.
  const PDEF = { auto: true, via: "phone", width: 80, size: "large", kot: true, bill: true, station: false };
  // Characters per line for browser printing: fewer columns = bigger letters.
  const BCOLS = { 80: { normal: 42, large: 32, xlarge: 24 }, 58: { normal: 32, large: 24, xlarge: 18 } };
  S.printer = {
    cfg() {
      try { return Object.assign({}, PDEF, JSON.parse(localStorage.getItem(PCFG_KEY) || "{}")); } catch (e) { return Object.assign({}, PDEF); }
    },
    save(c) { try { localStorage.setItem(PCFG_KEY, JSON.stringify(c)); } catch (e) { /* private mode */ } },
    // Print this order's fresh KOT / bill jobs. Returns how many were printed here.
    async printOrder(orderId, kind) {
      const c = S.printer.cfg();
      if (!c.auto || !c[kind] || !orderId || c.via === "phone") return 0; // the printer phone prints it within ~2 s
      let jobs = [];
      try { jobs = await S.list(`print-jobs?status=queued&order=${orderId}&kind=${kind}&since=180`); } catch (e) { return 0; }
      return S.printer.printJobs(jobs.sort((a, b) => a.id - b.id));
    },
    async printJobs(jobs) {
      const c = S.printer.cfg();
      const docs = [];
      for (const j of jobs) {
        // Claim first so two screens never print the same ticket.
        try { await S.api(`print-jobs/${j.id}/claim`, { body: {}, quiet: true }); } catch (e) { continue; }
        try {
          if (c.via === "dialog") {
            const cols = (BCOLS[c.width] || BCOLS[80])[c.size] || 32;
            const r = await S.api(`print-jobs/${j.id}/render?width=${c.width}&size=${c.size}&columns=${cols}`, { quiet: true });
            docs.push({ job: j, lines: r.lines, cols: r.columns || cols });
          } else {
            const r = await S.api(`print-jobs/${j.id}/render?width=${c.width}&size=${c.size}`, { quiet: true });
            await S.hw.print(r.escpos_b64, c.via);
            await S.api(`print-jobs/${j.id}/ack`, { body: { ok: true }, quiet: true });
            docs.push(null);
          }
        } catch (e) {
          S.api(`print-jobs/${j.id}/ack`, { body: { ok: false, error: String(e.message || e).slice(0, 180) }, quiet: true }).catch(() => {});
          S.toast("Printer: " + (e.message || e), "err");
        }
      }
      const pages = docs.filter(Boolean);
      if (pages.length) {
        S.printer.dialog(pages);
        pages.forEach((d) => S.api(`print-jobs/${d.job.id}/ack`, { body: { ok: true }, quiet: true }).catch(() => {}));
      }
      return docs.length;
    },
    // Receipt-sized page(s) with readable letters, printed via the system dialog.
    dialog(pages) {
      const c = S.printer.cfg();
      const paper = Number(c.width) === 58 ? 58 : 80, content = paper === 58 ? 48 : 72;
      const html = pages.map((p) => {
        const fs = content / (p.cols * 0.6); // mm: the widest line exactly fills the paper
        return `<section style="font-size:${fs.toFixed(2)}mm">` + p.lines.map((l) =>
          `<div class="l${l.b ? " b" : ""}${l.big ? " big" : ""}" style="text-align:${l.a || "left"}">${S.esc(l.t || "") || "&nbsp;"}</div>`).join("") + "</section>";
      }).join("");
      const f = document.createElement("iframe");
      f.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
      document.body.appendChild(f);
      f.contentDocument.open();
      f.contentDocument.write(`<!doctype html><html><head><meta charset="utf-8"><title>Print</title><style>
        @page { size: ${paper}mm auto; margin: 0; }
        html, body { margin: 0; padding: 0; background: #fff; color: #000; }
        body { width: ${content}mm; padding: 2mm ${(paper - content) / 2}mm 6mm; font-family: "Courier New", Courier, monospace; font-weight: 600; }
        section { page-break-after: always; break-after: page; }
        section:last-child { page-break-after: auto; break-after: auto; }
        .l { white-space: pre; line-height: 1.25; overflow: hidden; }
        .b { font-weight: 800; }
        .big { font-size: 1.6em; font-weight: 800; white-space: pre-wrap; }
      </style></head><body>${html}</body></html>`);
      f.contentDocument.close();
      const go = () => { try { f.contentWindow.focus(); f.contentWindow.print(); } catch (e) { S.toast("Could not open printing", "err"); } setTimeout(() => f.remove(), 60000); };
      setTimeout(go, 150);
    },
    // Settings dialog for this browser.
    settings() {
      const c = S.printer.cfg();
      const opt = (v, cur, label) => `<option value="${v}" ${String(v) === String(cur) ? "selected" : ""}>${label}</option>`;
      const m = S.modal({ title: "Printer settings (this screen)", body: `
        <label class="row" style="gap:8px;margin-bottom:10px"><input type="checkbox" id="pc-auto" ${c.auto ? "checked" : ""}> <b>Print straight away when I press KOT / Bill / Print</b></label>
        <div class="grid g2">
          <div class="field"><label>Print KOTs here</label><select id="pc-kot">${opt(1, c.kot ? 1 : 0, "Yes")}${opt(0, c.kot ? 1 : 0, "No")}</select></div>
          <div class="field"><label>Print bills here</label><select id="pc-bill">${opt(1, c.bill ? 1 : 0, "Yes")}${opt(0, c.bill ? 1 : 0, "No")}</select></div>
          <div class="field"><label>Paper width</label><select id="pc-width">${opt(80, c.width, "80 mm (3 inch)")}${opt(58, c.width, "58 mm (2 inch)")}</select></div>
          <div class="field"><label>Text size</label><select id="pc-size">${opt("normal", c.size, "Normal")}${opt("large", c.size, "Large (recommended)")}${opt("xlarge", c.size, "Extra large")}</select></div>
        </div>
        <div class="field"><label>Printer connection</label><select id="pc-via">
          ${opt("phone", c.via, "Printer connected to the Servora app phone (recommended)")}
          ${opt("dialog", c.via, "Printer chosen in the print window (any printer)")}${opt("usb", c.via, "USB thermal printer - prints with no window (Chrome / Edge)")}
          ${opt("bluetooth", c.via, "Bluetooth thermal printer - no window (Chrome)")}${opt("serial", c.via, "Serial / COM thermal printer - no window (Chrome / Edge)")}</select>
          <div class="help">Tip: in Chrome on a PC, start it with <code>--kiosk-printing</code> so the print window is skipped too.</div></div>
        <label class="row" style="gap:8px"><input type="checkbox" id="pc-station" ${c.station ? "checked" : ""}> Also print KOTs / bills sent from other phones (keep this page open)</label>`,
        footer: `<button class="btn" id="pc-test"><i data-lucide="printer"></i>Test print</button><button class="btn btn-primary" id="pc-save">Save</button>` });
      const read = () => ({ auto: m.$("#pc-auto").checked, kot: m.$("#pc-kot").value === "1", bill: m.$("#pc-bill").value === "1",
        width: Number(m.$("#pc-width").value), size: m.$("#pc-size").value, via: m.$("#pc-via").value, station: m.$("#pc-station").checked });
      m.$("#pc-save").onclick = () => { S.printer.save(read()); m.close(); S.toast("Printer settings saved", "ok"); S.printer.startStation(); };
      m.$("#pc-test").onclick = async () => {
        const c2 = read(); S.printer.save(c2);
        const cols = (BCOLS[c2.width] || BCOLS[80])[c2.size];
        const lines = [{ t: "SERVORA", b: true, big: true, a: "center" }, { t: "Test print OK", a: "center" }, { t: "-".repeat(cols) },
          { t: "2 x Masala Dosa".padEnd(cols - 8) + "Rs.180".padStart(8) }, { t: "1 x Filter Coffee".padEnd(cols - 8) + "Rs.40".padStart(8) },
          { t: "-".repeat(cols) }, { t: `Paper ${c2.width} mm - ${c2.size} text`, a: "center" }];
        if (c2.via === "phone") return S.toast("Use 'Test bill printer' in the Servora app on the printer phone", "");
        if (c2.via === "dialog") return S.printer.dialog([{ lines, cols }]);
        const esc = "\x1b@\x1d!" + (c2.size === "xlarge" ? "\x11" : c2.size === "large" ? "\x01" : "\x00") +
          "SERVORA\nTest print OK\n" + `Paper ${c2.width} mm - ${c2.size} text\n\n\n\n` + "\x1dVA\x03";
        try { await S.hw.print(btoa(esc), c2.via); S.toast("Test page sent", "ok"); } catch (e) { S.toast("Printer: " + (e.message || e), "err"); }
      };
    },
    // "Print station": print tickets sent from other phones while this page is open.
    _station: null,
    startStation() {
      const c = S.printer.cfg();
      if (S.printer._station) { S.printer._station(); S.printer._station = null; }
      if (!c.auto || !c.station || c.via === "phone") return;
      const kinds = [c.kot && "kot", c.bill && "bill"].filter(Boolean).join(",");
      if (!kinds) return;
      let busy = false;
      const tick = async () => {
        if (busy) return; busy = true;
        try { const jobs = await S.list(`print-jobs?status=queued&kind=${kinds}&since=600`); if (jobs.length) await S.printer.printJobs(jobs.sort((a, b) => a.id - b.id)); }
        catch (e) { /* offline: try again */ } finally { busy = false; }
      };
      const t = setInterval(tick, 5000); tick();
      S.printer._station = () => clearInterval(t);
    },
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
