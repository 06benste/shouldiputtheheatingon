"""Background job: purge homes that have stopped reporting."""
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import and_, delete, or_

from .config import settings
from .db import Device, SessionLocal, utcnow

log = logging.getLogger(__name__)


def purge_inactive() -> int:
    cutoff = utcnow() - timedelta(days=settings.delete_inactive_after_days)
    with SessionLocal() as db:
        result = db.execute(delete(Device).where(or_(
            Device.reported_at < cutoff,
            and_(Device.reported_at.is_(None), Device.created_at < cutoff),
        )))
        db.commit()
        return result.rowcount or 0


async def maintenance_loop() -> None:
    while True:
        try:
            removed = await asyncio.to_thread(purge_inactive)
            if removed:
                log.info("Deleted %d inactive devices", removed)
        except Exception:  # keep the loop alive whatever happens
            log.exception("Purge failed")
        await asyncio.sleep(settings.purge_interval_minutes * 60)
