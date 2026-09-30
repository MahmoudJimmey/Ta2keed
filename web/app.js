const $ = s => document.querySelector(s);
const chat = $("#chat");
let user = "web-" + Math.random().toString(36).slice(2, 8);
let busy = false;

function bubble(role, text, img) {
  const d = document.createElement("div");
  d.className = "b " + role;
  if (img) { const i = document.createElement("img"); i.src = img; d.appendChild(i); }
  if (text) d.appendChild(document.createTextNode(text));
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
  busy = false;
  refresh();
  return j;
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

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
  chat.innerHTML = ""; user = "web-" + Math.random().toString(36).slice(2, 8); refresh();
};

let SC = {};
async function loadScenarios() {
  SC = await (await fetch("/api/scenarios")).json();
  $("#scenario").innerHTML = Object.entries(SC).map(([k, v]) => `<option value="${k}">${v.title}</option>`).join("");
}

$("#play").onclick = async () => {
  if (busy) return;
  const sc = SC[$("#scenario").value];
  chat.innerHTML = "";
  user = "demo-" + Math.random().toString(36).slice(2, 8);
  if ($("#scenario").value === "known_refuser") user = "demo-heba";
  for (const step of sc.steps) {
    await sleep(700);
    if (step.image) {
      const url = "/api/receipts/" + step.image;
      await send({ image_b64: await b64OfUrl(url), image_mime: "image/png" }, { img: url });
    } else {
      await send({ text: step.text }, { text: step.text });
    }
  }
};

const fmt = n => Number(n || 0).toLocaleString("en-US");
const statusLabel = { shipped: "shipped", awaiting_deposit: "awaiting deposit", cancelled: "cancelled (not shipped)", confirmed: "confirmed" };

async function refresh() {
  const [imp, orders, events] = await Promise.all([
    fetch("/api/impact").then(r => r.json()), fetch("/api/orders").then(r => r.json()), fetch("/api/events").then(r => r.json())]);
  const m = imp.measured, p = imp.projected;
  $("#kpis").innerHTML = [
    ["g", m.orders_confirmed, "orders confirmed"],
    ["g", fmt(m.revenue_confirmed_egp) + " ج", "confirmed revenue"],
    ["w", m.risky_orders_flagged, "risky orders flagged"],
    ["w", m.fraud_receipts_blocked, "fake receipts blocked"],
    ["p", fmt(m.upsell_revenue_egp) + " ج", `upsell (${m.upsells_accepted}/${m.upsells_offered})`],
    ["g", fmt(m.shipping_loss_avoided_egp) + " ج", "return/shipping loss avoided"],
    ["", "0 min", "human time spent"],
  ].map(([c, v, l]) => `<div class="kpi ${c}"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");

  $("#orders tbody").innerHTML = orders.map(o => {
    const col = o.risk_score >= .5 ? "var(--bad)" : o.risk_score >= .3 ? "var(--warn)" : "var(--acc)";
    return `<tr title="${(o.risk_reasons || []).join(" · ")}"><td>${o.id}</td><td class="ar">${o.customer_name}<br><span class="muted small">${o.customer_phone}</span></td>
      <td>${fmt(o.total)} ج</td><td><span class="risk"><i style="width:${o.risk_score * 100}%;background:${col}"></i></span>${o.risk_score}
      <div class="muted small">${(o.risk_reasons || []).slice(0, 2).join(" · ")}</div></td>
      <td>${o.deposit_required ? (o.deposit_paid ? "✅ " + o.deposit_paid + " ج" : "required") : "—"}</td>
      <td><span class="tag s-${o.status}">${statusLabel[o.status] || o.status}</span></td><td class="small">${o.tracking || "—"}</td></tr>`;
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
    upsell_declined: "🙅", cancelled: "🛑", voice_transcribed: "🎤" };
  $("#events").innerHTML = events.map(e => {
    const t = new Date(e.ts * 1000).toLocaleTimeString();
    let txt = e.type.replace(/_/g, " "), cls = "";
    if (e.type === "order_created") txt = `order ${e.order_id} · ${fmt(e.data.total)} ج · risk ${e.data.risk}${e.data.deposit_required ? " → deposit required" : ""}`;
    if (e.type === "deposit_checked") { txt = e.data.ok ? `deposit verified for ${e.order_id}` : `receipt rejected: ${e.data.reason}`; cls = e.data.ok ? "ev-ok" : (e.data.fraud ? "ev-fraud" : ""); }
    if (e.type === "shipment_created") { txt = `shipment booked ${e.data.tracking} (${e.data.courier})`; cls = "ev-ok"; }
    if (e.type === "upsell_accepted") txt = `upsell accepted: ${e.data.name} +${e.data.price} ج`;
    if (e.type === "cancelled") txt = `order cancelled before shipping (${e.order_id || "draft"})`;
    return `<li class="${cls}"><span class="t">${t}</span>${icon[e.type] || "•"} ${txt}</li>`;
  }).join("");
}

(async () => {
  const h = await (await fetch("/health")).json();
  $("#health").textContent = `LLM: ${h.llm} · courier: ${h.courier}${h.telegram ? " · telegram ✓" : ""}${h.whatsapp ? " · whatsapp ✓" : ""}`;
  await loadScenarios();
  refresh();
  const auto = new URLSearchParams(location.search).get("autoplay");
  if (auto && SC[auto]) { $("#scenario").value = auto; $("#play").click(); }
})();
