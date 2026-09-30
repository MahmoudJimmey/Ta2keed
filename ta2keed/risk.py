"""COD refusal-risk scoring.

Transparent, explainable weights (judges and shop owners can read every reason).
Calibrate against the SME's own history with `scripts/calibrate.py` later.
"""
from __future__ import annotations

import datetime as dt

from . import db, nlu
from .config import store


def score(draft: dict, total: int, conv_id: int | None = None) -> tuple[float, list[str]]:
    s = store()
    reasons: list[str] = []
    risk = 0.10  # base COD refusal prior

    cust = db.customer(draft.get("phone"))
    if cust:
        done = cust["delivered"] + cust["refused"]
        if cust["refused"] and done:
            r = cust["refused"] / done
            risk += 0.6 * r
            reasons.append(f"refused {cust['refused']} of {done} past orders")
        if cust["delivered"] >= 3 and cust["refused"] == 0:
            risk -= 0.25
            reasons.append(f"trusted repeat customer ({cust['delivered']} delivered)")
    else:
        risk += 0.15
        reasons.append("first-time customer")

    if nlu.address_is_vague(draft.get("address")):
        risk += 0.20
        reasons.append("vague address (no building/floor/number)")

    if draft.get("zone") == "upper":
        risk += 0.08
        reasons.append("long-haul zone (higher return cost)")

    if total >= s["policy"]["high_value_order_egp"]:
        risk += 0.15
        reasons.append(f"high order value ({total} EGP)")

    if draft.get("hesitation"):
        risk += 0.15
        reasons.append("customer sounded unsure")

    if draft.get("edits", 0) >= 3:
        risk += 0.05
        reasons.append("changed the order several times")

    hour = dt.datetime.now().hour
    if 1 <= hour < 6:
        risk += 0.05
        reasons.append("ordered between 1-6 AM")

    return round(max(0.0, min(1.0, risk)), 2), reasons


def needs_deposit(risk: float, total: int) -> bool:
    p = store()["policy"]
    return risk >= p["risk_deposit_threshold"] or total >= p["high_value_order_egp"]
