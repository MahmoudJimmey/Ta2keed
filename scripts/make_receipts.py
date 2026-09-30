"""Generate demo InstaPay-style receipt screenshots into data/receipts/.

Each PNG also carries its fields as tEXt metadata so the offline demo can "read" it
without a vision model. With an LLM configured, the vision model reads the pixels instead.
Requires Pillow (dev only):  pip install pillow
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

OUT = Path(__file__).resolve().parent.parent / "data" / "receipts"
OUT.mkdir(parents=True, exist_ok=True)


def font(size, bold=False):
    for name in (["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def receipt(filename, amount, reference, recipient, status="Successful", when="29 Sep 2026, 14:32"):
    W, H = 540, 900
    img = Image.new("RGB", (W, H), "#F4F1FA")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 110], fill="#4B1D8F")
    d.text((30, 38), "InstaPay", font=font(38, True), fill="white")
    d.text((W - 170, 50), "Transfer receipt", font=font(18), fill="#E3D6FF")
    ok = status.lower().startswith("succ")
    d.ellipse([W // 2 - 50, 150, W // 2 + 50, 250], fill="#1FA463" if ok else "#D93025")
    d.text((W // 2 - 18 if ok else W // 2 - 14, 168), "✓" if ok else "!", font=font(56, True), fill="white")
    d.text((W // 2, 285), f"Transaction {status}", font=font(26, True), fill="#222", anchor="mm")
    d.text((W // 2, 345), f"EGP {amount:,.2f}", font=font(46, True), fill="#4B1D8F", anchor="mm")
    rows = [("To", recipient), ("From", "Customer ****4471"), ("Reference No.", reference),
            ("Date", when), ("Fees", "EGP 0.00"), ("Channel", "IPN")]
    y = 420
    d.rounded_rectangle([24, y - 20, W - 24, y + len(rows) * 62], 18, fill="white")
    for k, v in rows:
        d.text((48, y), k, font=font(20), fill="#777")
        d.text((W - 48, y), v, font=font(21, True), fill="#222", anchor="ra")
        y += 62
    d.text((W // 2, H - 40), "Demo receipt generated for Ta2keed — not a real transaction",
           font=font(14), fill="#999", anchor="mm")
    meta = PngInfo()
    meta.add_text("receipt", json.dumps({"is_receipt": True, "method": "instapay", "amount": amount,
                                         "reference": reference, "recipient": recipient,
                                         "datetime": when, "status": "success" if ok else "failed",
                                         "edited_suspicion": "none"}))
    img.save(OUT / filename, pnginfo=meta)
    print("wrote", OUT / filename)


receipt("receipt_ok.png", 100, "702915384462", "nourboutique@instapay")
receipt("receipt_wrong_account.png", 100, "702911112345", "ahmed.k@instapay")
receipt("receipt_low_amount.png", 50, "702900077711", "nourboutique@instapay")
receipt("receipt_failed.png", 100, "702955500012", "nourboutique@instapay", status="Failed")
