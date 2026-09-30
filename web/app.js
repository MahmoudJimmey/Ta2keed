const $ = s => document.querySelector(s);
const chat = $("#chat");
let user = "web-" + Math.random().toString(36).slice(2, 8);
let busy = false;

let lastMsgId = 0;
const userOrders = {};  // order_id -> web user, so courier buttons can pull that customer's chat

function bubble(role, text, img, via) {
  const d = document.createElement("div");
  d.className = "b " + role + (via ? " pro" : "");
  if (img) { const i = document.createElement("img"); i.src = img; d.appendChild(i); }
  if (text) d.appendChild(document.createTextNode(text));
  if (via) { const v = document.createElement("span"); v.className = "via"; v.textContent = via; d.appendChild(v); }
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
}

async function send(payload, show) {
  busy = true;
  if (show) bubble("user", show.text || "", show.img);
  const t = document.createElement("div"); t.className = "typing"; t.textContent = "نور بتكتب…";
  chat.appendChild(t); chat.scrollTop = chat.scrollHeight;
  const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user, ...payload }) });
  const j = await r.json();
  t.remove();
  for (const m of j.replies) { await sleep(350); bubble("agent", m); }
  if (j.order_id) userOrders[j.order_id] = user;
  await syncLastId();
  busy = false;
  refresh();
  return j;
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function syncLastId() {
  const j = await (await fetch(`/api/messages?user=${encodeURIComponent(user)}&since=${lastMsgId}`)).json();
  lastMsgId = j.last_id;
}

const KIND_LABEL = { out_for_delivery: "🔔 delivery highlight", delivered: "🔔 delivery highlight",
  delivery_failed: "🔔 delivery highlight", review: "⭐ 24h after delivery", reorder: "🛍️ 14 days after delivery" };

async function pollProactive() {
  if (busy) return;
  const j = await (await fetch(`/api/messages?user=${encodeURIComponent(user)}&since=${lastMsgId}`)).json();
  for (const m of j.messages) bubble("agent", m.text, null, `${KIND_LABEL[m.meta.kind] || "proactive"} · sent by the agent`);
  lastMsgId = j.last_id;
}
setInterval(pollProactive, 1500);

async function b64OfUrl(url) {
  const blob = await (await fetch(url)).blob();
  return await b64OfBlob(blob);
}
function b64OfBlob(blob) {
  return new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result.split(",")[1]); fr.readAsDataURL(blob); });
}

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
  if (f.type.startsWith("audio")) await send({ audio_b64: b64 }, { text: "🎤 voice note" });
  else await send({ image_b64: b64, image_mime: f.type }, { img: URL.createObjectURL(f) });
  e.target.value = "";
};

$("#reset").onclick = async () => {
  await fetch("/api/reset", { method: "POST" });
  chat.innerHTML = ""; user = "web-" + Math.random().toString(36).slice(2, 8); lastMsgId = 0; refresh();
};

async function courier(orderId, action) {
  if (userOrders[orderId] && userOrders[orderId] !== user) {   // show that customer's chat
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

$("#sendDigest").onclick = async () => { await fetch("/api/digest/send", { method: "POST" }); refresh(); };
$("#ff").onclick = async () => { await fetch("/api/followups/fast-forward", { method: "POST" }); await pollProactive(); refresh(); };

let SC = {};
async function loadScenarios() {
  SC = await (await fetch("/api/scenarios")).json();
  $("#scenario").innerHTML = Object.entries(SC).map(([k, v]) => `<option value="${k}">${v.title}</option>`).join("");
}

$("#play").onclick = async () => {
  if (busy) return;
  const sc = SC[$("#scenario").value];
  chat.innerHTML = ""; lastMsgId = 0;
  user = "demo-" + Math.random().toString(36).slice(2, 8);
  if ($("#scenario").value === "known_refuser") user = "demo-heba";
  for (const step of sc.steps) {
    await sleep(700);
    if (step.courier) {
      const oid = Object.keys(userOrders).find(k => userOrders[k] === user);
      if (oid) { await courier(oid, step.courier); await sleep(900); }
      continue;
    }
    if (step.followups) {
      const oid = Object.keys(userOrders).find(k => userOrders[k] === user);
      await fetch(`/api/followups/fast-forward?kind=${step.followups}${oid ? "&order_id=" + oid : ""}`, { method: "POST" });
      await pollProactive(); refresh(); await sleep(900);
      continue;
    }
    if (step.image) {
      const url = "/api/receipts/" + step.image;
      await send({ image_b64: await b64OfUrl(url), image_mime: "image/png" }, { img: url });
    } else {
      await send({ text: step.text }, { text: step.text });
    }
  }
};

const fmt = n => Number(n || 0).toLocaleString("en-US");
const statusLabel = { shipped: "shipped", awaiting_deposit: "awaiting deposit", cancelled: "cancelled (not shipped)", confirmed: "confirmed",
  delivered: "delivered", refused: "refused", returned: "returned" };
const DL = { created: "at courier", picked_up: "picked up", in_transit: "in transit", out_for_delivery: "out for delivery 🔔",
  delivered: "delivered 🔔", delivery_failed: "failed attempt 🔔", refused: "refused", returned: "returned", cancelled: "cancelled" };
const CHAIN = ["created", "picked_up", "in_transit", "out_for_delivery", "delivered"];
function dlCell(o) {
  if (!o.delivery_status) return `<span class="tag s-${o.status}">${statusLabel[o.status] || o.status}</span>`;
  const idx = CHAIN.indexOf(o.delivery_status === "delivery_failed" ? "out_for_delivery" : o.delivery_status);
  const bad = ["refused", "returned", "delivery_failed", "cancelled"].includes(o.delivery_status);
  const steps = CHAIN.map((s, i) => `<i class="${i <= idx ? "on" : ""}${bad && i === Math.max(idx, 0) ? " fail" : ""}"></i>`).join("");
  return `<span class="tag s-${o.status}">${DL[o.delivery_status] || o.delivery_status}</span><div class="steps">${steps}</div>
    <div class="muted small">${o.tracking || ""}</div>`;
}
function dlButtons(o) {
  if (!o.delivery_status || ["delivered", "refused", "returned", "cancelled"].includes(o.delivery_status)) return "—";
  return `<div class="dl"><button onclick="courier('${o.id}','advance')">next step ▸</button>
    <button class="bad" onclick="courier('${o.id}','delivery_failed')">failed</button>
    <button class="bad" onclick="courier('${o.id}','refused')">refused</button></div>`;
}

async function refresh() {
  const [imp, orders, events, digest] = await Promise.all([
    fetch("/api/impact").then(r => r.json()), fetch("/api/orders").then(r => r.json()), fetch("/api/events?limit=150").then(r => r.json()),
    fetch("/api/digest").then(r => r.text())]);
  $("#digest").textContent = digest;
  const owner = events.filter(e => e.type === "owner_alert");
  $("#owner").innerHTML = owner.map(e => `<li class="${["refused", "fraud", "low_rating", "returned"].includes(e.data.kind) ? "ev-fraud" : ""}">
    <span class="t">${new Date(e.ts * 1000).toLocaleTimeString()}</span><span class="muted small">[${e.data.kind} → ${(e.data.via || []).join(", ")}]</span>
    <div dir="rtl" style="white-space:pre-wrap">${e.data.text.length > 260 ? e.data.text.slice(0, 260) + "…" : e.data.text}</div></li>`).join("")
    || `<li class="muted">Only problems land here instantly (refused, failed attempt, fake receipt, low rating). Everything else goes into the daily summary.</li>`;
  const m = imp.measured, p = imp.projected;
  $("#kpis").innerHTML = [
    ["g", m.orders_confirmed, "orders confirmed"],
    ["g", fmt(m.revenue_confirmed_egp) + " ج", "confirmed revenue"],
    ["w", m.risky_orders_flagged, "risky orders flagged"],
    ["w", m.fraud_receipts_blocked, "fake receipts blocked"],
    ["p", fmt(m.upsell_revenue_egp) + " ج", `upsell (${m.upsells_accepted}/${m.upsells_offered})`],
    ["g", fmt(m.shipping_loss_avoided_egp) + " ج", "return/shipping loss avoided"],
    ["g", m.orders_delivered, `delivered · ${m.measured_refusal_rate !== null ? (m.measured_refusal_rate * 100).toFixed(0) + "% refused (measured)" : "refusal rate: n/a yet"}`],
    ["p", m.avg_rating ? "⭐ " + m.avg_rating : "—", `rating (${m.ratings_count}) · ${m.repeat_orders} repeat`],
    ["", `${m.customer_highlight_msgs} / ${m.courier_updates_received}`, "customer msgs / courier updates"],
    ["", "0 min", "human time spent"],
  ].map(([c, v, l]) => `<div class="kpi ${c}"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");

  $("#orders tbody").innerHTML = orders.map(o => {
    const col = o.risk_score >= .5 ? "var(--bad)" : o.risk_score >= .3 ? "var(--warn)" : "var(--acc)";
    return `<tr title="${(o.risk_reasons || []).join(" · ")}"><td>${o.id}</td><td class="ar">${o.customer_name}<br><span class="muted small">${o.customer_phone}</span></td>
      <td>${fmt(o.total)} ج</td><td><span class="risk"><i style="width:${o.risk_score * 100}%;background:${col}"></i></span>${o.risk_score}
      <div class="muted small">${(o.risk_reasons || []).slice(0, 2).join(" · ")}</div></td>
      <td>${o.deposit_required ? (o.deposit_paid ? "✅ " + o.deposit_paid + " ج" : "required") : "—"}</td>
      <td>${dlCell(o)}${o.rating ? `<div class="small">${"⭐".repeat(o.rating)}</div>` : ""}${o.source === "reorder" ? `<div class="small" style="color:#b3a1ff">repeat order</div>` : ""}</td>
      <td>${dlButtons(o)}</td></tr>`;
  }).join("") || `<tr><td colspan="7" class="muted">No orders yet — press ▶ Play demo or chat on the left.</td></tr>`;

  $("#roi").innerHTML = [
    ["⏱ Hours returned to the owner", p.hours_saved_per_month + " h"],
    ["💰 Staff cost saved", fmt(p.staff_cost_saved_egp) + " ج"],
    [`📦 Refusals avoided (${(p.refusal_rate_before * 100).toFixed(0)}% → ${(p.refusal_rate_after * 100).toFixed(1)}%)`, fmt(p.refusal_cost_saved_egp) + " ج"],
    ["🎁 Upsell revenue", fmt(p.upsell_revenue_egp) + " ج"],
    ["🌙 After-hours orders captured", fmt(p.after_hours_revenue_egp) + " ج"],
    ["♻️ Margin recovered from saved orders", fmt(p.recovered_margin_egp) + " ج"],
  ].map(([k, v]) => `<div class="roi-row"><span>${k}</span><b>${v}</b></div>`).join("") +
    `<div class="roi-total">${fmt(p.total_monthly_impact_egp)} ج / month</div>
     <div class="muted small">for ${fmt(p.assumptions.monthly_orders)} orders/month · cost saved ${fmt(p.total_cost_saved_egp)} ج + new revenue ${fmt(p.total_new_revenue_egp)} ج</div>`;

  const icon = { order_created: "🧾", shipment_created: "🚚", deposit_checked: "💳", upsell_offered: "🎁", upsell_accepted: "🛍️",
    upsell_declined: "🙅", cancelled: "🛑", voice_transcribed: "🎤", delivery_update: "📦", customer_notified: "💬",
    owner_alert: "👩‍💼", rating: "⭐", digest_sent: "📊", reschedule_requested: "📅" };
  $("#events").innerHTML = events.map(e => {
    const t = new Date(e.ts * 1000).toLocaleTimeString();
    let txt = e.type.replace(/_/g, " "), cls = "";
    if (e.type === "order_created") txt = `order ${e.order_id} · ${fmt(e.data.total)} ج · risk ${e.data.risk}${e.data.deposit_required ? " → deposit required" : ""}`;
    if (e.type === "deposit_checked") { txt = e.data.ok ? `deposit verified for ${e.order_id}` : `receipt rejected: ${e.data.reason}`; cls = e.data.ok ? "ev-ok" : (e.data.fraud ? "ev-fraud" : ""); }
    if (e.type === "shipment_created") { txt = `shipment booked ${e.data.tracking} (${e.data.courier})`; cls = "ev-ok"; }
    if (e.type === "upsell_accepted") txt = `upsell accepted: ${e.data.name} +${e.data.price} ج`;
    if (e.type === "cancelled") txt = `order cancelled before shipping (${e.order_id || "draft"})`;
    if (e.type === "delivery_update") { txt = `${e.order_id} → ${DL[e.data.status] || e.data.status} ${e.data.customer_notified ? "· customer notified" : "· internal only"}`; cls = ["refused", "returned", "delivery_failed"].includes(e.data.status) ? "ev-fraud" : (e.data.status === "delivered" ? "ev-ok" : ""); }
    if (e.type === "customer_notified") txt = `message to customer (${e.data.kind}) via ${e.data.via}`;
    if (e.type === "owner_alert") txt = `owner alert: ${e.data.kind} → ${(e.data.via || []).join(", ")}`;
    if (e.type === "rating") txt = `rating ${"⭐".repeat(e.data.rating)} on ${e.order_id}`;
    if (e.type === "digest_sent") txt = `daily summary sent → ${(e.data.via || []).join(", ")}`;
    return `<li class="${cls}"><span class="t">${t}</span>${icon[e.type] || "•"} ${txt}</li>`;
  }).join("");
}

(async () => {
  const h = await (await fetch("/health")).json();
  $("#health").textContent = `LLM: ${h.llm} · courier: ${h.courier}${h.telegram ? " · telegram ✓" : ""}${h.whatsapp ? " · whatsapp ✓" : ""}`;
  $("#ownerVia").textContent = "delivered to: " + h.owner_channels.join(", ");
  await loadScenarios();
  refresh();
  const auto = new URLSearchParams(location.search).get("autoplay");
  if (auto && SC[auto]) { $("#scenario").value = auto; $("#play").click(); }
})();
