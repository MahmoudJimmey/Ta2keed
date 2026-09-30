"""Courier booking. Real Bosta API when BOSTA_API_KEY is set, otherwise a local mock
that behaves the same (tracking number, fee, ETA) so the demo runs with zero accounts."""
from __future__ import annotations

import random

import httpx

from .config import settings, store

BOSTA_URL = "https://app.bosta.co/api/v2/deliveries"


def create_shipment(order: dict) -> dict:
    if settings.bosta_api_key:
        name = (order.get("customer_name") or "Customer").split()
        body = {
            "type": 10,  # SEND / forward delivery
            "specs": {"packageDetails": {"itemsCount": sum(i["qty"] for i in order["items"]),
                                         "description": ", ".join(i["name"] for i in order["items"])}},
            "cod": order["total"] - order.get("deposit_paid", 0),
            "dropOffAddress": {"firstLine": order["address"], "city": order.get("zone", "cairo").title()},
            "receiver": {"firstName": name[0], "lastName": " ".join(name[1:]) or "-",
                         "phone": order["customer_phone"]},
            "businessReference": order["id"],
        }
        r = httpx.post(BOSTA_URL, headers={"Authorization": settings.bosta_api_key}, json=body, timeout=30)
        r.raise_for_status()
        d = r.json().get("data", {})
        return {"courier": "bosta", "tracking": str(d.get("trackingNumber") or d.get("_id")), "live": True}

    rng = random.Random(order["id"])
    return {"courier": "bosta (mock)", "tracking": f"BST{rng.randint(10**8, 10**9 - 1)}",
            "eta_days": store()["policy"]["delivery_days"], "live": False}
