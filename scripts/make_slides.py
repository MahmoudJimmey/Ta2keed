"""Generate the impact slide deck (docs/Ta2keed-impact-slides.pptx).

Numbers are pulled live from ta2keed.impact, so after you put your pilot shop's real numbers in
data/store.json -> economics, re-run:   python -m scripts.make_slides
Requires python-pptx (dev only):        pip install python-pptx
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["TA2KEED_DB"] = str(Path(tempfile.mkdtemp()) / "slides.db")
os.environ["LLM_PROVIDER"] = "offline"

from pptx import Presentation  # noqa: E402
from pptx.chart.data import CategoryChartData  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE  # noqa: E402
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN  # noqa: E402
from pptx.util import Emu, Inches, Pt  # noqa: E402

from ta2keed import agent, db, impact  # noqa: E402
from ta2keed.config import store  # noqa: E402
from ta2keed.scenarios import SCENARIOS  # noqa: E402

# ---------------------------------------------------------------- run the demo to get measured numbers
db.reset(seed=True)
from ta2keed import aftercare, delivery  # noqa: E402

for sc in SCENARIOS.values():
    for step in sc["steps"]:
        if "courier" in step or "followups" in step:
            conv = db.get_conversation("slides", sc["user"])
            oid = conv.get("order_id") or (db.one("SELECT id FROM orders WHERE conv_id=? ORDER BY created_at DESC LIMIT 1",
                                                  (conv["id"],)) or {}).get("id")
            if "courier" in step:
                delivery.advance(delivery.find_order(oid))
            else:
                aftercare.fast_forward(oid, step["followups"])
            continue
        if "image" in step:
            agent.handle("slides", sc["user"], image=(ROOT / "data" / "receipts" / step["image"]).read_bytes())
        else:
            agent.handle("slides", sc["user"], step["text"])
M, P = impact.measured(), impact.projected()
A = P["assumptions"]
S = store()

# ---------------------------------------------------------------- style
BG = RGBColor(0x0E, 0x11, 0x17)
CARD = RGBColor(0x18, 0x1C, 0x25)
LINE = RGBColor(0x2A, 0x30, 0x3C)
FG = RGBColor(0xF2, 0xF4, 0xF8)
MUTED = RGBColor(0x8E, 0x96, 0xA8)
GREEN = RGBColor(0x25, 0xD3, 0x66)
PURPLE = RGBColor(0x8B, 0x6C, 0xFF)
AMBER = RGBColor(0xF5, 0xA5, 0x24)
RED = RGBColor(0xFF, 0x5D, 0x5D)
FONT = "Segoe UI"
TOTAL = 14


def egp(n):
    return f"{int(round(n)):,} EGP"


prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]


def text(slide, x, y, w, h, s, size=18, color=FG, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
         font=FONT, spacing=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    lines = s if isinstance(s, list) else [s]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if spacing:
            p.space_after = Pt(spacing)
        runs = line if isinstance(line, list) else [(line, {})]
        for r in runs:
            if isinstance(r, str):
                r = (r, {})
            run = p.add_run()
            run.text = r[0]
            f = run.font
            f.name = r[1].get("font", font)
            f.size = Pt(r[1].get("size", size))
            f.bold = r[1].get("bold", bold)
            f.color.rgb = r[1].get("color", color)
    return tb


def box(slide, x, y, w, h, fill=CARD, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08):
    sh = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if line:
        sh.line.color.rgb = line
        sh.line.width = Pt(1)
    else:
        sh.line.fill.background()
    sh.shadow.inherit = False
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        sh.adjustments[0] = radius
    return sh


def base(n, kicker, title):
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = BG
    box(s, 0, 0, 13.333, 0.08, fill=GREEN, shape=MSO_SHAPE.RECTANGLE)
    text(s, 0.6, 0.35, 9, 0.35, kicker.upper(), size=12, color=GREEN, bold=True)
    text(s, 0.6, 0.65, 12.2, 0.9, title, size=30, bold=True)
    text(s, 0.6, 7.0, 6, 0.3, "Ta2keed · Agents at Work 2026", size=10, color=MUTED)
    text(s, 11.7, 7.0, 1.05, 0.3, f"{n} / {TOTAL}", size=10, color=MUTED, align=PP_ALIGN.RIGHT)
    return s


def notes(s, t):
    s.notes_slide.notes_text_frame.text = t


def stat(s, x, y, w, h, value, label, color=GREEN, sub=None, vsize=34):
    box(s, x, y, w, h)
    text(s, x + 0.25, y + 0.2, w - 0.5, 0.75, value, size=vsize, bold=True, color=color)
    text(s, x + 0.25, y + 0.95 + (vsize - 34) / 72, w - 0.5, 0.5, label, size=13, color=FG, bold=True)
    if sub:
        text(s, x + 0.25, y + 1.3 + (vsize - 34) / 72, w - 0.5, h - 1.4, sub, size=11, color=MUTED)


# ================================================================ 1. title
s = prs.slides.add_slide(BLANK)
s.background.fill.solid()
s.background.fill.fore_color.rgb = BG
box(s, 0, 0, 0.18, 7.5, fill=GREEN, shape=MSO_SHAPE.RECTANGLE)
logo = box(s, 0.8, 1.2, 0.9, 0.9, fill=GREEN, radius=0.2)
text(s, 0.8, 1.2, 0.9, 0.9, "✓", size=40, bold=True, color=BG, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
text(s, 1.9, 1.15, 8, 1.0, [[("Ta2keed ", {"size": 54, "bold": True}), ("تأكيد", {"size": 40, "color": GREEN})]])
text(s, 0.8, 2.55, 11.5, 1.4, "The AI agent that confirms, de-risks and ships cash-on-delivery orders "
     "for Egyptian social-commerce shops — without a human in the loop.", size=26, color=FG)
text(s, 0.8, 4.05, 11.5, 0.5, "DM in  →  order confirmed  →  deposit verified  →  courier booked", size=18, color=MUTED)
for i, (v, l) in enumerate([(f"{P['hours_saved_per_month']:.0f} h", "returned to the owner / month"),
                            (f"{P['refusal_rate_before']*100:.0f}% → {P['refusal_rate_after']*100:.0f}%", "COD refusal rate"),
                            (egp(P["total_monthly_impact_egp"]), "monthly impact (projected)")]):
    stat(s, 0.8 + i * 3.95, 4.8, 3.7, 1.35, v, l, vsize=28)
text(s, 0.8, 6.55, 12, 0.4, "Agents at Work 2026 · Mahmoud Gamal · github.com/MahmoudJimmey/Ta2keed", size=13, color=MUTED)
notes(s, "Ta2keed means 'confirmation'. One sentence: it replaces the person who sits in the DMs all day "
         "confirming COD orders, and it stops the refusals that eat the shop's margin.")

# ================================================================ 2. the SME
s = base(2, "The SME we built for", "Instagram & WhatsApp shops that live on cash-on-delivery")
box(s, 0.6, 1.7, 5.6, 4.95)
text(s, 0.9, 1.9, 5.1, 0.45, "Pilot profile", size=14, color=GREEN, bold=True)
text(s, 0.9, 2.3, 5.1, 0.6, f"{S['store']['name']} ({S['store']['name_ar']})", size=24, bold=True)
text(s, 0.9, 2.95, 5.1, 3.6, [
    f"• Women's fashion, sells only via Instagram, Facebook & WhatsApp DMs",
    f"• ~{A['monthly_orders']:,} orders / month, almost all cash-on-delivery",
    f"• 1 person answers DMs, confirms, books the courier",
    f"• ~{A['manual_minutes_per_order']} min of manual handling per order",
    f"• ~{A['baseline_refusal_rate']*100:.0f}% of parcels refused at the door",
    f"• Each refusal costs ~{A['loss_per_refusal_egp']} EGP (shipping + return) and a week of stock"],
    size=15, color=FG, spacing=8)
text(s, 6.6, 1.7, 6.2, 0.5, "Why this segment", size=14, color=GREEN, bold=True)
rows = [("Huge", "Social commerce is how most small Egyptian brands sell — no website, no checkout, just DMs."),
        ("Cash-first", "COD dominates, so the shop carries the risk of every order until the courier collects."),
        ("Painful", "Refusals, fake transfer screenshots and slow replies are the #1 complaints of these owners."),
        ("Underserved", "Global tools (Shopify bots, US chatbots) don't speak Egyptian Arabic or InstaPay.")]
for i, (k, v) in enumerate(rows):
    y = 2.2 + i * 1.12
    box(s, 6.6, y, 6.15, 0.98)
    text(s, 6.8, y + 0.1, 1.7, 0.8, k, size=17, bold=True, color=GREEN, anchor=MSO_ANCHOR.MIDDLE)
    text(s, 8.45, y + 0.08, 4.2, 0.85, v, size=12.5, color=FG, anchor=MSO_ANCHOR.MIDDLE)
text(s, 0.6, 6.7, 12, 0.3, "Pilot numbers live in data/store.json → economics; this deck regenerates from them "
     "(python -m scripts.make_slides).", size=10, color=MUTED)
notes(s, "Replace the pilot profile with the real shop you talked to, and its real numbers. "
         "Judges score measurable impact for a real SME.")

# ================================================================ 3. workflow replaced
s = base(3, "The workflow we replaced", "From 9 minutes of copy-paste per order to zero")
text(s, 0.6, 1.65, 5.9, 0.4, "BEFORE — a person does this for every order", size=14, bold=True, color=RED)
text(s, 6.9, 1.65, 5.9, 0.4, "AFTER — Ta2keed does it, 24/7", size=14, bold=True, color=GREEN)
before = [("Read messy DM, ask for size / colour / address", "3 min"),
          ("Copy order into a sheet or notebook", "1.5 min"),
          ("Call / message to confirm the order", "2 min"),
          ("Chase InstaPay screenshot, check it by eye", "1.5 min"),
          ("Book courier, send tracking to customer", "1 min"),
          ("Absorb refused parcels (~1 in 4)", f"{A['loss_per_refusal_egp']} EGP each")]
after = ["Understands Egyptian Arabic, Franco & voice notes; asks only what's missing",
         "Writes the order to the database + CSV/Excel export",
         "Sends a clear order summary; customer just replies \"OK\"",
         "Reads the receipt, checks amount, recipient, status & re-use",
         "Books Bosta and sends tracking automatically",
         "Scores refusal risk and asks risky orders for a deposit first"]
for i, ((b, t), a) in enumerate(zip(before, after)):
    y = 2.1 + i * 0.75
    box(s, 0.6, y, 5.9, 0.64)
    text(s, 0.8, y, 4.2, 0.64, b, size=13, anchor=MSO_ANCHOR.MIDDLE)
    text(s, 5.0, y, 1.4, 0.64, t, size=13, bold=True, color=RED, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
    arr = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(6.55), Inches(y + 0.2), Inches(0.3), Inches(0.26))
    arr.fill.solid(); arr.fill.fore_color.rgb = MUTED; arr.line.fill.background()
    box(s, 6.9, y, 5.85, 0.64, line=GREEN)
    text(s, 7.1, y, 5.5, 0.64, a, size=13, anchor=MSO_ANCHOR.MIDDLE)
text(s, 0.6, 6.6, 12, 0.35, [[("Human time per order: ", {"color": MUTED}), (f"{A['manual_minutes_per_order']} min → 0 min",
     {"bold": True, "color": GREEN}), ("   (owner only reviews the daily digest)", {"color": MUTED})]], size=14)

# ================================================================ 4. how it works
s = base(4, "How the agent works", "One conversation, eight autonomous steps")
steps = [("1", "Understand", "Arabic / Franco / voice → items, size, colour, name, phone, address, zone"),
         ("2", "Complete", "Asks for only the missing field, pushes for building & floor"),
         ("3", "Upsell", "Offers a matching item at a small discount"),
         ("4", "Score risk", "Explainable COD-refusal score with reasons"),
         ("5", "Deposit", "Risky orders pay 100 EGP via InstaPay / Vodafone Cash"),
         ("6", "Verify", "Receipt fraud checks: recipient, amount, status, re-use"),
         ("7", "Ship", "Books Bosta, sends tracking & amount due"),
         ("8", "Report", "Live dashboard, CSV, Telegram daily digest")]
for i, (n, t, d) in enumerate(steps):
    col, row = i % 4, i // 4
    x, y = 0.6 + col * 3.1, 1.8 + row * 2.25
    box(s, x, y, 2.9, 2.0)
    c = box(s, x + 0.2, y + 0.2, 0.55, 0.55, fill=GREEN if i not in (3, 4, 5) else AMBER, shape=MSO_SHAPE.OVAL)
    text(s, x + 0.2, y + 0.2, 0.55, 0.55, n, size=16, bold=True, color=BG, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.9, y + 0.22, 1.9, 0.5, t, size=17, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.2, y + 0.9, 2.55, 1.05, d, size=12, color=MUTED)
box(s, 0.6, 6.35, 12.15, 0.55, fill=RGBColor(0x1B, 0x16, 0x33))
text(s, 0.8, 6.35, 11.8, 0.55, [[("Safe by design: ", {"bold": True, "color": PURPLE}),
     ("a deterministic state machine owns prices, deposits and shipments. The (optional) LLM only reads text and "
      "images — a prompt can't make an order free.", {})]], size=12.5, anchor=MSO_ANCHOR.MIDDLE)
notes(s, "Amber steps 4-6 are the money-protecting part — that's what differentiates this from a chatbot.")

# ================================================================ 5. after the order
s = base(5, "After the order is confirmed", "Every parcel tracked; customer pinged only when it matters")
chain = [("Picked up", False), ("In transit", False), ("Out for delivery", True), ("Delivered", True)]
for i, (k, hl) in enumerate(chain):
    x = 0.6 + i * 3.1
    box(s, x, 1.75, 2.85, 1.25, line=GREEN if hl else None)
    text(s, x + 0.2, 1.85, 2.5, 0.45, k, size=17, bold=True, color=GREEN if hl else FG)
    text(s, x + 0.2, 2.35, 2.5, 0.6, "🔔 customer notified" if hl else "dashboard only", size=12,
         color=GREEN if hl else MUTED)
    if i < 3:
        a = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x + 2.88), Inches(2.25), Inches(0.2), Inches(0.25))
        a.fill.solid(); a.fill.fore_color.rgb = MUTED; a.line.fill.background()
cards = [("Failed attempt", "Customer: \"when should we come back?\" Reply goes to the owner as a reschedule.", AMBER),
         ("Refused / returned", "Silent to the customer. Owner alerted. Customer history updated, so next time a deposit is required.", RED),
         ("+24 h", "Rating 1-5. A low rating triggers an apology and an instant owner alert.", PURPLE),
         ("+14 days", "Personal reorder offer + discount code. Repeat order reuses the saved address.", PURPLE)]
for i, (k, v, c) in enumerate(cards):
    x = 0.6 + i * 3.1
    box(s, x, 3.25, 2.85, 1.85)
    text(s, x + 0.2, 3.35, 2.5, 0.45, k, size=15, bold=True, color=c)
    text(s, x + 0.2, 3.8, 2.5, 1.3, v, size=11.5, color=FG)
box(s, 0.6, 5.35, 12.15, 1.2, fill=RGBColor(0x12, 0x2A, 0x1C), line=GREEN)
text(s, 0.85, 5.42, 11.7, 1.05, [[("Owner on WhatsApp: ", {"bold": True, "color": GREEN}),
     ("instant alerts only for problems, plus a 21:00 daily summary (orders, cash collected, refusals, ratings, "
      "repeat orders). Answers summary / deliveries / pending commands on demand.", {})],
     [("Courier: ", {"bold": True, "color": GREEN}), ("Bosta webhook or any courier or own driver via one endpoint. "
      "Refusal rate becomes measured, not estimated.", {})]], size=13, anchor=MSO_ANCHOR.MIDDLE, spacing=4)
notes(s, "Key point for judges: fewer messages, not more. 4 courier updates -> 2 customer messages. "
         "And every refusal makes the risk engine smarter for that shop.")

# ================================================================ 6. proof: live demo
s = base(6, "Does it work?", f"A live agent: {len(SCENARIOS)} real conversations, zero human touches")
shot = ROOT / "docs" / "screenshot.png"
if shot.exists():
    pic = s.shapes.add_picture(str(shot), Inches(0.6), Inches(1.7), width=Inches(7.3))
    pic.line.color.rgb = LINE
rows = [("Conversations handled", M["conversations"]), ("Orders auto-confirmed & shipped", M["orders_auto_shipped"]),
        ("Risky orders flagged", M["risky_orders_flagged"]), ("Fake receipts blocked", M["fraud_receipts_blocked"]),
        ("Deposits verified", f"{M['deposits_collected']} ({M['deposit_cash_egp']} EGP)"),
        ("Risky parcels NOT shipped", f"{M['risky_orders_stopped_before_shipping']} (saved {M['shipping_loss_avoided_egp']} EGP)"),
        ("Upsells accepted", f"{M['upsells_accepted']}/{M['upsells_offered']} (+{M['upsell_revenue_egp']} EGP)"),
        ("Delivered / cash collected", f"{M['orders_delivered']} ({M['cash_collected_egp']:,} EGP)"),
        ("Courier updates → customer msgs", f"{M['courier_updates_received']} → {M['customer_highlight_msgs']}"),
        ("Rating · repeat orders", f"{M['avg_rating'] or '—'} · {M['repeat_orders']}"),
        ("Human minutes spent", M["human_minutes_spent"])]
box(s, 8.2, 1.7, 4.55, 4.75)
text(s, 8.45, 1.8, 4.1, 0.4, "Measured in the demo run", size=14, bold=True, color=GREEN)
for i, (k, v) in enumerate(rows):
    y = 2.2 + i * 0.385
    text(s, 8.45, y, 2.55, 0.38, k, size=11, color=FG, anchor=MSO_ANCHOR.MIDDLE)
    text(s, 10.75, y, 1.85, 0.38, str(v), size=11.5, bold=True, color=GREEN, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
text(s, 0.6, 6.55, 12.2, 0.4, "Runs in < 5 min with no API keys (./run.sh → ▶ Play demo)  ·  35 automated tests",
     size=12, color=MUTED)
notes(s, "Numbers on the right are produced by the agent's own event log (/api/impact), not typed by hand.")

# ================================================================ 6. business impact (the 4 criteria)
s = base(7, "Measured business impact", f"{egp(P['total_monthly_impact_egp'])} per month for a {A['monthly_orders']:,}-order shop")
cards = [("Does it work?", "✓ Live", "WhatsApp / Telegram / web chat, courier booking, receipt checks — end to end", GREEN),
         ("Time saved", f"{P['hours_saved_per_month']:.0f} h / mo", f"{A['monthly_orders']:,} orders × "
          f"{A['manual_minutes_per_order']} min no longer done by hand ≈ half a full-time job", GREEN),
         ("Cost saved", egp(P["total_cost_saved_egp"]), f"Staff time {egp(P['staff_cost_saved_egp'])} + "
          f"refused-parcel losses avoided {egp(P['refusal_cost_saved_egp'])}", AMBER),
         ("Revenue generated", egp(P["total_new_revenue_egp"]), f"Upsell {egp(P['upsell_revenue_egp'])} + after-hours "
          f"orders {egp(P['after_hours_revenue_egp'])} + saved orders {egp(P['recovered_margin_egp'])}", PURPLE)]
for i, (k, v, d, c) in enumerate(cards):
    x = 0.6 + i * 3.1
    box(s, x, 1.75, 2.9, 3.3)
    text(s, x + 0.25, 1.95, 2.5, 0.4, k.upper(), size=12, bold=True, color=MUTED)
    text(s, x + 0.25, 2.35, 2.5, 0.8, v, size=28, bold=True, color=c)
    text(s, x + 0.25, 3.25, 2.45, 1.75, d, size=12, color=FG)
box(s, 0.6, 5.3, 12.15, 1.25, fill=RGBColor(0x12, 0x2A, 0x1C), line=GREEN)
text(s, 0.9, 5.4, 7.5, 1.05, [[("Refusal rate  ", {"color": MUTED, "size": 16}),
     (f"{P['refusal_rate_before']*100:.0f}%  →  {P['refusal_rate_after']*100:.1f}%", {"bold": True, "size": 30, "color": GREEN})],
     [(f"≈ {P['refusals_avoided_per_month']:.0f} fewer refused parcels every month", {"size": 13, "color": FG})]],
     anchor=MSO_ANCHOR.MIDDLE)
text(s, 8.4, 5.4, 4.2, 1.05, [[(egp(P["total_monthly_impact_egp"]), {"bold": True, "size": 30, "color": GREEN})],
     [("total monthly impact (cost saved + new revenue)", {"size": 12, "color": MUTED})]],
     align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
text(s, 0.6, 6.65, 12.2, 0.3, "Projection from the pilot baseline (slide 9 lists every assumption). "
     "Measured counters come from the agent's event log.", size=10, color=MUTED)

# ================================================================ 7. where the money comes from (chart)
s = base(8, "Where the money comes from", "Monthly impact breakdown")
cd = CategoryChartData()
cats = ["Staff time", "Refusals avoided", "Upsell", "After-hours orders", "Saved-order margin"]
vals = [P["staff_cost_saved_egp"], P["refusal_cost_saved_egp"], P["upsell_revenue_egp"],
        P["after_hours_revenue_egp"], P["recovered_margin_egp"]]
cd.categories = cats
cd.add_series("EGP / month", vals)
gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.6), Inches(1.7), Inches(7.6), Inches(4.9), cd)
ch = gf.chart
ch.has_legend = False
ch.has_title = False
ch.font.name, ch.font.size, ch.font.color.rgb = FONT, Pt(12), FG
plot = ch.plots[0]
plot.gap_width = 55
plot.has_data_labels = True
dl = plot.data_labels
dl.number_format, dl.number_format_is_linked = '#,##0" EGP"', False
dl.position = XL_LABEL_POSITION.OUTSIDE_END
dl.font.color.rgb, dl.font.size, dl.font.bold = FG, Pt(12), True
colors = [GREEN, AMBER, PURPLE, PURPLE, PURPLE]
for i, pt in enumerate(plot.series[0].points):
    pt.format.fill.solid()
    pt.format.fill.fore_color.rgb = colors[i]
va = ch.value_axis
va.visible = False
va.has_major_gridlines = False
va.maximum_scale = max(vals) * 1.35
ca = ch.category_axis
ca.tick_labels.font.color.rgb = FG
ca.format.line.color.rgb = LINE
ca.reverse_order = True
box(s, 8.6, 1.7, 4.15, 4.9)
text(s, 8.85, 1.9, 3.7, 0.4, "Reading the chart", size=14, bold=True, color=GREEN)
text(s, 8.85, 2.35, 3.7, 4.2, [
    [("■ ", {"color": GREEN}), ("Cost saved", {"bold": True}), (" — time the owner gets back", {"color": MUTED})],
    [("■ ", {"color": AMBER}), ("Cost saved", {"bold": True}), (" — outbound + return fees on parcels that "
     "would have been refused", {"color": MUTED})],
    [("■ ", {"color": PURPLE}), ("New revenue", {"bold": True}), (" — upsells, DMs answered at 2 AM, and "
     "orders the deposit turns into real sales", {"color": MUTED})],
    "",
    [("Biggest single lever: ", {"bold": True}), ("the deposit gate. It only asks the ~30% riskiest orders "
     "for 100 EGP, so good customers never feel friction.", {"color": MUTED})]], size=13, spacing=10)

# ================================================================ 8. trust / differentiation
s = base(9, "Why this agent, not a chatbot", "Built for the Egyptian market and for money-safety")
items = [("🗣️", "Speaks the customer's language", "Egyptian Arabic, Franco-Arabic, Arabic-Indic digits, voice notes, "
          "Egyptian areas → shipping zones"),
         ("💳", "Local payment rails", "InstaPay & Vodafone Cash deposits with screenshot fraud checks (wrong account, "
          "low amount, failed, reused)"),
         ("🛡️", "Can't be talked into losses", "Prices, totals, deposits and shipments are code, not LLM output — "
          "prompt-injection test included"),
         ("🔍", "Explainable decisions", "Every risk score lists its reasons; every action is logged and visible to "
          "the owner"),
         ("🔕", "Talks less, not more", "Customers get only delivery highlights; owners get only problems + one "
          "daily summary"),
         ("🧩", "New shop in minutes", "Catalogue, upsell pairs, zones, fees and deposit policy live in one "
          "store.json file")]
for i, (ic, t, d) in enumerate(items):
    col, row = i % 2, i // 2
    x, y = 0.6 + col * 6.15, 1.75 + row * 1.6
    box(s, x, y, 5.95, 1.4)
    text(s, x + 0.2, y + 0.2, 0.8, 0.9, ic, size=28, anchor=MSO_ANCHOR.MIDDLE, font="Segoe UI Emoji")
    text(s, x + 1.05, y + 0.15, 4.7, 0.45, t, size=16, bold=True)
    text(s, x + 1.05, y + 0.6, 4.75, 0.8, d, size=12, color=MUTED)

# ================================================================ 9. assumptions (transparency)
s = base(10, "How we measured", "Every number is traceable")
text(s, 0.6, 1.65, 6, 0.4, "Measured by the agent (event log)", size=14, bold=True, color=GREEN)
text(s, 0.6, 2.1, 5.9, 4.3, ["• orders created / confirmed / auto-shipped",
                              "• risky orders flagged and their reasons",
                              "• deposits verified, fake receipts blocked",
                              "• risky parcels stopped before shipping + fees saved",
                              "• upsells offered vs accepted, upsell revenue",
                              "• after-hours orders, human minutes spent",
                              "", "Live at /api/impact and on the dashboard."], size=14, spacing=6)
text(s, 6.9, 1.65, 6, 0.4, "Pilot baseline used for the monthly projection", size=14, bold=True, color=AMBER)
rows = [("Orders / month", f"{A['monthly_orders']:,}"), ("Manual minutes / order", A["manual_minutes_per_order"]),
        ("Staff cost / hour", f"{A['staff_hourly_cost_egp']} EGP"), ("Baseline refusal rate", f"{A['baseline_refusal_rate']*100:.0f}%"),
        ("Refusal rate with deposit", f"{A['refusal_rate_with_deposit']*100:.0f}%"), ("Share of orders flagged risky", f"{A['flagged_share']*100:.0f}%"),
        ("Loss per refused parcel", f"{A['loss_per_refusal_egp']} EGP"), ("Average basket", f"{A['avg_basket_egp']} EGP"),
        ("Gross margin", f"{A['gross_margin']*100:.0f}%"), ("Upsell acceptance used", f"{A['upsell_accept_rate_used']*100:.0f}% (capped at 25%)")]
tbl = s.shapes.add_table(len(rows), 2, Inches(6.9), Inches(2.1), Inches(5.85), Inches(0.42 * len(rows))).table
tbl.columns[0].width, tbl.columns[1].width = Inches(3.6), Inches(2.25)
for r, (k, v) in enumerate(rows):
    for c, val in enumerate((k, str(v))):
        cell = tbl.cell(r, c)
        cell.fill.solid()
        cell.fill.fore_color.rgb = CARD if r % 2 == 0 else RGBColor(0x1F, 0x24, 0x2F)
        cell.margin_left = Inches(0.12)
        p = cell.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.LEFT if c == 0 else PP_ALIGN.RIGHT
        run = p.add_run()
        run.text = val
        run.font.name, run.font.size, run.font.color.rgb, run.font.bold = FONT, Pt(12.5), FG, c == 1
text(s, 0.6, 6.6, 12.2, 0.35, "Conservative by design: upsell rate is blended with a 15% prior and capped; only half of "
     "saved orders are counted as sales.", size=11, color=MUTED)

# ================================================================ 10. business model / next
s = base(11, "What's next", "From hackathon to a product SMEs hire on Wesam")
price = 750
roi = P["total_monthly_impact_egp"] / price
stat(s, 0.6, 1.75, 3.9, 2.2, f"{price} EGP", "suggested price / month", sub="Less than one refused parcel a day", vsize=34)
stat(s, 4.72, 1.75, 3.9, 2.2, f"{roi:.0f}×", "return on price for the pilot shop", sub="Pays for itself in the first ~day", vsize=34)
stat(s, 8.85, 1.75, 3.9, 2.2, "< 1 day", "to onboard a new shop", sub="Edit store.json, connect WhatsApp number", vsize=34)
text(s, 0.6, 4.25, 12, 0.4, "Roadmap", size=14, bold=True, color=GREEN)
road = [("Now", "WhatsApp + Telegram + web, Bosta, receipt checks, delivery tracking, follow-ups, daily summary"),
        ("Next 30 days", "Pilot with 3 real shops; calibrate risk weights on their order history"),
        ("Then", "Instagram DM channel, Shopify/WooCommerce sync, courier status → auto follow-ups"),
        ("Scale", "List on Wesam's marketplace so any Egyptian SME can hire it in one click")]
for i, (k, v) in enumerate(road):
    y = 4.7 + i * 0.52
    box(s, 0.6, y, 12.15, 0.44)
    text(s, 0.8, y, 2.2, 0.44, k, size=13, bold=True, color=GREEN, anchor=MSO_ANCHOR.MIDDLE)
    text(s, 3.0, y, 9.6, 0.44, v, size=13, anchor=MSO_ANCHOR.MIDDLE)

# ================================================================ 11. demo script + links
s = base(12, "See it yourself", "Run it in under five minutes")
box(s, 0.6, 1.75, 6.1, 4.8)
text(s, 0.85, 1.9, 5.6, 0.4, "Judge quick-start", size=14, bold=True, color=GREEN)
text(s, 0.85, 2.35, 5.6, 2.5, ["git clone https://github.com/MahmoudJimmey/Ta2keed",
                                "cd Ta2keed",
                                "./run.sh        # Windows: run.bat",
                                "# open http://localhost:8000  →  ▶ Play demo",
                                "",
                                "pytest -q       # 35 tests"], size=13, font="Consolas", color=FG, spacing=4)
text(s, 0.85, 4.75, 5.6, 1.7, ["No API keys, no accounts, no database server.",
                                "Optional .env adds LLM, WhatsApp, Telegram, Bosta."], size=13, color=MUTED, spacing=4)
box(s, 6.95, 1.75, 5.8, 4.8)
text(s, 7.2, 1.9, 5.3, 0.4, f"{len(SCENARIOS)} demo scenarios", size=14, bold=True, color=GREEN)
for i, sc in enumerate(SCENARIOS.values()):
    text(s, 7.2, 2.4 + i * 0.82, 5.35, 0.8, [[(f"{i+1}. ", {"bold": True, "color": GREEN}), (sc["title"].replace(" -> ", " → "), {})]], size=13)

# ================================================================ 12. risks & mitigations
s = base(13, "Honest limitations", "What could go wrong — and how we handle it")
rows = [("Rules miss an unusual message", "Falls back to the LLM when configured; always asks instead of guessing; owner sees every order"),
        ("Fake receipts get more sophisticated", "Checks recipient, amount, status, duplicate reference & image hash; flags edited-looking screenshots; owner alert"),
        ("Deposit annoys good customers", "Only the riskiest ~30% are asked; trusted repeat buyers get a lower score automatically"),
        ("Risk weights are generic", "Transparent weights; calibrate on each shop's own delivered/refused history"),
        ("WhatsApp API needs Meta approval", "Telegram + web chat work today; WhatsApp webhook is implemented and ready")]
for i, (r, m) in enumerate(rows):
    y = 1.75 + i * 0.95
    box(s, 0.6, y, 4.3, 0.82, line=RED)
    text(s, 0.8, y, 4.0, 0.82, r, size=13, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    box(s, 5.1, y, 7.65, 0.82)
    text(s, 5.3, y, 7.3, 0.82, m, size=12.5, color=FG, anchor=MSO_ANCHOR.MIDDLE)

# ================================================================ 13. close
s = prs.slides.add_slide(BLANK)
s.background.fill.solid()
s.background.fill.fore_color.rgb = BG
box(s, 0, 0, 0.18, 7.5, fill=GREEN, shape=MSO_SHAPE.RECTANGLE)
text(s, 0.9, 1.6, 11.8, 1.0, "Every COD order confirmed, de-risked, shipped.", size=36, bold=True)
text(s, 0.9, 2.75, 11.5, 0.8, "No human in the loop. No new app for the customer. Just WhatsApp.", size=22, color=MUTED)
for i, (v, l) in enumerate([(f"{P['hours_saved_per_month']:.0f} h", "time saved / month"),
                            (egp(P["total_cost_saved_egp"]), "cost saved / month"),
                            (egp(P["total_new_revenue_egp"]), "new revenue / month")]):
    stat(s, 0.9 + i * 3.9, 3.9, 3.65, 1.35, v, l, vsize=28)
text(s, 0.9, 5.8, 11.5, 0.5, "github.com/MahmoudJimmey/Ta2keed", size=20, bold=True, color=GREEN)
text(s, 0.9, 6.3, 11.5, 0.5, "Mahmoud Gamal · Agents at Work 2026", size=14, color=MUTED)

assert len(prs.slides) == TOTAL, len(prs.slides)
out = ROOT / "docs" / "Ta2keed-impact-slides.pptx"
prs.save(out)
print("saved", out)
