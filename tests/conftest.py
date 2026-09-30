import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["TA2KEED_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")
os.environ["LLM_PROVIDER"] = "offline"
os.environ.pop("TELEGRAM_BOT_TOKEN", None)

import pytest  # noqa: E402

from ta2keed import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    db.reset(seed=True)
    yield
