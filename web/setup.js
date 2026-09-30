// Ta2keed setup wizard — vanilla JS, talks to /api/setup/*
const $ = s => document.querySelector(s);
const L = v => Array.isArray(v) ? v.join(", ") : (v ?? "");
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
let S = null;          // server state
let cur = 0;
let draftProducts = null;

const STEPS = [
  { id: "welcome", title: "Welcome" },
  { id: "admin", title: "Owner login", key: "admin" },
  { id: "shop", title: "Your shop", key: "shop" },
  { id: "products", title: "Products", key: "products" },
  { id: "shipping", title: "Shipping & fees", key: "shipping" },
  { id: "ai", title: "AI brain", key: "ai", optional: true },
  { id: "whatsapp", title: "WhatsApp", key: "whatsapp", optional: true },
  { id: "owner", title: "Alerts & daily summary", key: "owner", optional: true },
  { id: "courier", title: "Courier", key: "courier", optional: true },
  { id: "numbers", title: "Business numbers", key: "numbers", optional: true },
  { id: "live", title: "Go live" },
];

async function api(path, body, method) {
  const r = await fetch(path, { method: method || (body !== undefined ? "POST" : "GET"),
    headers: body !== undefined ? { "Content-Type": "application/json" } : {}, body: body !== undefined ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || j.error || r.statusText);
  return j;
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.style.display = "block"; clearTimeout(t._h); t._h = setTimeout(() => t.style.display = "none", 2600); }
function result(el, r) { el.className = "result " + (r.ok ? "ok" : "bad"); el.textContent = (r.ok ? "✓ " : "✗ ") + r.message; }

async function load() {
  S = await api("/api/setup/state");
  const local = /localhost|127\.0\.0\.1/.test(location.host);
  $("#where").textContent = local ? "🖥 running on this computer" : "🌍 running online · " + location.host;
  renderNav(); render();
}

function renderNav() {
  $("#nav").innerHTML = STEPS.map((s, i) => {
    const done = s.key ? S.steps[s.key] : (s.id === "live" ? S.setup_complete : i < cur);
    return `<a class="${i === cur ? "on" : ""} ${done ? "done" : ""}" onclick="go(${i})"><span class="dot">${done ? "✓" : i}</span>${s.title}${s.optional ? '<span class="opt">optional</span>' : ""}</a>`;
  }).join("");
}
window.go = i => { cur = i; renderNav(); render(); window.scrollTo(0, 0); };

// ---------- field helpers
function field(key, label, opts = {}) {
  const f = S.fields[key] || { value: "", source: "default" };
  const locked = f.source === "environment";
  const type = opts.type || (f.secret ? "password" : "text");
  return `<label class="f">${label}${locked ? ' <span class="lock">🔒 set by the host environment</span>' : ""}
    <input class="i" data-k="${key}" type="${type}" value="${esc(opts.value ?? f.value)}" placeholder="${esc(opts.ph || "")}" ${locked ? "disabled" : ""} autocomplete="off">
    ${opts.hint ? `<span class="hint">${opts.hint}</span>` : ""}</label>`;
}
function sfield(sec, key, label, opts = {}) {
  const v = (S.store[sec] || {})[key];
  return `<label class="f">${label}<input class="i" data-s="${sec}.${key}" type="${opts.type || "text"}" value="${esc(opts.fmt ? opts.fmt(v) : v ?? "")}" placeholder="${esc(opts.ph || "")}">
    ${opts.hint ? `<span class="hint">${opts.hint}</span>` : ""}</label>`;
}
function collect() {
  const settings = {}, store = {};
  document.querySelectorAll("#panel [data-k]").forEach(el => { if (!el.disabled) settings[el.dataset.k] = el.value; });
  document.querySelectorAll("#panel [data-s]").forEach(el => {
    const [sec, key] = el.dataset.s.split(".");
    let v = el.value;
    if (el.type === "number") v = v === "" ? null : Number(v);
    if (el.dataset.pct) v = Number(el.value) / 100;
    if (el.dataset.list) v = el.value.split(",").map(x => parseInt(x)).filter(x => !isNaN(x));
    (store[sec] = store[sec] || {})[key] = v;
  });
  return { settings, store };
}
async function save(extra = {}, next = true) {
  const { settings, store } = collect();
  const payload = { settings: { ...settings, ...(extra.settings || {}) }, store: { ...store, ...(extra.store || {}) }, flags: extra.flags || {} };
  try {
    const r = await api("/api/setup/save", payload);
    if (r.env_locked.length) toast("Some values are set by the host and weren't changed");
    else toast("Saved ✓");
    await load();
    if (next) go(Math.min(cur + 1, STEPS.length - 1));
  } catch (e) { toast("⚠ " + e.message); }
}
window.save = save;
async function test(what, el, body) {
  const box = document.getElementById(el);
  box.className = "result ok"; box.textContent = "Testing…";
  try { await save({}, false); result(box, await api("/api/setup/test/" + what, body || {})); }
  catch (e) { result(box, { ok: false, message: e.message }); }
}
window.test = test;
function nav(extraSave, skip = true) {
  return `<div class="btns"><button class="btn-go" onclick='save(${JSON.stringify(extraSave || {})})'>Save & continue →</button>
    ${skip ? `<button class="btn-ghost" onclick="go(cur+1)">Skip for now</button>` : ""}
    ${cur > 0 ? `<button class="btn-ghost" onclick="go(cur-1)">← Back</button>` : ""}</div>`;
}
function copyBox(v, empty) {
  return v ? `<div class="copy"><code>${esc(v)}</code><button onclick="navigator.clipboard.writeText('${esc(v)}');toast('Copied')">Copy</button></div>`
           : `<div class="muted small">${empty}</div>`;
}

// ---------- steps
const R = {};

R.welcome = () => `
  <h2>Let's set up your order agent 👋</h2>
  <p class="lead">Ta2keed answers your customers' DMs, confirms COD orders, checks InstaPay deposits, books the courier,
  sends delivery highlights and a daily summary. This wizard takes about 10 minutes. Everything except your shop details is optional.
  Skipped parts keep working in demo mode.</p>
  <div class="welcome">
    <div class="choice" onclick="go(1)"><b>🛍️ Set up my shop</b><span class="muted">Add your products, prices, shipping fees and (optionally) connect WhatsApp, the AI and your courier.</span></div>
    <div class="choice" onclick="skipToDemo()"><b>▶ Just show me the demo</b><span class="muted">Uses the sample shop “Nour Boutique”. You can come back to <code>/setup</code> any time.</span></div>
  </div>
  <div class="box"><h4>Where does the agent run?</h4>
    <div class="muted small" style="line-height:1.7">Right now it runs on <b>${/localhost|127\.0\.0\.1/.test(location.host) ? "this computer" : location.host}</b>.
    That's perfect for trying it and for the demo video. For real customers on WhatsApp it must be reachable from the internet 24/7.
    The last step, <b>Go live</b>, shows the easiest ways: a free tunnel from your laptop (for testing) or a one-click cloud host (for real use).</div></div>`;
window.skipToDemo = async () => { await api("/api/setup/save", { flags: { _setup_skipped: true } }); location.href = "/"; };

R.admin = () => `
  <h2>Owner login</h2>
  <p class="lead">Protects your dashboard and settings. Webhooks from WhatsApp and the courier stay open so they keep working.
  ${S.steps.admin ? "<b style='color:var(--acc)'>A password is already set.</b> Enter a new one to change it." : ""}</p>
  <div class="row">${field("ADMIN_PASSWORD", "Password (min 8 characters)", { type: "password", value: "", ph: S.steps.admin ? "leave empty to keep the current one" : "" })}
  <label class="f">Repeat password<input class="i" id="pw2" type="password" autocomplete="off"></label></div>
  <div class="muted small">On this computer the dashboard works without a password, but you need one before putting Ta2keed online.</div>
  <div class="btns"><button class="btn-go" onclick="savePw()">Save & continue →</button><button class="btn-ghost" onclick="go(cur+1)">Skip (this computer only)</button></div>`;
window.savePw = () => {
  const a = document.querySelector('[data-k="ADMIN_PASSWORD"]');
  if (!a.value) return go(cur + 1);
  if (a.value !== $("#pw2").value) return toast("Passwords don't match");
  if (a.value.length < 8) return toast("Use at least 8 characters");
  save();
};

R.shop = () => `
  <h2>Your shop</h2>
  <p class="lead">This is what customers see in the chat and where deposits are paid.</p>
  <div class="row">${sfield("store", "name", "Shop name (English)", { ph: "Nour Boutique" })}${sfield("store", "name_ar", "Shop name (Arabic)", { ph: "نور بوتيك" })}
    ${sfield("store", "agent_name_ar", "Assistant's name (Arabic)", { ph: "نور", hint: "The agent introduces itself with this name" })}</div>
  <div class="row">${sfield("store", "city", "City", { ph: "Cairo" })}
    <label class="f">Working hours (orders outside are counted as “after-hours”)<div style="display:flex;gap:8px">
      <input class="i" type="number" min="0" max="23" id="h1" value="${S.store.store.business_hours?.[0] ?? 10}"><input class="i" type="number" min="1" max="24" id="h2" value="${S.store.store.business_hours?.[1] ?? 22}"></div></label></div>
  <h3 style="margin:18px 0 6px;font-size:15px">Payments & deposit policy</h3>
  <div class="row">${sfield("policy", "instapay_handle", "InstaPay address", { ph: "yourshop@instapay", hint: "Receipts sent to any other account are rejected" })}
    ${sfield("policy", "vodafone_cash", "Vodafone Cash number", { ph: "010 1234 5678" })}</div>
  <div class="row">${sfield("policy", "deposit_amount", "Deposit for risky orders (EGP)", { type: "number" })}
    ${sfield("policy", "high_value_order_egp", "Always ask a deposit above (EGP)", { type: "number" })}
    <label class="f">Risk level that needs a deposit<input class="i" type="number" data-s="policy.risk_deposit_threshold" step="0.05" min="0.1" max="1" value="${S.store.policy.risk_deposit_threshold}">
      <span class="hint">0.5 = balanced · lower = more deposits · higher = fewer</span></label>
    ${sfield("policy", "delivery_days", "Delivery time told to customers", { ph: "2-4" })}</div>
  <div class="btns"><button class="btn-go" onclick="saveShop()">Save & continue →</button>${cur > 0 ? '<button class="btn-ghost" onclick="go(cur-1)">← Back</button>' : ""}</div>`;
window.saveShop = () => save({ store: { store: { business_hours: [Number($("#h1").value), Number($("#h2").value)] } } });

R.products = () => {
  const ps = draftProducts || S.store.products;
  const rows = ps.map((p, i) => `<tr data-i="${i}">
      <td><input data-p="name_ar" value="${esc(p.name_ar)}" dir="rtl" placeholder="عباية"></td>
      <td><input data-p="name_en" value="${esc(p.name_en)}" placeholder="Abaya"></td>
      <td style="width:80px"><input data-p="price" value="${esc(p.price)}" type="number"></td>
      <td><input data-p="sizes" value="${esc(L(p.sizes))}" placeholder="S, M, L"></td>
      <td><input data-p="colors" value="${esc(L(p.colors))}" placeholder="black, beige"></td>
      <td><input data-p="keywords" value="${esc(L(p.keywords))}" dir="rtl" placeholder="عبايه, abaya"></td>
      <td><select data-p="upsell_sku" class="i" style="padding:5px"><option value="">—</option>${ps.filter(q => q.sku).map(q => `<option value="${esc(q.sku)}" ${(p.upsell?.sku || p.upsell_sku) === q.sku ? "selected" : ""}>${esc(q.name_en || q.name_ar)}</option>`).join("")}</select></td>
      <td style="width:70px"><input data-p="upsell_price" value="${esc(p.upsell?.price ?? p.upsell_price ?? "")}" type="number"></td>
      <td class="x"><input type="hidden" data-p="sku" value="${esc(p.sku)}"><button onclick="delProd(${i})">✕</button></td></tr>`).join("");
  return `<h2>Products</h2>
  <p class="lead">What customers can order. <b>Keywords</b> are the words people really type (Arabic, Franco, typos) so the agent recognises the product.
  <b>Upsell</b> is the item offered with it at the special price.</p>
  ${S.store_is_demo ? '<div class="box">These are the demo products. Replace them with yours, or upload a spreadsheet.</div>' : ""}
  <div style="overflow:auto"><table class="ed"><thead><tr><th>Name (Arabic)</th><th>Name (English)</th><th>Price</th><th>Sizes</th><th>Colours</th><th>Keywords</th><th>Upsell item</th><th>Upsell price</th><th></th></tr></thead>
  <tbody id="prods">${rows}</tbody></table></div>
  <div class="btns" style="margin-top:10px"><button onclick="addProd()">+ Add product</button>
    <label class="upl" style="padding:7px 12px;border:1px solid var(--line);border-radius:8px;cursor:pointer">⬆ Upload CSV / Excel-CSV<input type="file" accept=".csv,text/csv" hidden onchange="uploadCsv(this)"></label>
    <a href="/api/setup/products-template.csv" class="small">⬇ download template</a></div>
  <div class="muted small" style="margin-top:6px">Colours the agent understands in Arabic: black, navy, beige, pink, white, olive (other colours work in English/as typed).</div>
  <div class="btns"><button class="btn-go" onclick="saveProducts()">Save & continue →</button><button class="btn-ghost" onclick="go(cur-1)">← Back</button></div>`;
};
function readProducts() {
  return [...document.querySelectorAll("#prods tr")].map(tr => {
    const o = {}; tr.querySelectorAll("[data-p]").forEach(el => o[el.dataset.p] = el.value); return o;
  });
}
window.addProd = () => { draftProducts = readProducts(); draftProducts.push({ name_ar: "", name_en: "", price: "", sizes: [], colors: [], keywords: [] }); render(); };
window.delProd = i => { draftProducts = readProducts(); draftProducts.splice(i, 1); render(); };
window.uploadCsv = async inp => {
  const text = await inp.files[0].text();
  const r = await fetch("/api/setup/products-csv", { method: "POST", body: text });
  const j = await r.json();
  if (!r.ok) return toast("⚠ " + (j.detail || "Could not read the file"));
  draftProducts = j.products; render(); toast(`Loaded ${j.products.length} products. Review and save`);
};
window.saveProducts = async () => {
  const ps = readProducts().filter(p => p.name_ar || p.name_en);
  if (!ps.length) return toast("Add at least one product");
  await save({ store: { products: ps } }); draftProducts = null;
};

R.shipping = () => {
  const z = S.store.shipping.zones;
  const names = { cairo: "Cairo", giza: "Giza", alex: "Alexandria", delta: "Delta governorates", canal: "Canal cities", upper: "Upper Egypt" };
  return `<h2>Shipping & fees</h2><p class="lead">The agent detects the zone from the address (e.g. “فيصل” → Giza) and adds the right fee.</p>
  <table class="ed" style="max-width:520px"><thead><tr><th>Zone</th><th>Shipping fee (EGP)</th></tr></thead><tbody>
  ${Object.entries(z).map(([k, v]) => `<tr><td>${names[k] || k} <span class="muted small">${v.label_ar}</span></td><td><input type="number" data-zone="${k}" value="${v.fee}"></td></tr>`).join("")}
  </tbody></table>
  <div class="row" style="margin-top:14px;max-width:520px">${sfield("shipping", "return_fee", "Courier return fee when a parcel is refused (EGP)", { type: "number", hint: "Used to calculate the money saved by deposits" })}</div>
  <div class="btns"><button class="btn-go" onclick="saveShipping()">Save & continue →</button><button class="btn-ghost" onclick="go(cur-1)">← Back</button></div>`;
};
window.saveShipping = () => {
  const zones = JSON.parse(JSON.stringify(S.store.shipping.zones));
  document.querySelectorAll("[data-zone]").forEach(el => zones[el.dataset.zone].fee = Number(el.value));
  save({ store: { shipping: { zones, return_fee: Number(document.querySelector('[data-s="shipping.return_fee"]').value) } }, flags: { _shipping_saved: true } });
};

R.ai = () => {
  const P = S.llm_presets;
  const curProv = S.fields.LLM_PROVIDER.value, curBase = S.fields.LLM_BASE_URL.value;
  const active = curProv === "offline" || !curProv ? "offline" : Object.keys(P).find(k => P[k].provider === curProv && (P[k].base_url || "") === (curBase || "")) || "openai";
  const card = (k, t, d) => `<div class="choice ${active === k ? "on" : ""}" onclick="pickLLM('${k}')"><b>${t}</b><span class="muted">${d}</span></div>`;
  return `<h2>AI brain <span class="muted small">optional</span></h2>
  <p class="lead">Without AI the agent already works with built-in Egyptian-Arabic rules (free, fast). Adding an AI lets it understand unusual messages,
  answer free questions and <b>read real receipt screenshots</b>.</p>
  <div class="cards">${card("offline", "No AI (free)", "Rules only. Demo receipts only.")}
    ${card("gemini", "Google Gemini", "Free tier available. Good Arabic.")}${card("anthropic", "Claude", "Best quality. Paid.")}
    ${card("openai", "OpenAI", "GPT-4o-mini. Cheap.")}${card("groq", "Groq", "Free & very fast. Text only.")}${card("openrouter", "OpenRouter", "Any model, one key.")}</div>
  <div id="llmFields" style="${active === "offline" ? "display:none" : ""}">
    <div class="row">${field("LLM_API_KEY", "API key", { hint: "Gemini: aistudio.google.com/apikey · Claude: console.anthropic.com · OpenAI: platform.openai.com/api-keys · Groq: console.groq.com/keys" })}
      ${field("LLM_MODEL", "Model")}</div>
    <input type="hidden" data-k="LLM_PROVIDER" value="${esc(curProv)}"><input type="hidden" data-k="LLM_BASE_URL" value="${esc(curBase)}">
    <div class="btns" style="margin-top:0"><button onclick="test('llm','llmRes')">Test connection</button></div><div id="llmRes" class="result"></div>
    <div class="box"><h4>🎤 Voice notes (optional)</h4><div class="muted small">Customers often order by voice. A free Groq key transcribes Egyptian Arabic voice notes.</div>
      <div class="row" style="margin-top:8px">${field("STT_API_KEY", "Groq API key for voice notes", { hint: "console.groq.com/keys" })}
      <input type="hidden" data-k="STT_BASE_URL" value="https://api.groq.com/openai/v1"></div></div>
  </div>
  ${nav()}`;
};
window.pickLLM = k => {
  const p = S.llm_presets[k];
  S.fields.LLM_PROVIDER.value = p.provider; S.fields.LLM_BASE_URL.value = p.base_url;
  if (k !== "offline") S.fields.LLM_MODEL.value = p.model;
  render();
};

R.whatsapp = () => {
  const hook = S.webhooks.whatsapp;
  return `<h2>WhatsApp <span class="muted small">optional</span></h2>
  <p class="lead">Connect your business WhatsApp so customers order there and receive delivery highlights. Uses Meta's official Cloud API
  (no risk of bans). Meta gives a free test number to try it today.</p>
  <div class="box"><h4>1 · Create the Meta app (≈10 min)</h4><ol class="steps-list">
    <li>Open <a href="https://developers.facebook.com/apps/creation/" target="_blank">developers.facebook.com → Create app</a> → type <b>Business</b> → add <b>WhatsApp</b>.</li>
    <li>In <b>WhatsApp → API Setup</b> copy the <b>access token</b>, <b>Phone number ID</b> and <b>WhatsApp Business Account ID</b> below.</li>
    <li>Still there: add your phone (and a friend's, as the “customer”) under <b>To</b> → verify the code.</li>
    <li>App secret: <b>App settings → Basic → App secret</b> (Show).</li>
    <li>Permanent token (so it doesn't expire in 24 h): Business settings → <b>System users</b> → Add → Generate token with <i>whatsapp_business_messaging</i> + <i>whatsapp_business_management</i>.</li></ol></div>
  <div class="row">${field("WHATSAPP_ACCESS_TOKEN", "Access token")}${field("WHATSAPP_PHONE_NUMBER_ID", "Phone number ID", { ph: "1234567890" })}</div>
  <div class="row">${field("WHATSAPP_BUSINESS_ACCOUNT_ID", "WhatsApp Business Account ID", { ph: "for message templates" })}${field("WHATSAPP_APP_SECRET", "App secret", { hint: "Lets Ta2keed verify messages really come from Meta" })}</div>
  <div class="btns" style="margin-top:0"><button onclick="test('whatsapp','waRes')">Test connection</button>
    <input class="i" id="waTo" placeholder="your number, e.g. 2010…" style="max-width:220px"><button onclick="test('whatsapp-send','waRes',{to:$('#waTo').value})">Send me a test message</button></div>
  <div id="waRes" class="result"></div>
  <div class="box"><h4>2 · Connect the webhook (so Ta2keed receives messages)</h4>
    <div class="muted small" style="margin-bottom:8px">In Meta: <b>WhatsApp → Configuration → Webhook → Edit</b>, paste these, then <b>Manage → subscribe to “messages”</b>.</div>
    <div class="muted small">Callback URL</div>${copyBox(hook, "⚠ Needs a public https address first. See <a href='#' onclick='go(10)'>Go live</a> (a free tunnel works for testing).")}
    <div class="muted small" style="margin-top:8px">Verify token</div>
    <div class="row" style="margin:4px 0 0">${field("WHATSAPP_VERIFY_TOKEN", "", {})}</div></div>
  <div class="box"><h4>3 · Message templates (for updates sent more than 24 h after the customer's last message)</h4>
    <div class="muted small">WhatsApp only allows free text within 24 h of the customer's last message. Delivery updates and follow-ups come later,
    so they use 7 pre-approved templates. Ta2keed can submit them for you.</div>
    <div class="btns" style="margin-top:8px"><button onclick="tpl(false)">Check status</button><button onclick="tpl(true)">Create missing templates</button></div>
    <div id="tplRes" class="result"></div><div id="tplList"></div></div>
  ${nav()}`;
};
window.tpl = async create => {
  const box = $("#tplRes"); box.className = "result ok"; box.textContent = create ? "Submitting…" : "Checking…";
  await save({}, false);
  const r = await api("/api/setup/test/templates", { create });
  result(box, r);
  $("#tplList").innerHTML = r.templates?.length ? `<table class="ed" style="margin-top:8px"><tr><th>Template</th><th>Category</th><th>Status</th></tr>${r.templates.map(t => `<tr><td>${t.name}</td><td>${t.category}</td><td><span class="badge b-${t.status}">${t.status}</span></td></tr>`).join("")}</table>` : "";
};

R.owner = () => `
  <h2>Alerts & daily summary <span class="muted small">optional</span></h2>
  <p class="lead">You get an instant message only when something needs you (refused parcel, fake receipt, bad rating, reschedule),
  plus one daily summary. Pick WhatsApp, Telegram, or both.</p>
  <div class="box"><h4>📱 On WhatsApp</h4><div class="muted small">Needs the WhatsApp step. Enter your personal WhatsApp number in international format.</div>
    <div class="row" style="margin-top:8px">${field("OWNER_WHATSAPP", "Your WhatsApp number", { ph: "201012345678", hint: "You can also message the business number “ملخص”, “شحنات” or “عربون” any time" })}</div></div>
  <div class="box"><h4>✈️ On Telegram (easiest, free, no approval)</h4><ol class="steps-list">
    <li>Open <a href="https://t.me/BotFather" target="_blank">@BotFather</a> → <b>/newbot</b> → copy the token here → Test.</li>
    <li>Open your new bot and send: <b>/owner ${S.owner_claim_code}</b>. That links your Telegram as the owner.</li></ol>
    <div class="row" style="margin-top:8px">${field("TELEGRAM_BOT_TOKEN", "Bot token")}
      <label class="f">Linked owner chat<input class="i" disabled value="${S.fields.OWNER_TELEGRAM_CHAT_ID.value || "not linked yet"}"></label></div>
    <div class="btns" style="margin-top:0"><button onclick="test('telegram','tgRes')">Test</button><button onclick="load()">Refresh</button></div><div id="tgRes" class="result"></div>
    <div class="muted small">The bot also works as a customer channel, which is handy for demos.</div></div>
  <div class="row" style="max-width:560px">${sfield("notifications", "digest_time", "Daily summary time", { type: "time" })}
    ${sfield("notifications", "review_after_hours", "Ask for a rating after (hours)", { type: "number" })}
    ${sfield("notifications", "reorder_after_days", "Send reorder offer after (days)", { type: "number" })}</div>
  <div class="btns" style="margin-top:0"><button onclick="test('digest','dgRes')">Send today's summary now</button></div><div id="dgRes" class="result"></div>
  ${nav()}`;

R.courier = () => {
  const m = S.courier_mode;
  const card = (k, t, d) => `<div class="choice ${m === k ? "on" : ""}" onclick="pickCourier('${k}')"><b>${t}</b><span class="muted">${d}</span></div>`;
  return `<h2>Courier <span class="muted small">optional</span></h2>
  <p class="lead">How parcels leave your shop and how delivery updates come back.</p>
  <div class="cards">${card("mock", "Demo courier", "Fake tracking numbers; buttons on the dashboard simulate updates.")}
    ${card("bosta", "Bosta", "Real shipments + automatic delivery updates.")}${card("own_driver", "My own delivery person", "Mark delivered/refused from the dashboard or any app via the webhook.")}</div>
  ${m === "bosta" ? `<div class="row">${field("BOSTA_API_KEY", "Bosta API key", { hint: "Bosta dashboard → Settings → API integration → Create API key" })}</div>
    <div class="btns" style="margin-top:0"><button onclick="test('bosta','bRes')">Test key</button></div><div id="bRes" class="result"></div>
    <div class="box"><h4>Delivery updates webhook</h4><div class="muted small">Bosta dashboard → Settings → Webhooks → add this URL, and put the secret in the Authorization header field.</div>
      ${copyBox(S.webhooks.bosta, "⚠ Needs a public https address first. See Go live.")}
      <div class="row" style="margin-top:8px">${field("COURIER_WEBHOOK_SECRET", "Webhook secret")}<div style="align-self:end"><button onclick="genSecret()">Generate</button></div></div></div>` : ""}
  ${m === "own_driver" ? `<div class="box"><h4>Updating deliveries</h4><div class="muted small">Use the <b>failed / refused</b> and <b>next step</b> buttons on the dashboard, or have any app / Google Form call:</div>
      ${copyBox(S.webhooks.courier ? S.webhooks.courier + '  {"order_id":"NB-1001","status":"delivered"}' : "", "Available after Go live.")}
      <div class="row" style="margin-top:8px">${field("COURIER_WEBHOOK_SECRET", "Webhook secret (Authorization header)")}<div style="align-self:end"><button onclick="genSecret()">Generate</button></div></div></div>` : ""}
  ${nav({ flags: { _courier_mode: m } })}`;
};
window.pickCourier = k => { S.courier_mode = k; render(); };
window.genSecret = async () => { const r = await api("/api/setup/secret"); document.querySelector('[data-k="COURIER_WEBHOOK_SECRET"]').value = r.value; };

R.numbers = () => `
  <h2>Business numbers <span class="muted small">optional</span></h2>
  <p class="lead">Your real numbers make the ROI on the dashboard and the impact slides true for your shop. Rough estimates are fine.</p>
  <div class="row">${sfield("economics", "monthly_orders", "Orders per month", { type: "number" })}
    ${sfield("economics", "manual_minutes_per_order", "Minutes spent per order today (reply, confirm, book courier)", { type: "number" })}
    ${sfield("economics", "staff_hourly_cost_egp", "Cost of 1 hour of staff time (EGP)", { type: "number" })}</div>
  <div class="row"><label class="f">Parcels refused at the door today (%)<input class="i" type="number" data-s="economics.baseline_refusal_rate" data-pct="1" value="${Math.round(S.store.economics.baseline_refusal_rate * 100)}"></label>
    <label class="f">Refusal rate when a deposit was paid (%)<input class="i" type="number" data-s="economics.refusal_rate_with_deposit" data-pct="1" value="${Math.round(S.store.economics.refusal_rate_with_deposit * 100)}"></label>
    <label class="f">Gross margin (%)<input class="i" type="number" data-s="economics.gross_margin" data-pct="1" value="${Math.round(S.store.economics.gross_margin * 100)}"></label></div>
  ${nav()}`;

R.live = () => {
  const st = S.steps, local = /localhost|127\.0\.0\.1/.test(location.host);
  const li = (ok, t) => `<li>${ok ? "✅" : "⬜"} ${t}</li>`;
  return `<h2>Go live</h2>
  <p class="lead">Ta2keed is a small web server. It needs to run somewhere that stays on and that WhatsApp/Bosta can reach.</p>
  <div class="hostgrid">
    <div class="choice ${local ? "on" : ""}"><b>🖥 This computer</b><span class="muted small">Great for trying it and recording the demo. Customers can't reach it and it stops when the PC sleeps.<br>Start: <code>run.bat</code></span></div>
    <div class="choice"><b>🔗 This computer + free tunnel</b><span class="muted small">Gives your laptop a public https link in 1 minute, enough to test real WhatsApp messages. Link changes each run.<br>Start: <code>run.bat online</code></span></div>
    <div class="choice ${!local ? "on" : ""}"><b>☁️ Cloud host (24/7)</b><span class="muted small">For real customers. One click with the repo's <code>render.yaml</code> (Render) or the <code>Dockerfile</code> (Railway, Fly.io, any VPS). Needs a persistent disk for orders.<br>See <a href="https://github.com/MahmoudJimmey/Ta2keed/blob/main/docs/deploy.md" target="_blank">docs/deploy.md</a></span></div>
  </div>
  <div class="box"><h4>Public address</h4>
    <div class="muted small">Detected: ${S.public_url ? `<b>${esc(S.public_url)}</b>` : "none (running locally)"}. If you use a tunnel or custom domain, paste it here so the wizard shows the right webhook links.</div>
    <div class="row" style="margin:8px 0 0">${field("PUBLIC_URL", "Public URL", { ph: "https://ta2keed-yourshop.onrender.com" })}</div>
    <div class="btns" style="margin-top:0"><button onclick="test('public-url','puRes',{url:document.querySelector('[data-k=PUBLIC_URL]').value})">Test from the internet</button></div><div id="puRes" class="result"></div></div>
  <div class="box"><h4>Checklist</h4><ul class="summary" style="list-style:none;padding:0;margin:0">
    ${li(st.admin, "Owner password")}${li(st.shop, "Shop details & payment accounts")}${li(st.products, "Your products")}${li(st.shipping, "Shipping fees")}
    ${li(st.ai, "AI brain <span class='muted small'>(optional)</span>")}${li(st.whatsapp, "WhatsApp connected <span class='muted small'>(optional)</span>")}
    ${li(st.owner, "Owner alerts <span class='muted small'>(optional)</span>")}${li(st.courier, "Courier <span class='muted small'>(optional)</span>")}${li(st.numbers, "Business numbers <span class='muted small'>(optional)</span>")}</ul></div>
  <div class="box"><h4>Demo tools</h4><label style="display:flex;gap:10px;align-items:center"><input type="checkbox" id="demo" ${S.demo_mode ? "checked" : ""}>
    Keep demo tools (Play demo, Reset, fake courier buttons, sample customers). <span class="muted small">Turn off for a real shop.</span></label></div>
  <div class="btns"><button class="btn-go big" onclick="finish()">✓ Finish & open dashboard</button><button class="btn-ghost" onclick="go(cur-1)">← Back</button></div>`;
};
window.finish = async () => {
  if (!local() && !S.steps.admin) return toast("Set an owner password before going online");
  await save({ settings: { DEMO_MODE: $("#demo").checked ? "on" : "off" }, flags: { _setup_complete: true } }, false);
  location.href = "/";
};
const local = () => /localhost|127\.0\.0\.1/.test(location.host);

function render() { $("#panel").innerHTML = R[STEPS[cur].id](); }
load().catch(e => { $("#panel").innerHTML = `<h2>Can't load setup</h2><p class="lead">${esc(e.message)}</p>`; });
