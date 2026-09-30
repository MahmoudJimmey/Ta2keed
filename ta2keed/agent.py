"""Ta2keed agent: turns a messy DM into a confirmed, de-risked, shipped COD order.

Design: a deterministic state machine owns every business action (price, risk, deposit,
shipment). Language understanding is rules-first with an optional LLM on top. That makes
it cheap (works with no API key), auditable, and impossible for a prompt to give free stuff.

States: COLLECTING -> UPSELL -> CONFIRM -> (DEPOSIT) -> CONFIRMED | CANCELLED
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time

from . import courier, db, llm, nlu, payments, risk
from .config import product, store

QUESTION_HINTS = ["بكام", "كام", "سعر", "امتي", "امتى", "فين", "ازاي", "هل", "ينفع", "متاح", "موجود",
                  "بتوصلو", "how much", "price", "ايه الالوان", "ايه المقاسات", "الوانها", "مقاساتها"]
ORDER_INTENT = ["عايزه", "عايز", "عاوزه", "عاوز", "هاخد", "اطلب", "خلاص", "ابعتيلي", "ابعتلي", "محتاجه", "3ayza", "3ayez"]


def fmt(n: float) -> str:
    return f"{int(n):,}"


# ------------------------------------------------------------------ helpers

def _items_view(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        p = product(it["sku"])
        if not p:
            continue
        price = it.get("price", p["price"])
        out.append({**it, "name": p["name_ar"], "price": price, "line": price * it["qty"]})
    return out


def _totals(draft: dict) -> tuple[int, int, int]:
    items = _items_view(draft.get("items", []))
    sub = sum(i["line"] for i in items)
    zone = draft.get("zone")
    ship = store()["shipping"]["zones"].get(zone, {}).get("fee", 0) if zone else 0
    return sub, ship, sub + ship


def _merge(draft: dict, new: dict) -> None:
    if new.get("items"):
        existing = {i["sku"]: i for i in draft.get("items", [])}
        for it in new["items"]:
            if not product(it.get("sku", "")):
                continue
            cur = existing.get(it["sku"])
            if cur:
                for k in ("size", "color"):
                    if it.get(k):
                        cur[k] = it[k]
                if it.get("qty") and it["qty"] != 1:
                    cur["qty"] = it["qty"]
            else:
                existing[it["sku"]] = {"sku": it["sku"], "qty": int(it.get("qty") or 1),
                                       "size": it.get("size"), "color": it.get("color")}
                if draft.get("items"):
                    draft["edits"] = draft.get("edits", 0) + 1
        draft["items"] = list(existing.values())
    for k in ("name", "phone", "zone"):
        if new.get(k) and not draft.get(k):
            draft[k] = new[k]
    if new.get("address"):
        if draft.get("address") and draft.get("awaiting") == "address_detail":
            if nlu.normalize(new["address"]) not in nlu.normalize(draft["address"]):
                draft["address"] = f"{draft['address']} - {new['address']}"
        elif not draft.get("address") or len(new["address"]) > len(draft["address"]):
            draft["address"] = new["address"]
    if new.get("address") and not draft.get("zone"):
        z = nlu.find_zone(new["address"])
        if z:
            draft["zone"] = z


def _apply_size_color(draft: dict, sc: dict) -> None:
    for it in draft.get("items", []):
        p = product(it["sku"])
        if sc.get("size") and p["sizes"] and not it.get("size") and sc["size"] in p["sizes"]:
            it["size"] = sc["size"]
            sc = {**sc, "size": None}
        if sc.get("color") and p["colors"] and not it.get("color") and sc["color"] in p["colors"]:
            it["color"] = sc["color"]
            sc = {**sc, "color": None}


def _missing(draft: dict) -> str | None:
    if not draft.get("items"):
        return "items"
    for it in draft["items"]:
        p = product(it["sku"])
        if p["sizes"] and not it.get("size"):
            return f"size:{it['sku']}"
        if p["colors"] and not it.get("color"):
            return f"color:{it['sku']}"
    if not draft.get("name"):
        return "name"
    if not draft.get("phone"):
        return "phone"
    if not draft.get("address"):
        return "address"
    if not draft.get("zone"):
        return "zone"
    if nlu.address_is_vague(draft["address"]) and not draft.get("address_detail_asked"):
        return "address_detail"
    return None


def _ask(slot: str, draft: dict) -> str:
    if slot == "items":
        names = "، ".join(f"{p['name_ar']} ({p['price']} ج)" for p in store()["products"][:5])
        return f"أهلاً بيكي في {store()['store']['name_ar']} 🌸 تحبي تطلبي إيه؟ عندنا: {names}"
    if slot.startswith("size:"):
        p = product(slot.split(":")[1])
        return f"{p['name_ar']} متاح مقاسات {' / '.join(p['sizes'])} — تحبي أنهي مقاس؟"
    if slot.startswith("color:"):
        p = product(slot.split(":")[1])
        return f"وتحبي {p['name_ar']} بأنهي لون؟ ({' / '.join(nlu.COLOR_AR.get(c, c) for c in p['colors'])})"
    if slot == "name":
        return "تمام ✨ ممكن الاسم بالكامل للمستلم؟"
    if slot == "phone":
        return "ورقم موبايل المستلم؟ (مندوب الشحن هيكلمه عليه)"
    if slot == "address":
        return "والعنوان بالتفصيل؟ (المحافظة/المنطقة، الشارع، رقم العمارة، الدور والشقة)"
    if slot == "zone":
        return "العنوان ده في أنهي محافظة/منطقة؟"
    if slot == "address_detail":
        return "علشان المندوب يوصل من أول مرة 🙏 ممكن رقم العمارة والدور والشقة أو علامة مميزة جنبك؟"
    return ""


def _summary(draft: dict) -> str:
    items = _items_view(draft["items"])
    sub, ship, total = _totals(draft)
    zone_label = store()["shipping"]["zones"].get(draft.get("zone"), {}).get("label_ar", "")
    lines = ["📦 ملخص الأوردر:"]
    for i in items:
        opts = " ".join(x for x in [i.get("size") or "", nlu.COLOR_AR.get(i.get("color") or "", "")] if x)
        lines.append(f"• {i['qty']}× {i['name']} {opts} — {fmt(i['line'])} ج")
    lines += [f"الشحن ({zone_label}): {fmt(ship)} ج", f"الإجمالي: {fmt(total)} ج (الدفع عند الاستلام)",
              f"👤 {draft['name']} — 📱 {draft['phone']}", f"📍 {draft['address']}",
              "", "أأكد الأوردر؟ (رد بـ تمام للتأكيد أو قولي عايزة تعدلي إيه)"]
    return "\n".join(lines)


def _upsell_offer(draft: dict) -> dict | None:
    have = {i["sku"] for i in draft["items"]}
    for it in draft["items"]:
        up = (product(it["sku"]) or {}).get("upsell")
        if up and up["sku"] not in have:
            p = product(up["sku"])
            return {"sku": up["sku"], "price": up["price"], "name": p["name_ar"], "list": p["price"], "for": it["sku"]}
    return None


def _is_question(text: str) -> bool:
    t = nlu.normalize(text)
    if "?" in t or "؟" in t:
        return True
    if nlu._has(t, ORDER_INTENT):
        return False
    return nlu._has(t, QUESTION_HINTS, prefix=True)


def _rule_answer(text: str) -> str | None:
    t = nlu.normalize(text)
    s = store()
    if any(w in t for w in ["شحن", "توصيل", "بتوصلو", "shipping"]):
        fees = "، ".join(f"{z['label_ar']} {z['fee']} ج" for z in s["shipping"]["zones"].values())
        return f"الشحن لكل مصر خلال {s['policy']['delivery_days']} أيام — {fees}. والدفع عند الاستلام 👌"
    if any(w in t for w in ["استبدال", "استرجاع", "ترجيع"]):
        return "الاستبدال متاح خلال 14 يوم لو المنتج بحالته، وبتدفعي مصاريف الشحن بس."
    items = nlu.extract_items(t)
    if items:
        p = product(items[0]["sku"])
        extra = f" — المقاسات: {' / '.join(p['sizes'])}" if p["sizes"] else ""
        colors = f" — الألوان: {' / '.join(nlu.COLOR_AR.get(c, c) for c in p['colors'])}" if p["colors"] else ""
        return f"{p['name_ar']} بـ {p['price']} ج{extra}{colors} ✨"
    return None


def _after_hours() -> bool:
    start, end = store()["store"]["business_hours"]
    return not (start <= dt.datetime.now().hour < end)


# ------------------------------------------------------------------ order creation

def _create_order(conv: dict) -> dict:
    d = conv["draft"]
    sub, ship, total = _totals(d)
    score, reasons = risk.score(d, total, conv["id"])
    dep = risk.needs_deposit(score, total)
    oid = db.next_order_id()
    items = _items_view(d["items"])
    upsell_value = sum(i["line"] for i in items if i.get("upsell"))
    now = time.time()
    db.x("""INSERT INTO orders(id,conv_id,customer_phone,customer_name,address,zone,items,subtotal,shipping,total,
            upsell_value,risk_score,risk_reasons,deposit_required,status,after_hours,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
         (oid, conv["id"], d["phone"], d["name"], d["address"], d.get("zone"),
          json.dumps(items, ensure_ascii=False), sub, ship, total, upsell_value, score,
          json.dumps(reasons, ensure_ascii=False), int(dep), "awaiting_deposit" if dep else "confirmed",
          int(_after_hours()), now, now))
    if not db.customer(d["phone"]):
        db.x("INSERT INTO customers(phone,name,created_at) VALUES(?,?,?)", (d["phone"], d["name"], now))
    db.log_event(conv["id"], "order_created", {"total": total, "risk": score, "reasons": reasons,
                                                "deposit_required": dep}, oid)
    conv["order_id"] = oid
    return db.one("SELECT * FROM orders WHERE id=?", (oid,))


def _ship(order: dict, conv_id: int) -> dict:
    o = {**order, "items": json.loads(order["items"]) if isinstance(order["items"], str) else order["items"]}
    shipment = courier.create_shipment(o)
    db.x("UPDATE orders SET status='shipped', tracking=?, updated_at=? WHERE id=?",
         (shipment["tracking"], time.time(), order["id"]))
    db.log_event(conv_id, "shipment_created", shipment, order["id"])
    return shipment


def _shipped_msg(order: dict, shipment: dict) -> str:
    cod = order["total"] - (order.get("deposit_paid") or 0)
    return (f"✅ تم تأكيد الأوردر رقم {order['id']}!\n"
            f"رقم الشحنة: {shipment['tracking']} — هيوصلك خلال {store()['policy']['delivery_days']} أيام.\n"
            f"المطلوب عند الاستلام: {fmt(cod)} ج. شكراً لثقتك في {store()['store']['name_ar']} 💕")


# ------------------------------------------------------------------ main entry

def handle(channel: str, user_id: str, text: str = "", *, image: bytes | None = None,
           image_mime: str = "image/png", audio: bytes | None = None, audio_name: str = "voice.ogg") -> list[str]:
    conv = db.get_conversation(channel, user_id)
    d = conv["draft"]
    meta = {}

    if audio is not None:
        heard = llm.transcribe(audio, audio_name)
        if not heard:
            db.add_message(conv["id"], "user", "[voice note]", {"voice": True})
            return _reply(conv, ["معلش مقدرتش أسمع الفويس كويس 🙏 ممكن تكتبيلي الطلب؟"])
        text = heard
        meta["voice_transcript"] = True
        db.log_event(conv["id"], "voice_transcribed", {"text": heard})

    db.add_message(conv["id"], "user", text or ("[image]" if image else ""), {**meta, "image": bool(image)})

    if channel == "whatsapp" and not d.get("phone"):
        m = re.search(r"(01[0125]\d{8})$", re.sub(r"\D", "", user_id))
        if m:
            d["phone_hint"] = m.group(1)

    state = conv["state"]

    # finished conversations: status check or start a new order
    if state in ("CONFIRMED", "CANCELLED"):
        if conv.get("order_id") and any(w in nlu.normalize(text) for w in ["فين", "امتي", "امتى", "الاوردر", "الشحنه", "status", "tracking"]):
            o = db.one("SELECT * FROM orders WHERE id=?", (conv["order_id"],))
            if o:
                return _reply(conv, [f"أوردرك {o['id']} حالته: {o['status']} — رقم الشحنة {o['tracking'] or '—'} 🚚"])
        conv["state"], conv["draft"], conv["order_id"] = "COLLECTING", {}, None
        d = conv["draft"]
        state = "COLLECTING"

    if text and nlu.is_cancel(text) and state != "NEW":
        if conv.get("order_id"):
            db.x("UPDATE orders SET status='cancelled', updated_at=? WHERE id=?", (time.time(), conv["order_id"]))
        conv["state"] = "CANCELLED"
        db.log_event(conv["id"], "cancelled", {"stage": state}, conv.get("order_id"))
        return _reply(conv, ["تم إلغاء الطلب 👍 لو حبيتي تطلبي تاني في أي وقت ابعتيلي."])

    if text and nlu.hesitation(text):
        d["hesitation"] = True

    # ---------------- deposit stage
    if state == "DEPOSIT":
        order = db.one("SELECT * FROM orders WHERE id=?", (conv["order_id"],))
        if image is not None or nlu.extract_receipt_text(text).get("reference"):
            res = payments.verify(order, image=image, mime=image_mime, text=None if image else text)
            db.log_event(conv["id"], "deposit_checked", {k: res[k] for k in ("ok", "reason", "fraud")}, order["id"])
            if res["ok"]:
                amt = int(float(res["info"].get("amount") or store()["policy"]["deposit_amount"]))
                db.x("UPDATE orders SET deposit_paid=?, status='confirmed' WHERE id=?", (amt, order["id"]))
                order = db.one("SELECT * FROM orders WHERE id=?", (order["id"],))
                shipment = _ship(order, conv["id"])
                conv["state"] = "CONFIRMED"
                return _reply(conv, [f"وصلني التحويل ✅ ({fmt(amt)} ج) — شكراً!", _shipped_msg(order, shipment)])
            return _reply(conv, [_deposit_rejection(res)])
        if text and nlu.is_no(text):
            return _reply(conv, ["للأسف العربون مطلوب للأوردر ده علشان نقدر نشحنه 🙏 "
                                 "لو تحبي نلغيه قولي «إلغاء»، أو ابعتي صورة التحويل أول ما تحوّلي."])
        return _reply(conv, [_deposit_request(order)])

    # ---------------- understanding
    extracted = nlu.rule_extract(text) if text else {}
    if llm.settings.llm_enabled and text:
        ai = llm.extract(text, d)
        if ai and not ai.get("_error"):
            for k in ("name", "address", "zone"):
                if ai.get(k) and not extracted.get(k):
                    extracted[k] = ai[k]
            if ai.get("items") and not extracted.get("items"):
                extracted["items"] = ai["items"]
            if ai.get("phone") and not extracted.get("phone") and re.fullmatch(r"01[0125]\d{8}", str(ai["phone"])):
                extracted["phone"] = ai["phone"]

    # ---------------- upsell stage
    if text and _is_question(text) and not extracted.get("phone") and state != "UPSELL":
        extracted = {}  # "الطرحة بكام؟" is a question, not an order line / address

    if state == "UPSELL":
        offer = d.get("upsell_offer")
        if offer and (nlu.is_yes(text) or any(i["sku"] == offer["sku"] for i in extracted.get("items", []))):
            d["items"].append({"sku": offer["sku"], "qty": 1, "size": None, "color": None,
                               "price": offer["price"], "upsell": True})
            db.log_event(conv["id"], "upsell_accepted", offer)
            p = product(offer["sku"])
            if p["colors"]:
                conv["state"] = "COLLECTING"
                d["awaiting"] = f"color:{offer['sku']}"
                return _reply(conv, ["اختيار حلو 😍 " + _ask(f"color:{offer['sku']}", d)])
        else:
            db.log_event(conv["id"], "upsell_declined", offer or {})
        d.pop("upsell_offer", None)
        conv["state"] = "CONFIRM"
        return _reply(conv, [_summary(d)])

    # ---------------- confirm stage
    if state == "CONFIRM":
        if nlu.is_yes(text) and not extracted.get("items"):
            order = _create_order(conv)
            if order["deposit_required"]:
                conv["state"] = "DEPOSIT"
                return _reply(conv, [_deposit_request(order)])
            shipment = _ship(order, conv["id"])
            conv["state"] = "CONFIRMED"
            return _reply(conv, [_shipped_msg(order, shipment)])
        if extracted:
            d["edits"] = d.get("edits", 0) + 1
            _merge(d, extracted)
            state = conv["state"] = "COLLECTING"
        elif _is_question(text):
            ans = llm.answer(text, d) or _rule_answer(text) or "هسأل الإدارة وأرد عليكي حالاً 🙏"
            return _reply(conv, [ans, "أأكد الأوردر؟ (تمام للتأكيد)"])
        else:
            return _reply(conv, ["قوليلي عايزة تعدلي إيه (المقاس، اللون، العنوان...) أو رد بـ «تمام» للتأكيد 🙏"])

    # ---------------- collecting
    conv["state"] = "COLLECTING"
    awaiting = d.get("awaiting")
    had_info = bool(extracted)
    _merge(d, extracted)

    if text and awaiting:
        t = nlu.normalize(text)
        if awaiting.startswith(("size:", "color:")):
            sc = nlu.extract_size_color(t)
            sku = awaiting.split(":")[1]
            for it in d.get("items", []):
                if it["sku"] == sku:
                    p = product(sku)
                    if awaiting.startswith("size:") and sc.get("size") in p["sizes"]:
                        it["size"] = sc["size"]; had_info = True
                    if sc.get("color") in p["colors"]:
                        it["color"] = sc["color"]; had_info = True
            _apply_size_color(d, sc)
        elif awaiting == "name" and not extracted.get("name") and not nlu.PHONE_RE.search(t) and len(text.split()) <= 5 \
                and not _is_question(text) and not nlu.is_yes(text) and not nlu.is_no(text) \
                and re.fullmatch(r"[\u0600-\u06FFa-zA-Z\s]{3,40}", text.strip()):
            d["name"] = text.strip(); had_info = True
        elif awaiting == "phone" and not d.get("phone") and d.get("phone_hint") and nlu.is_yes(text):
            d["phone"] = d["phone_hint"]; had_info = True
        elif awaiting in ("address", "zone") and not extracted.get("address") and len(text) >= 6 and not _is_question(text):
            if awaiting == "address":
                d["address"] = text.strip(); had_info = True
            z = nlu.find_zone(text)
            if z:
                d["zone"] = z; had_info = True
        elif awaiting == "address_detail":
            d["address_detail_asked"] = True
            if not extracted.get("address") and len(text) >= 3 and not nlu.is_no(text):
                d["address"] = f"{d['address']} - {text.strip()}"
            had_info = True

    replies: list[str] = []
    if text and _is_question(text) and not had_info:
        ans = llm.answer(text, d) or _rule_answer(text)
        if ans:
            replies.append(ans)

    slot = _missing(d)
    if slot:
        if slot == "address_detail":
            d["address_detail_asked"] = True
        d["awaiting"] = slot
        if slot == "phone" and d.get("phone_hint"):
            replies.append(f"أبعت الأوردر على نفس الرقم {d['phone_hint']}؟ (أو ابعتي رقم تاني)")
        elif slot == "items" and replies:
            replies.append("تحبي أسجلك طلب؟ قوليلي المنتج والمقاس واللون 🛍️")
        else:
            replies.append(_ask(slot, d))
        return _reply(conv, replies)

    d.pop("awaiting", None)
    if not d.get("upsell_done"):
        d["upsell_done"] = True
        offer = _upsell_offer(d)
        if offer:
            d["upsell_offer"] = offer
            conv["state"] = "UPSELL"
            db.log_event(conv["id"], "upsell_offered", offer)
            replies.append(f"عرض خاص ليكي بس 🎁 تحبي تضيفي {offer['name']} بـ {offer['price']} ج بدل {offer['list']} ج؟ "
                           "بتليق جداً مع اختيارك (رد بـ «ضيفي» أو «لا شكراً»)")
            return _reply(conv, replies)
    conv["state"] = "CONFIRM"
    replies.append(_summary(d))
    return _reply(conv, replies)


def _deposit_request(order: dict) -> str:
    p = store()["policy"]
    return (f"الأوردر رقم {order['id']} جاهز 🎉 علشان نحجزهولك ونشحنه النهارده محتاجين عربون {p['deposit_amount']} ج "
            f"بيتخصم من الإجمالي.\nInstaPay: {p['instapay_handle']}\nفودافون كاش: {p['vodafone_cash']}\n"
            "وابعتيلي صورة التحويل هنا 📸")


def _deposit_rejection(res: dict) -> str:
    reason = res["reason"] or ""
    need = store()["policy"]["deposit_amount"]
    if reason == "duplicate_screenshot" or reason == "reference_already_used":
        return "الإيصال ده اتستخدم قبل كده ⚠️ ممكن تبعتي إيصال التحويل الجديد؟"
    if reason.startswith("amount_too_low"):
        return f"المبلغ اللي في الإيصال أقل من العربون المطلوب ({need} ج) — ممكن تحوّلي الباقي وتبعتي الإيصال؟"
    if reason == "wrong_recipient":
        return f"التحويل ده مش على حسابنا ⚠️ حسابنا على InstaPay: {store()['policy']['instapay_handle']}"
    if reason == "transaction_not_successful":
        return "العملية دي ظاهرة إنها لسه ما تمتش — ممكن تتأكدي وتبعتي الإيصال بعد نجاح التحويل؟"
    if reason == "looks_edited":
        return "مش قادرين نتحقق من الإيصال ده 🙏 ممكن تبعتي سكرين شوت أصلية من التطبيق؟"
    return "مش قادرة أقرأ الإيصال 🙏 ابعتي سكرين شوت واضحة فيها المبلغ ورقم العملية."


def _reply(conv: dict, texts: list[str]) -> list[str]:
    texts = [t for t in texts if t]
    for t in texts:
        db.add_message(conv["id"], "agent", t)
    db.save_conversation(conv)
    return texts
