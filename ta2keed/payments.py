"""Deposit verification for InstaPay / Vodafone Cash screenshots.

Checks: is it a receipt, amount >= deposit, recipient matches the shop, transaction status,
reference never used before, same image never submitted before (screenshot re-use fraud).
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import time
import zlib

from . import db, llm, nlu
from .config import store


def png_text_chunks(data: bytes) -> dict:
    """Read tEXt metadata from a PNG (used by the offline demo receipts)."""
    out = {}
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return out
    i = 8
    while i + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[i:i + 8])
        chunk = data[i + 8:i + 8 + length]
        if ctype == b"tEXt" and b"\x00" in chunk:
            k, v = chunk.split(b"\x00", 1)
            out[k.decode("latin-1")] = v.decode("utf-8", "replace")
        elif ctype == b"zTXt" and b"\x00" in chunk:
            k, rest = chunk.split(b"\x00", 1)
            out[k.decode("latin-1")] = zlib.decompress(rest[1:]).decode("utf-8", "replace")
        if ctype == b"IEND":
            break
        i += 12 + length
    return out


def read_image(image: bytes, mime: str) -> dict:
    info = llm.read_receipt(image, mime)
    if info and not info.get("_error") and info.get("is_receipt") is not None:
        info["_source"] = "vision-llm"
        return info
    meta = png_text_chunks(image)
    if "receipt" in meta:  # offline demo receipts carry their fields as PNG metadata
        try:
            d = json.loads(meta["receipt"])
            d["_source"] = "demo-metadata"
            return d
        except json.JSONDecodeError:
            pass
    return {"_source": "unreadable"}


def verify(order: dict, *, image: bytes | None = None, mime: str = "image/png", text: str | None = None) -> dict:
    policy = store()["policy"]
    need = policy["deposit_amount"]
    image_hash = hashlib.sha256(image).hexdigest() if image else None

    if image:
        info = read_image(image, mime)
    else:
        info = nlu.extract_receipt_text(text or "")
        info["_source"] = "text"
        info["is_receipt"] = bool(info.get("reference"))

    result = {"ok": False, "reason": None, "info": info, "fraud": False}

    def done(ok: bool, reason: str | None, fraud: bool = False):
        result.update(ok=ok, reason=reason, fraud=fraud)
        result["payment_id"] = db.x(
            "INSERT INTO payments(order_id,reference,amount,image_hash,status,reason,raw,ts) VALUES(?,?,?,?,?,?,?,?)",
            (order["id"], info.get("reference"), info.get("amount"), image_hash,
             "verified" if ok else ("fraud" if fraud else "rejected"), reason,
             json.dumps(info, ensure_ascii=False), time.time()))
        return result

    # a screenshot/reference already used (verified OR waiting for the owner) can never pay a second order
    USED = "status IN ('verified','pending_owner')"
    if image_hash and db.one(f"SELECT id FROM payments WHERE image_hash=? AND {USED}", (image_hash,)):
        return done(False, "duplicate_screenshot", fraud=True)
    if info.get("_source") == "unreadable" or info.get("is_receipt") is False:
        return done(False, "not_a_receipt")
    if str(info.get("status", "success")).lower() not in ("success", "successful", "completed", "تمت", "ناجحة"):
        return done(False, "transaction_not_successful")
    if info.get("edited_suspicion") == "high":
        return done(False, "looks_edited", fraud=True)

    ref = re.sub(r"\D", "", str(info.get("reference") or ""))
    if not ref:
        return done(False, "missing_reference")
    if db.one(f"SELECT id FROM payments WHERE reference=? AND {USED}", (ref,)):
        return done(False, "reference_already_used", fraud=True)
    info["reference"] = ref

    try:
        amount = float(info.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount < need:
        return done(False, f"amount_too_low:{amount:g}")

    recipient = nlu.normalize(str(info.get("recipient") or ""))
    handle = nlu.normalize(policy["instapay_handle"])
    vf = re.sub(r"\D", "", policy["vodafone_cash"])
    if recipient and handle.split("@")[0] not in recipient and vf not in re.sub(r"\D", "", recipient) \
            and nlu.normalize(store()["store"]["name"]) not in recipient:
        return done(False, "wrong_recipient", fraud=True)

    return done(True, None)
