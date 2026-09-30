"""Background jobs: send due follow-ups (review / reorder) and the daily owner digest."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from . import aftercare, db, notify
from .config import store

log = logging.getLogger("ta2keed.scheduler")


def digest_due(now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now()
    hh, mm = (int(x) for x in store().get("notifications", {}).get("digest_time", "21:00").split(":"))
    if (now.hour, now.minute) < (hh, mm):
        return False
    return db.kv_get("last_digest_date") != now.date().isoformat()


def tick(now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now()
    out = {"followups": aftercare.run_due(now.timestamp()), "digest": None}
    if digest_due(now):
        out["digest"] = notify.send_digest(now.date())
        db.kv_set("last_digest_date", now.date().isoformat())
    return out


async def loop(interval: int = 60) -> None:
    log.info("scheduler started (every %ss)", interval)
    while True:
        try:
            await asyncio.to_thread(tick)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(interval)
