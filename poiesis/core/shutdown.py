"""Stopping a long-running process when Kubernetes asks it to."""

from __future__ import annotations

import asyncio
import signal


def stop_on_signals() -> asyncio.Event:
    """Return an Event that SIGTERM or SIGINT sets; the caller's loop polls it."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    return stop
