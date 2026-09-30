"""Egyptian-Arabic / Franco order understanding.

Two layers:
  1. `rule_extract` — deterministic, offline, zero-cost. Handles the common shapes of
     Egyptian Instagram/WhatsApp orders (Arabic, Arabic-Indic digits, Franco-Arabic).
  2. `llm.extract` (optional) — an LLM fills whatever the rules missed. Results are merged,
     rules win on hard fields (phone), LLM wins on fuzzy ones (address wording).
"""
from __future__ import annotations

import re

from .config import store

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize(text: str) -> str:
    t = (text or "").translate(AR_DIGITS)
    t = re.sub("[إأآا]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    t = re.sub("[\u064B-\u0652\u0640]", "", t)  # tashkeel + tatweel
    return t.lower().strip()


# ---------------------------------------------------------------- vocab
YES = ["تمام", "ايوه", "ايوا", "اه", "ايه", "ماشي", "اكيد", "اوكي", "اوك", "ok", "okay", "yes", "yup", "tamam",
       "aywa", "ah", "maashy", "mashy", "موافق", "موافقه", "اكد", "اكدي", "كده تمام", "عظيم", "حلو", "يلا", "👍", "✅",
       "صح", "مظبوط", "بالظبط", "ضيفي", "ضيفها", "ضيفه", "زوديها", "هاخدها", "هاخده", "عايزاها", "عاوزاها"]
NO = ["لا", "لأ", "لاء", "مش عايز", "مش عاوز", "مش عايزه", "مش عاوزه", "no", "la", "la2", "مش محتاج", "مش محتاجه",
      "بلاش", "كفايه", "خلاص كده", "مش دلوقتي"]
CANCEL = ["الغي", "الغاء", "كنسل", "cancel", "مش عايزه الاوردر", "مش عايز الاوردر", "هلغي", "عايزه الغي",
          "عايز الغي", "بطلت", "مش هاخد"]
HESITATION = ["هشوف", "هفكر", "مش متاكد", "مش متاكده", "لسه", "يمكن", "ممكن بعدين", "بعدين", "هرد عليكي",
              "هكلم جوزي", "هسال", "مش عارفه", "مش عارف", "لو عجبني"]

SIZES = {
    "xxl": "XXL", "2xl": "XXL", "اكس اكس لارج": "XXL",
    "xl": "XL", "اكس لارج": "XL", "اكسلارج": "XL", "x large": "XL",
    "large": "L", "لارج": "L", "كبير": "L",
    "medium": "M", "ميديم": "M", "ميديوم": "M", "وسط": "M",
    "small": "S", "سمول": "S", "صغير": "S",
}
COLORS = {
    "اسود": "black", "سودا": "black", "سوده": "black", "black": "black", "iswed": "black",
    "كحلي": "navy", "نيفي": "navy", "navy": "navy",
    "بيج": "beige", "beige": "beige", "بيچ": "beige",
    "بينك": "pink", "روز": "pink", "وردي": "pink", "pink": "pink",
    "ابيض": "white", "بيضا": "white", "بيضه": "white", "white": "white",
    "زيتي": "olive", "اوليف": "olive", "olive": "olive",
}
COLOR_AR = {"black": "أسود", "navy": "كحلي", "beige": "بيج", "pink": "بينك", "white": "أبيض", "olive": "زيتي"}
NUM_WORDS = {"واحد": 1, "واحده": 1, "اتنين": 2, "اثنين": 2, "تنين": 2, "تلاته": 3, "ثلاثه": 3, "تلات": 3,
             "اربعه": 4, "اربع": 4, "خمسه": 5, "one": 1, "two": 2, "three": 3, "wa7da": 1, "etnein": 2, "itnen": 2}

ZONES = {
    "cairo": ["القاهره", "مدينه نصر", "مصر الجديده", "المعادي", "التجمع", "الرحاب", "مدينتي", "شبرا", "حلوان",
              "المقطم", "العباسيه", "عين شمس", "المرج", "الزيتون", "وسط البلد", "الشروق", "العبور", "بدر",
              "النزهه", "مصر القديمه", "السيده زينب", "المطريه", "القطاميه", "cairo", "nasr city", "maadi",
              "tagamoa", "heliopolis"],
    "giza": ["الجيزه", "الهرم", "فيصل", "الدقي", "المهندسين", "العجوزه", "امبابه", "6 اكتوبر", "اكتوبر",
             "الشيخ زايد", "زايد", "حدايق الاهرام", "بولاق الدكرور", "الوراق", "giza", "haram", "october",
             "zayed", "mohandseen", "dokki"],
    "alex": ["اسكندريه", "الاسكندريه", "سموحه", "سيدي بشر", "العجمي", "المنتزه", "ميامي", "alex", "alexandria"],
    "delta": ["المنصوره", "طنطا", "الزقازيق", "دمنهور", "بنها", "شبين الكوم", "كفر الشيخ", "دمياط", "المحله",
              "الدقهليه", "الغربيه", "الشرقيه", "المنوفيه", "القليوبيه", "البحيره", "mansoura", "tanta"],
    "canal": ["الاسماعيليه", "بورسعيد", "السويس", "ismailia", "port said", "suez"],
    "upper": ["اسيوط", "سوهاج", "المنيا", "قنا", "الاقصر", "اسوان", "بني سويف", "الفيوم", "assiut", "minya",
              "luxor", "aswan", "sohag", "fayoum"],
}
ADDRESS_MARKERS = ["شارع", "ش ", "عماره", "عمارة", "برج", "شقه", "الدور", "دور", "بلوك", "مربع", "كمبوند",
                   "المجاوره", "الحي", "بجوار", "جنب", "امام", "قدام", "خلف", "ورا", "street", "st ", "building",
                   "apt", "floor", "عنوان", "العنوان", "ميدان", "حاره", "عطفه", "منطقه"]
DETAIL_MARKERS = ["شقه", "الدور", "دور", "عماره", "برج", "رقم", "بلوك", "floor", "apt", "building", "فيلا"]

PHONE_RE = re.compile(r"(?<!\d)(?:\+?2)?(01[0125]\d{8})(?!\d)")
REF_RE = re.compile(r"(?:رقم العمليه|رقم المرجع|المرجع|ref(?:erence)?|reference no|transaction(?: id)?|عمليه)\D{0,6}(\d{6,16})", re.I)
AMOUNT_RE = re.compile(r"(\d{2,6})\s*(?:ج|جنيه|جنية|egp|le|pound)", re.I)


PREFIX = r"(?:و|ف)?(?:ال|بال|لل|ب|ل)?"


def _has(t: str, words: list[str], prefix: bool = False) -> bool:
    pre = PREFIX if prefix else ""
    for w in words:
        w = normalize(w)
        if re.search(rf"(?<![\w\u0600-\u06FF]){pre}{re.escape(w)}(?![\w\u0600-\u06FF])", t):
            return True
    return False


def is_yes(text: str) -> bool:
    t = normalize(text)
    return _has(t, YES) and not is_no(text)


def is_no(text: str) -> bool:
    t = normalize(text)
    return _has(t, NO) or _has(t, CANCEL)


def is_cancel(text: str) -> bool:
    return _has(normalize(text), CANCEL)


def hesitation(text: str) -> bool:
    return _has(normalize(text), HESITATION)


def find_zone(t: str) -> str | None:
    t = normalize(t)
    for zone, places in ZONES.items():
        if _has(t, places, prefix=True):
            return zone
    return None


def _qty_before(t: str, idx: int) -> int:
    window = t[max(0, idx - 14):idx].split()
    for tok in reversed(window[-2:]):
        if tok.isdigit() and 0 < int(tok) < 20:
            return int(tok)
        if tok in NUM_WORDS:
            return NUM_WORDS[tok]
    return 1


def _segment(t: str, start: int, stops: list[int]) -> str:
    nxt = min([s for s in stops if s > start] + [len(t)])
    return t[start:nxt]


def extract_items(t: str) -> list[dict]:
    hits = []
    for p in store()["products"]:
        for kw in p["keywords"]:
            m = re.search(rf"(?<![\w\u0600-\u06FF]){PREFIX}{re.escape(normalize(kw))}", t)
            if m:
                hits.append((m.start(), p))
                break
    hits.sort(key=lambda h: h[0])
    starts = [h[0] for h in hits]
    items = []
    for start, p in hits:
        seg = _segment(t, start, starts)
        item = {"sku": p["sku"], "qty": _qty_before(t, start), "size": None, "color": None}
        numeric = [s for s in p["sizes"] if s.isdigit()]
        if numeric:
            m = re.search(r"(?<!\d)(\d{2})(?!\d)", seg)
            if m and m.group(1) in numeric:
                item["size"] = m.group(1)
        if p["sizes"] and not item["size"] and not numeric:
            for k, v in sorted(SIZES.items(), key=lambda kv: -len(kv[0])):
                if re.search(rf"(?<![\w\u0600-\u06FF]){re.escape(k)}(?![\w\u0600-\u06FF])", seg):
                    item["size"] = v
                    break
            if not item["size"]:
                m = re.search(r"(?<![\w])(xxl|xl|l|m|s)(?![\w])", seg)
                if m:
                    item["size"] = m.group(1).upper()
        if p["colors"]:
            for k, v in COLORS.items():
                if normalize(k) in seg and v in p["colors"]:
                    item["color"] = v
                    break
        items.append(item)
    return items


def extract_size_color(t: str) -> dict:
    out = {}
    for k, v in sorted(SIZES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![\w\u0600-\u06FF]){re.escape(k)}(?![\w\u0600-\u06FF])", t):
            out["size"] = v
            break
    if "size" not in out:
        m = re.fullmatch(r"\s*(xxl|xl|l|m|s)\s*", t)
        if m:
            out["size"] = m.group(1).upper()
    for k, v in COLORS.items():
        if normalize(k) in t:
            out["color"] = v
            break
    return out


def extract_name(raw: str) -> str | None:
    t = raw.translate(AR_DIGITS)
    m = re.search(r"(?:اسمي|إسمي|الاسم|الإسم|انا اسمي|اسم المستلم|المستلم|my name is|esmy|ismi)\s*[:：\-]?\s*([^\n,،.0-9]{2,40})", t, re.I)
    if m:
        name = re.split(r"\s+(?:و|ورقمي|رقمي|العنوان|عنواني|تليفوني|موبايلي)\s*", m.group(1).strip())[0]
        words = name.split()[:3]
        return " ".join(words) if words else None
    return None


def extract_address(raw: str) -> str | None:
    t = raw.translate(AR_DIGITS)
    m = re.search(r"(?:العنوان|عنواني|عنوان|address|el3enwan)\s*[:：\-]?\s*(.+)", t, re.I | re.S)
    cand = m.group(1) if m else None
    if not cand:
        for line in re.split(r"[\n]", t):
            n = normalize(line)
            if _has(n, ADDRESS_MARKERS) or (find_zone(n) and len(n.split()) >= 3):
                cand = line
                break
    if not cand:
        return None
    pm = PHONE_RE.search(cand)
    if pm:  # "name 01xxxxxxxxx address..." -> keep the side that looks like an address
        after, before = cand[pm.end():], cand[:pm.start()]
        cand = after if len(after.strip()) >= 3 else before
    cand = re.split(r"(?:اسمي|الاسم|رقمي|تليفوني|موبايلي)", cand)[0]
    cand = re.sub(r"\s+", " ", cand).strip(" ،,.-:")
    if len(cand) >= 6 or (find_zone(cand) and len(cand) >= 3):
        return cand
    return None


def leading_name(raw: str) -> str | None:
    """'هبة علي 0123... المنصورة ...' -> 'هبة علي' (words before the phone number)."""
    t = raw.translate(AR_DIGITS)
    m = PHONE_RE.search(t)
    if not m:
        return None
    head = re.sub(r"^(?:انا|أنا|اسمي|الاسم)\s+", "", t[:m.start()].strip(" ،,:-\n"))
    words = head.split()
    if 2 <= len(words) <= 4 and all(re.fullmatch(r"[\u0600-\u06FFa-zA-Z]+", w) for w in words) \
            and not _has(normalize(head), YES + NO + ADDRESS_MARKERS) and not find_zone(head) \
            and not extract_items(normalize(head)):
        return " ".join(words)
    return None


def address_is_vague(address: str | None) -> bool:
    if not address:
        return True
    n = normalize(address)
    has_detail = _has(n, DETAIL_MARKERS) or bool(re.search(r"\d", n))
    return not has_detail or len(n.split()) < 4


def rule_extract(raw: str) -> dict:
    t = normalize(raw)
    out: dict = {}
    items = extract_items(t)
    if items:
        out["items"] = items
    phone = PHONE_RE.search(t)
    if phone:
        out["phone"] = phone.group(1)
    name = extract_name(raw) or leading_name(raw)
    if name:
        out["name"] = name
    addr = extract_address(raw)
    if addr:
        out["address"] = addr
    zone = find_zone(t)
    if zone:
        out["zone"] = zone
    sc = extract_size_color(t)
    if sc and not items:
        out["size_color"] = sc
    return out


def extract_receipt_text(raw: str) -> dict:
    """Payment info typed or pasted by the customer (fallback when no vision model)."""
    t = normalize(raw)
    out = {}
    ref = REF_RE.search(t) or re.search(r"(?<!\d)(\d{9,16})(?!\d)", t)
    if ref:
        out["reference"] = ref.group(1)
    amt = AMOUNT_RE.search(t)
    if amt:
        out["amount"] = int(amt.group(1))
    if "instapay" in t or "انستاباي" in t or "انستا باي" in t:
        out["method"] = "instapay"
    elif "فودافون" in t or "vodafone" in t:
        out["method"] = "vodafone_cash"
    return out
