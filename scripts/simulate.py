"""Run the scripted demo conversations in the terminal (no server, no API keys).

    python -m scripts.simulate            # all scenarios
    python -m scripts.simulate risky_deposit
    python -m scripts.simulate --chat     # talk to the agent yourself
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from ta2keed import aftercare, agent, db, delivery  # noqa: E402
from ta2keed.config import ROOT  # noqa: E402
from ta2keed.scenarios import SCENARIOS  # noqa: E402

RECEIPTS = ROOT / "data" / "receipts"


def run(name: str) -> None:
    sc = SCENARIOS[name]
    print(f"\n{'=' * 70}\n▶ {name}: {sc['title']}\n{'=' * 70}")
    for step in sc["steps"]:
        if "owner" in step:
            from ta2keed import payconfirm
            conv = db.get_conversation("sim", sc["user"])
            before = db.one("SELECT MAX(id) m FROM messages WHERE conv_id=?", (conv["id"],))["m"] or 0
            for c in payconfirm.pending():
                print(f"\n👩‍💼 [owner gets the receipt on Telegram/WhatsApp, checks the bank app → presses "
                      f"{'✅ received' if step['owner'] == 'approve' else '❌ not received'}]")
                print("   " + payconfirm.decide(c["id"], step["owner"] == "approve", by="sim")["message"])
            for m in db.q("SELECT text FROM messages WHERE conv_id=? AND id>? AND role='agent'", (conv["id"], before)):
                print("🤖 " + m["text"].replace("\n", "\n   "))
            continue
        if "courier" in step or "followups" in step:
            conv = db.get_conversation("sim", sc["user"])
            oid = conv.get("order_id") or (db.one("SELECT id FROM orders WHERE conv_id=? ORDER BY created_at DESC LIMIT 1",
                                                  (conv["id"],)) or {}).get("id")
            before = db.one("SELECT MAX(id) m FROM messages WHERE conv_id=?", (conv["id"],))["m"] or 0
            if "courier" in step:
                res = delivery.advance(delivery.find_order(oid))
                print(f"\n📦 [courier update: {res.get('status')}] "
                      + ("→ customer notified" if res.get("customer_notified") else "→ internal only (dashboard)"))
            else:
                aftercare.fast_forward(oid, step["followups"])
                print(f"\n⏩ [time passes: {step['followups']} follow-up is due]")
            for m in db.q("SELECT text FROM messages WHERE conv_id=? AND id>? AND role='agent'", (conv["id"], before)):
                print("🤖 " + m["text"].replace("\n", "\n   "))
            continue
        if "image" in step:
            print(f"\n👤 [sends screenshot: {step['image']}]")
            replies = agent.handle("sim", sc["user"], image=(RECEIPTS / step["image"]).read_bytes())
        else:
            print(f"\n👤 {step['text']}")
            replies = agent.handle("sim", sc["user"], step["text"])
        for r in replies:
            print("🤖 " + r.replace("\n", "\n   "))


def chat() -> None:
    print("Chat with Ta2keed (Ctrl+C to exit). Send a receipt with: /img data/receipts/receipt_ok.png")
    while True:
        msg = input("\n👤 ").strip()
        if msg.startswith("/img "):
            replies = agent.handle("sim", "you", image=Path(msg[5:].strip()).read_bytes())
        else:
            replies = agent.handle("sim", "you", msg)
        for r in replies:
            print("🤖 " + r.replace("\n", "\n   "))


if __name__ == "__main__":
    db.reset(seed=True)
    args = sys.argv[1:]
    if args and args[0] == "--chat":
        chat()
    else:
        for n in (args or list(SCENARIOS)):
            run(n)
        from ta2keed import impact
        print("\n" + impact.text_report())
