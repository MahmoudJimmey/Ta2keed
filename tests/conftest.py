import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = Path(tempfile.mkdtemp())
os.environ["TA2KEED_DATA_DIR"] = str(_tmp)          # isolated settings.json / store.json per test run
os.environ["TA2KEED_DB"] = str(_tmp / "test.db")
os.environ["LLM_PROVIDER"] = "offline"
os.environ["SCHEDULER"] = "off"
os.environ["TA2KEED_AUTH"] = "off"                    # auth has its own tests (they switch it back on)
for k in ("TELEGRAM_BOT_TOKEN", "WHATSAPP_ACCESS_TOKEN", "OWNER_WHATSAPP", "ADMIN_PASSWORD", "BOSTA_API_KEY",
          "PUBLIC_URL", "DEMO_MODE"):
    os.environ.pop(k, None)

import pytest  # noqa: E402

from ta2keed import config, db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    for f in ("settings.json", "store.json"):
        (_tmp / f).unlink(missing_ok=True)
    config.store.cache_clear()
    db.reset(seed=True)
    config.save_wizard_values({"_setup_skipped": True})   # existing tests expect the dashboard, not the wizard
    yield
    config.store.cache_clear()
