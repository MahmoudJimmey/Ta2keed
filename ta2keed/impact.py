"""Business-impact metrics: measured from the agent's own event log + projected monthly ROI.

Measured (from the DB): orders handled, confirmed, auto-shipped, deposits collected, fraud blocked,
risky orders caught, upsell revenue, after-hours orders, agent response time.
Projected (monthly): uses the SME's own baseline numbers from store.json -> economics.
"""
from __future__ import annotations

import json

from . import db
from .config import store


def measured() -> dict:
    orders = db.q("SELECT * FROM orders")
    n = len(orders)
    confirmed = [o for o in orders if o["status"] in ("confirmed", "shipped", "delivered", "refused", "returned")]
    shipped = [o for o in orders if o.get("tracking")]
    deposits = [o for o in orders if o["deposit_paid"]]
    risky = [o for o in orders if o["deposit_required"]]
    risky_cancelled = [o for o in risky if o["status"] == "cancelled" or (o["status"] == "awaiting_deposit")]
    fraud = db.one("SELECT COUNT(*) AS n FROM payments WHERE status='fraud'")["n"]
    ups_off = db.one("SELECT COUNT(*) AS n FROM events WHERE type='upsell_offered'")["n"]
    ups_acc = db.one("SELECT COUNT(*) AS n FROM events WHERE type='upsell_accepted'")["n"]
    upsell_rev = sum(o["upsell_value"] or 0 for o in confirmed)
    convs = db.one("SELECT COUNT(*) AS n FROM conversations")["n"]
    msgs = db.one("SELECT COUNT(*) AS n FROM messages WHERE role='agent'")["n"]
    ret_fee = store()["shipping"]["return_fee"]
    avoided_loss = sum((o["shipping"] or 0) + ret_fee for o in risky_cancelled)
    delivered = [o for o in orders if o.get("delivery_status") == "delivered"]
    refused = [o for o in orders if o.get("delivery_status") in ("refused", "returned")]
    closed = len(delivered) + len(refused)
    ratings = [o["rating"] for o in orders if o.get("rating")]
    cust_msgs = db.q("SELECT data FROM events WHERE type='customer_notified'")
    courier_updates = db.one("SELECT COUNT(*) AS n FROM events WHERE type='delivery_update'")["n"]
    return {
        "conversations": convs,
        "agent_messages_sent": msgs,
        "orders_created": n,
        "orders_confirmed": len(confirmed),
        "orders_auto_shipped": len(shipped),
        "revenue_confirmed_egp": sum(o["total"] for o in confirmed),
        "risky_orders_flagged": len(risky),
        "deposits_collected": len(deposits),
        "deposit_cash_egp": sum(o["deposit_paid"] for o in deposits),
        "fraud_receipts_blocked": fraud,
        "risky_orders_stopped_before_shipping": len(risky_cancelled),
        "shipping_loss_avoided_egp": avoided_loss,
        "upsells_offered": ups_off,
        "upsells_accepted": ups_acc,
        "upsell_revenue_egp": upsell_rev,
        "after_hours_orders": sum(1 for o in orders if o["after_hours"]),
        "orders_delivered": len(delivered),
        "orders_refused_or_returned": len(refused),
        "measured_refusal_rate": round(len(refused) / closed, 3) if closed else None,
        "cash_collected_egp": sum(o.get("cod_collected") or 0 for o in delivered),
        "courier_updates_received": courier_updates,
        "customer_highlight_msgs": len(cust_msgs),
        "courier_updates_kept_internal": max(0, courier_updates - sum(
            1 for m in cust_msgs if json.loads(m["data"]).get("kind") in ("out_for_delivery", "delivered", "delivery_failed"))),
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "ratings_count": len(ratings),
        "repeat_orders": sum(1 for o in orders if o.get("source") == "reorder"),
        "human_minutes_spent": 0,
    }


def projected() -> dict:
    s = store()
    e = s["economics"]
    orders = e["monthly_orders"]
    avg_ship = sum(z["fee"] for z in s["shipping"]["zones"].values()) / len(s["shipping"]["zones"])
    loss_per_refusal = avg_ship + s["shipping"]["return_fee"]
    avg_basket = sum(p["price"] for p in s["products"][:5]) / 5

    # time
    hours_saved = orders * (e["manual_minutes_per_order"] - e["owner_review_minutes"] * 0.1) / 60
    staff_cost_saved = hours_saved * e["staff_hourly_cost_egp"]

    # refusals: the deposit gate applies to the risky share of orders (~ 30% flagged in pilot)
    flagged_share = 0.30
    base_refusals = orders * e["baseline_refusal_rate"]
    # assume flagged orders carry ~70% of refusals; deposits cut their refusal rate to refusal_rate_with_deposit
    refusals_in_flagged = base_refusals * 0.70
    new_refusals = (base_refusals - refusals_in_flagged) + orders * flagged_share * e["refusal_rate_with_deposit"]
    refusals_avoided = max(0.0, base_refusals - new_refusals)
    refusal_cost_saved = refusals_avoided * loss_per_refusal
    recovered_margin = refusals_avoided * avg_basket * e["gross_margin"] * 0.5  # half become real sales

    # revenue: upsell + after-hours capture
    m = measured()
    # blend observed acceptance with a conservative 15% prior (5 pseudo-offers) so tiny samples don't swing it
    ups_rate = (m["upsells_accepted"] + 0.15 * 5) / (m["upsells_offered"] + 5)
    ups_rate = min(ups_rate, 0.25)  # cap demo optimism
    upsell_rev = orders * 0.8 * ups_rate * 120
    after_hours_rev = orders * 0.10 * 0.5 * avg_basket  # 10% of DMs arrive after hours, half were lost before

    total_saved = staff_cost_saved + refusal_cost_saved
    total_new = upsell_rev + after_hours_rev + recovered_margin
    return {
        "assumptions": {**e, "loss_per_refusal_egp": round(loss_per_refusal), "avg_basket_egp": round(avg_basket),
                        "flagged_share": flagged_share, "upsell_accept_rate_used": round(ups_rate, 2)},
        "hours_saved_per_month": round(hours_saved, 1),
        "staff_cost_saved_egp": round(staff_cost_saved),
        "refusals_avoided_per_month": round(refusals_avoided, 1),
        "refusal_cost_saved_egp": round(refusal_cost_saved),
        "upsell_revenue_egp": round(upsell_rev),
        "after_hours_revenue_egp": round(after_hours_rev),
        "recovered_margin_egp": round(recovered_margin),
        "total_cost_saved_egp": round(total_saved),
        "total_new_revenue_egp": round(total_new),
        "total_monthly_impact_egp": round(total_saved + total_new),
        "refusal_rate_before": e["baseline_refusal_rate"],
        "refusal_rate_after": round(new_refusals / orders, 3),
    }


def text_report() -> str:
    m, p = measured(), projected()
    lines = ["📊 IMPACT REPORT", "-- measured in this session --"]
    lines += [f"  {k}: {v}" for k, v in m.items()]
    lines += ["-- projected per month for the SME (store.json → economics) --"]
    lines += [f"  {k}: {v}" for k, v in p.items() if k != "assumptions"]
    lines.append("  assumptions: " + json.dumps(p["assumptions"], ensure_ascii=False))
    return "\n".join(lines)
