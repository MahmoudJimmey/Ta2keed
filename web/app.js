const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const chat = $("#chat");
let user = "web-" + Math.random().toString(36).slice(2, 8);
let busy = false;
let lastMsgId = 0;
const userOrders = {};  // order_id -> web user, so courier buttons can pull that customer's chat
const sleep = ms => new Promise(r => setTimeout(r, ms));
const fmt = n => Number(n || 0).toLocaleString("en-US");
const time = ts => new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 2400); }

// ---------------- chat
function bubble(role, text, img, via) {
  const d = document.createElement("div");
  d.className = "b " + role + (via ? " pro" : "");
  d.dir = "auto";
  if (img) { const i = document.createElement("img"); i.src = img; i.alt = "attachment"; d.appendChild(i); if (!text) d.classList.add("has-img"); }
  if (text) d.appendChild(document.createTextNode(text));
  if (via) { const v = document.createElement("span"); v.className = "via"; v.textContent = via; d.appendChild(v); }
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
}
function typing(on) {
  let t = chat.querySelector(".typing");
  if (on && !t) { t = document.createElement("div"); t.className = "typing"; t.innerHTML = "<i></i><i></i><i></i>"; chat.appendChild(t); chat.scrollTop = chat.scrollHeight; }
  if (!on && t) t.remove();
}
async function send(payload, show) {
  busy = true;
  if (show) bubble("user", show.text || "", show.img);
  typing(true);
  try {
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user, ...payload }) });
    const j = await r.json();
    typing(false);
    for (const m of j.replies || []) { await sleep(380); bubble("agent", m); }
    if (j.order_id) userOrders[j.order_id] = user;
    await syncLastId();
    return j;
  } catch (e) { typing(false); toast("Couldn't reach the agent"); }
  finally { busy = false; refresh(); }
}
async function syncLastId() {
  const j = await (await fetch(`/api/messages?user=${encodeURIComponent(user)}&since=${lastMsgId}`)).json();
  j.messages.forEach(m => shown.add(m.id));
  lastMsgId = Math.max(lastMsgId, j.last_id);
}
const KIND_LABEL = { out_for_delivery: "Delivery update", delivered: "Delivery update", delivery_failed: "Delivery update",
  review: "Sent 24 h after delivery", reorder: "Sent 14 days after delivery",
  deposit_confirmed: "After the owner confirmed the transfer", deposit_not_received: "Owner didn't receive the transfer" };
const shown = new Set();
let polling = null;
function pollProactive() {            // single-flight: concurrent callers share one request, each message shown once
  if (busy || document.hidden) return Promise.resolve();
  if (polling) return polling;
  polling = (async () => {
    try {
      const j = await (await fetch(`/api/messages?user=${encodeURIComponent(user)}&since=${lastMsgId}`)).json();
      for (const m of j.messages) {
        if (shown.has(m.id)) continue;
        shown.add(m.id);
        bubble("agent", m.text, null, `${KIND_LABEL[m.meta.kind] || "Sent automatically"} · by the agent`);
      }
      lastMsgId = Math.max(lastMsgId, j.last_id);
    } finally { polling = null; }
  })();
  return polling;
}
setInterval(pollProactive, 1500);

async function b64OfUrl(url) { return b64OfBlob(await (await fetch(url)).blob()); }
function b64OfBlob(blob) { return new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result.split(",")[1]); fr.readAsDataURL(blob); }); }

$("#form").onsubmit = async e => {
  e.preventDefault();
  const text = $("#msg").value.trim();
  if (!text || busy) return;
  $("#msg").value = "";
  await send({ text }, { text });
};
document.querySelectorAll("#receipts button").forEach(b => b.onclick = async () => {
  if (busy) return;
  const url = "/api/receipts/" + b.dataset.r;
  await send({ image_b64: await b64OfUrl(url), image_mime: "image/png" }, { img: url });
});
$("#file").onchange = async e => {
  const f = e.target.files[0]; if (!f) return;
  const b64 = await b64OfBlob(f);
  if (f.type.startsWith("audio")) await send({ audio_b64: b64 }, { text: "Voice note" });
  else await send({ image_b64: b64, image_mime: f.type }, { img: URL.createObjectURL(f) });
  e.target.value = "";
};
$("#reset").onclick = async () => {
  await fetch("/api/reset", { method: "POST" });
  chat.innerHTML = ""; user = "web-" + Math.random().toString(36).slice(2, 8); lastMsgId = 0; refresh(); toast("Demo data reset");
};
$("#theme").onclick = () => window.toggleTheme();

async function courier(orderId, action) {
  if (userOrders[orderId] && userOrders[orderId] !== user) {
    user = userOrders[orderId]; chat.innerHTML = ""; lastMsgId = 0;
    const j = await (await fetch(`/api/messages?user=${encodeURIComponent(user)}&since=0`)).json();
    lastMsgId = j.last_id;
  }
  const url = action === "advance" ? `/api/orders/${orderId}/advance` : `/api/orders/${orderId}/delivery`;
  const body = action === "advance" ? null : JSON.stringify({ status: action, reason: action === "refused" ? "العميل رفض الاستلام" : "الموبايل مقفول" });
  await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body });
  await pollProactive(); refresh();
}
window.courier = courier;
$("#sendDigest").onclick = async () => { const r = await (await fetch("/api/digest/send", { method: "POST" })).json(); toast("Summary sent · " + (r.via || []).join(", ")); refresh(); };
$("#ff").onclick = async () => { await fetch("/api/followups/fast-forward", { method: "POST" }); await pollProactive(); refresh(); toast("Follow-ups sent"); };

let SC = {};
async function loadScenarios() {
  SC = await (await fetch("/api/scenarios")).json();
  $("#scenario").innerHTML = Object.entries(SC).map(([k, v]) => `<option value="${esc(k)}">${esc(v.title.replace(/ -> /g, " → "))}</option>`).join("");
}
$("#play").onclick = async () => {
  if (busy) return;
  const sc = SC[$("#scenario").value];
  if (!sc) return;
  chat.innerHTML = ""; lastMsgId = 0;
  user = $("#scenario").value === "known_refuser" ? "demo-heba" : "demo-" + Math.random().toString(36).slice(2, 8);
  for (const step of sc.steps) {
    await sleep(700);
    const oid = () => Object.keys(userOrders).find(k => userOrders[k] === user);
    if (step.courier) { if (oid()) { await courier(oid(), step.courier); await sleep(900); } continue; }
    if (step.owner) {
      await refresh(); await sleep(1600);                         // let the viewer see the "Payments to confirm" card
      for (const c of await (await fetch("/api/payment-checks")).json()) {
        await fetch(`/api/payment-checks/${c.id}/decide`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approve: step.owner === "approve" }) });
        toast(step.owner === "approve" ? "Owner confirmed the transfer" : "Owner: not received");
      }
      await pollProactive(); refresh(); await sleep(900); continue;
    }
    if (step.followups) {
      await fetch(`/api/followups/fast-forward?kind=${step.followups}${oid() ? "&order_id=" + oid() : ""}`, { method: "POST" });
      await pollProactive(); refresh(); await sleep(900); continue;
    }
    if (step.image) { const url = "/api/receipts/" + step.image; await send({ image_b64: await b64OfUrl(url), image_mime: "image/png" }, { img: url }); }
    else await send({ text: step.text }, { text: step.text });
  }
};

// ---------------- dashboard
const STATUS = { shipped: "Shipped", awaiting_deposit: "Awaiting deposit", awaiting_owner_confirm: "Checking payment", cancelled: "Not shipped", confirmed: "Confirmed",
  delivered: "Delivered", refused: "Refused", returned: "Returned" };
const DL = { created: "At courier", picked_up: "Picked up", in_transit: "In transit", out_for_delivery: "Out for delivery",
  delivered: "Delivered", delivery_failed: "Failed attempt", refused: "Refused", returned: "Returned", cancelled: "Cancelled" };
const CHAIN = ["created", "picked_up", "in_transit", "out_for_delivery", "delivered"];
const DONE = ["delivered", "refused", "returned", "cancelled"];

function dlCell(o) {
  if (!o.delivery_status) return `<span class="tag s-${esc(o.status)}">${STATUS[o.status] || esc(o.status)}</span>`;
  const idx = CHAIN.indexOf(o.delivery_status === "delivery_failed" ? "out_for_delivery" : o.delivery_status);
  const bad = ["refused", "returned", "delivery_failed", "cancelled"].includes(o.delivery_status);
  const cls = o.delivery_status === "delivered" ? "s-delivered" : bad ? "s-refused" : "s-shipped";
  const steps = CHAIN.map((s, i) => `<i class="${i <= idx ? "on" : ""}${bad && i === Math.max(idx, 0) ? " fail" : ""}"></i>`).join("");
  return `<span class="tag ${cls}">${DL[o.delivery_status] || esc(o.delivery_status)}</span><div class="steps">${steps}</div>
    <div class="cell-2">${esc(o.tracking || "")}</div>`;
}
function dlButtons(o) {
  if (window.DEMO_OFF && !["mock"].includes(window.COURIER)) return `<span class="cell-2">Automatic</span>`;
  if (!o.delivery_status || DONE.includes(o.delivery_status)) return `<span class="cell-2">—</span>`;
  return `<div class="dl"><button class="go" onclick="courier('${esc(o.id)}','advance')">Next step</button>
    <button class="bad" onclick="courier('${esc(o.id)}','delivery_failed')">Failed</button>
    <button class="bad" onclick="courier('${esc(o.id)}','refused')">Refused</button></div>`;
}
const EVENT_TXT = e => {
  const d = e.data || {};
  switch (e.type) {
    case "order_created": return [`Order ${e.order_id}`, `${fmt(d.total)} EGP · risk ${d.risk}${d.deposit_required ? " · deposit required" : ""}`, d.deposit_required ? "ev-warn" : "ev-info"];
    case "deposit_checked": return d.ok ? ["Deposit verified", e.order_id, "ev-ok"] : ["Receipt rejected", `${e.order_id} · ${String(d.reason || "").replace(/_/g, " ")}`, d.fraud ? "ev-fraud" : "ev-warn"];
    case "shipment_created": return ["Shipment booked", `${e.order_id} · ${d.tracking}`, "ev-ok"];
    case "upsell_offered": return ["Upsell offered", d.name || "", ""];
    case "upsell_accepted": return ["Upsell accepted", `${d.name} · +${d.price} EGP`, "ev-ok"];
    case "upsell_declined": return ["Upsell declined", "", ""];
    case "cancelled": return ["Order cancelled", `${e.order_id || "draft"} · before shipping`, "ev-warn"];
    case "delivery_update": return [DL[d.status] || d.status, `${e.order_id} · ${d.customer_notified ? "customer notified" : "kept internal"}`,
      ["refused", "returned", "delivery_failed"].includes(d.status) ? "ev-fraud" : d.status === "delivered" ? "ev-ok" : ""];
    case "customer_notified": return ["Message to customer", `${d.kind} · ${d.via}`, "ev-info"];
    case "owner_alert": return ["Owner alerted", `${d.kind} · ${(d.via || []).join(", ")}`, ""];
    case "rating": return ["Rating received", `${"★".repeat(d.rating)} · ${e.order_id}`, d.rating >= 4 ? "ev-ok" : "ev-warn"];
    case "digest_sent": return ["Daily summary sent", (d.via || []).join(", "), "ev-info"];
    case "reschedule_requested": return ["Reschedule requested", e.order_id, "ev-warn"];
    case "payment_confirmation_requested": return ["Owner asked to confirm transfer", `${e.order_id} · ${fmt(d.amount)} EGP · ${(d.via || []).join(", ")}`, "ev-warn"];
    case "payment_owner_decision": return [d.approved ? "Owner confirmed transfer" : "Owner: transfer not received", `${e.order_id} · via ${String(d.by || "").replace("owner-", "")}${d.minutes != null ? ` · ${d.minutes} min` : ""}`, d.approved ? "ev-ok" : "ev-fraud"];
    case "voice_transcribed": return ["Voice note transcribed", "", ""];
    case "login": return ["Owner signed in", d.ip || "", ""];
    case "login_failed": return ["Failed sign-in", d.ip || "", "ev-fraud"];
    default: return [e.type.replace(/_/g, " "), e.order_id || "", ""];
  }
};
const OWNER_TITLE = { payment_check: "Confirm a transfer", refused: "Parcel refused", returned: "Parcel returned", delivery_failed: "Delivery attempt failed", fraud: "Suspicious receipt",
  low_rating: "Low rating", reschedule_requested: "New delivery time requested", digest: "Daily summary" };

async function refresh() {
  if (document.hidden) return;
  let imp, orders, events, digest;
  try {
    [imp, orders, events, digest] = await Promise.all([
      fetch("/api/impact").then(r => r.json()), fetch("/api/orders").then(r => r.json()),
      fetch("/api/events?limit=150").then(r => r.json()), fetch("/api/digest").then(r => r.text())]);
  } catch (e) { return; }
  const m = imp.measured, p = imp.projected;

  $("#kpis").innerHTML = [
    ["Confirmed orders", fmt(m.orders_confirmed), `${m.orders_auto_shipped} shipped automatically`],
    ["Revenue confirmed", fmt(m.revenue_confirmed_egp) + "<small>EGP</small>", m.upsell_revenue_egp ? `incl. ${fmt(m.upsell_revenue_egp)} EGP upsell` : "no upsells yet"],
    ["Losses prevented", fmt(m.shipping_loss_avoided_egp) + "<small>EGP</small>", `${m.risky_orders_stopped_before_shipping} risky parcel${m.risky_orders_stopped_before_shipping === 1 ? "" : "s"} not shipped`],
    ["Delivered", fmt(m.orders_delivered), m.measured_refusal_rate !== null ? `${(m.measured_refusal_rate * 100).toFixed(0)}% refused (measured)` : "refusal rate after first deliveries"],
  ].map(([l, v, d]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="d">${esc(d)}</div></div>`).join("");
  $("#kpisSub").innerHTML = [
    [m.fraud_receipts_blocked, "fake receipts blocked"], [m.deposits_collected, "deposits verified"],
    [m.avg_rating ? m.avg_rating + "★" : "—", `rating${m.ratings_count ? ` (${m.ratings_count})` : ""}`], [m.repeat_orders, "repeat orders"],
    [`${m.customer_highlight_msgs}/${m.courier_updates_received}`, "courier updates sent to customers"], ["0 min", "of your time"],
  ].map(([v, l]) => `<span><b>${esc(v)}</b>${esc(l)}</span>`).join("");

  $("#orders tbody").innerHTML = orders.map(o => {
    const col = o.risk_score >= .5 ? "var(--bad)" : o.risk_score >= .3 ? "var(--warn)" : "var(--ok)";
    const lvl = o.risk_score >= .5 ? "High" : o.risk_score >= .3 ? "Medium" : "Low";
    return `<tr title="${esc((o.risk_reasons || []).join(" · "))}">
      <td><div class="oid">${esc(o.id)}</div><div class="cell-2">${time(o.created_at)}</div></td>
      <td class="ar"><div>${esc(o.customer_name)}</div><div class="cell-2">${esc(o.customer_phone)}</div></td>
      <td class="num">${fmt(o.total)} EGP</td>
      <td><span class="risk"><i style="width:${Math.max(6, o.risk_score * 100)}%;background:${col}"></i></span>${lvl}
        <div class="cell-2">${esc((o.risk_reasons || []).slice(0, 2).join(" · "))}</div></td>
      <td>${o.deposit_required ? (o.deposit_paid ? `<span class="tag s-delivered">${o.deposit_paid} EGP paid</span>` : o.status === "awaiting_owner_confirm" ? `<span class="tag s-awaiting_deposit">Confirm transfer</span>` : `<span class="tag s-awaiting_deposit">Requested</span>`) : `<span class="cell-2">Not needed</span>`}</td>
      <td>${dlCell(o)}${o.rating ? `<div class="stars">${"★".repeat(o.rating)}</div>` : ""}${o.source === "reorder" ? `<div class="repeat">Repeat order</div>` : ""}</td>
      <td>${dlButtons(o)}</td></tr>`;
  }).join("") || `<tr><td colspan="7"><div class="empty"><b>No orders yet</b>${window.DEMO_OFF ? "Orders appear here as customers message you." : "Press Play above, or order from the phone on the right."}</div></td></tr>`;

  const decided = new Set(events.filter(e => e.type === "payment_owner_decision").map(e => e.data.check_id));
  const owner = events.filter(e => e.type === "owner_alert" && e.data.kind !== "digest" &&
    !(e.data.kind === "payment_check" && decided.has(e.data.check_id)));
  $("#owner").innerHTML = owner.map(e => {
    const bad = ["refused", "fraud", "low_rating", "returned"].includes(e.data.kind);
    return `<li class="${bad ? "ev-fraud" : "ev-warn"}"><span class="dot"></span><div><div class="k">${OWNER_TITLE[e.data.kind] || esc(e.data.kind)}</div>
      <div class="body" dir="rtl">${esc(e.data.text.length > 240 ? e.data.text.slice(0, 240) + "…" : e.data.text)}</div>
      <div class="via">Sent to ${esc((e.data.via || []).join(", "))}</div></div><time>${time(e.ts)}</time></li>`;
  }).join("") || `<li class="note">Nothing needs you right now.<br><span class="small">Refusals, fake receipts, low ratings and reschedules appear here instantly.</span></li>`;

  $("#digest").textContent = digest;
  renderPayChecks();

  $("#roi").innerHTML = [
    ["Hours returned to you", p.hours_saved_per_month + " h"],
    ["Staff cost saved", fmt(p.staff_cost_saved_egp) + " EGP"],
    [`Refusals avoided · ${(p.refusal_rate_before * 100).toFixed(0)}% → ${(p.refusal_rate_after * 100).toFixed(1)}%`, fmt(p.refusal_cost_saved_egp) + " EGP"],
    ["Upsell revenue", fmt(p.upsell_revenue_egp) + " EGP"],
    ["After-hours orders", fmt(p.after_hours_revenue_egp) + " EGP"],
    ["Margin from saved orders", fmt(p.recovered_margin_egp) + " EGP"],
  ].map(([k, v]) => `<div class="roi-row"><span>${k}</span><b>${v}</b></div>`).join("") +
    `<div class="roi-total">${fmt(p.total_monthly_impact_egp)} <small>EGP per month</small></div>
     <p class="foot">Based on ${fmt(p.assumptions.monthly_orders)} orders a month: ${fmt(p.total_cost_saved_egp)} EGP saved + ${fmt(p.total_new_revenue_egp)} EGP new revenue.</p>`;

  $("#events").innerHTML = events.filter(e => e.type !== "owner_alert").slice(0, 80).map(e => {
    const [k, body, cls] = EVENT_TXT(e);
    return `<li class="${cls}"><span class="dot"></span><div><span class="k">${esc(k)}</span>${body ? ` <span class="muted">· ${esc(body)}</span>` : ""}</div><time>${time(e.ts)}</time></li>`;
  }).join("") || `<li class="note">The agent's actions will appear here.</li>`;
}

// ---------------- owner payment confirmation
async function renderPayChecks() {
  let rows = [];
  try { rows = await (await fetch("/api/payment-checks")).json(); } catch (e) { return; }
  $("#pay-sec").hidden = !rows.length;
  $("#payChecks").innerHTML = rows.map(c => {
    const i = c.info || {};
    const mins = Math.max(0, Math.round((Date.now() / 1000 - c.asked_at) / 60));
    return `<div class="pay-item">
      ${c.has_image ? `<a class="pay-img" href="/api/payment-checks/${c.id}/image" target="_blank" rel="noopener"><img src="/api/payment-checks/${c.id}/image" alt="Receipt"></a>` : `<div class="pay-img none">No image</div>`}
      <div class="pay-body">
        <div class="pay-amt">${fmt(c.amount)} <small>EGP</small></div>
        <div class="pay-meta"><b>${esc(c.order_id)}</b> · <span dir="auto">${esc(c.customer_name)}</span> · ${esc(c.customer_phone)}</div>
        <dl class="pay-dl">
          <dt>Reference</dt><dd class="mono">${esc(c.reference || "—")}</dd>
          <dt>Sent to</dt><dd>${esc(i.recipient || "—")}</dd>
          <dt>Receipt time</dt><dd>${esc(i.datetime || "—")}</dd>
          <dt>Waiting</dt><dd>${mins < 1 ? "just now" : mins + " min"}${c.reminders ? ` · ${c.reminders} reminder${c.reminders > 1 ? "s" : ""}` : ""}</dd>
        </dl>
        <div class="pay-actions">
          <button class="btn btn-primary" onclick="decidePay(${c.id}, true)">Received · ship order</button>
          <button class="btn btn-danger" onclick="decidePay(${c.id}, false)">Not received</button>
        </div>
      </div></div>`;
  }).join("");
}
async function decidePay(id, approve) {
  if (!approve && !confirm("Mark this transfer as NOT received? The order stays on hold and the customer is asked to check.")) return;
  const r = await fetch(`/api/payment-checks/${id}/decide`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approve }) });
  const j = await r.json();
  toast(j.message || (approve ? "Confirmed" : "Marked as not received"));
  await pollProactive(); refresh();
}
window.decidePay = decidePay;

// scroll-spy for the segmented control
const secs = [["#top", 0], ["#orders-sec", 1], ["#inbox-sec", 2]];
addEventListener("scroll", () => {
  let on = 0;
  secs.forEach(([s, i]) => { const el = $(s); if (el && el.getBoundingClientRect().top < 140) on = i; });
  document.querySelectorAll("#seg a").forEach((a, i) => a.classList.toggle("on", i === on));
}, { passive: true });

(async () => {
  const h = await (await fetch("/health")).json();
  window.COURIER = h.courier;
  const dot = (on, t) => `<span><i class="${on ? "on" : ""}"></i>${t}</span>`;
  $("#health").innerHTML = dot(h.whatsapp, "WhatsApp") + dot(h.llm !== "offline", h.llm !== "offline" ? "AI" : "Rules") +
    dot(h.courier !== "mock", h.courier === "mock" ? "Demo courier" : "Bosta");
  $("#ownerVia").textContent = "alerts go to " + h.owner_channels.join(" & ");
  if (!h.demo) { document.querySelectorAll(".demo-only").forEach(el => el.hidden = true); window.DEMO_OFF = true; }
  if (!/localhost|127\.0\.0\.1/.test(location.host)) { $("#logout").hidden = false; }
  $("#logout").onclick = async () => { await fetch("/logout", { method: "POST" }); location.href = "/login"; };
  $("#today").textContent = new Date().toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
  try {
    const st = (await (await fetch("/api/impact")).json()).store;
    $("#storeName").textContent = st.name_ar || st.name;
    $("#shopEyebrow").textContent = st.name;
    $("#storeInitial").textContent = (st.agent_name_ar || st.name_ar || "ت").slice(0, 1);
    document.title = `${st.name} · Ta2keed`;
  } catch (e) { /* ignore */ }
  await loadScenarios();
  refresh();
  setInterval(refresh, 8000);
  const auto = new URLSearchParams(location.search).get("autoplay");
  if (auto && SC[auto]) { $("#scenario").value = auto; $("#play").click(); }
})();
