"""Serialize use of one adapter across the GUI's native worker processes."""
import asyncio
from contextlib import asynccontextmanager


@asynccontextmanager
async def radio_access(lock, cancel=None):
    acquired = False
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise asyncio.CancelledError
            if lock is None or lock.acquire(blocking=False):
                acquired = lock is not None
                break
            await asyncio.sleep(0.025)
        yield
    finally:
        if acquired:
            lock.release()
