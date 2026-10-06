"""Single-owner ASGI disconnect monitoring for an already-consumed HTTP body."""

import asyncio
from contextlib import suppress


async def monitor_disconnect(application, receive, disconnected):
    async def watch():
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected.set()
                return

    task = asyncio.create_task(application)
    watcher = asyncio.create_task(watch())
    try:
        done, _ = await asyncio.wait({task, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if watcher in done:
            await watcher
        if watcher in done and disconnected.is_set() and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            return True
        await task
        return False
    finally:
        for pending in (task, watcher):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, watcher, return_exceptions=True)
