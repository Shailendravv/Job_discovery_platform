"""HostThrottle — per-host min-interval spacing used by the ingest runner.

Uses a small interval (not the real 1s) so the test stays fast; verifies
the *behavior* (same host serializes with spacing, different hosts don't
wait on each other) rather than the exact production interval.
"""

import asyncio
import time

from app.agents.ats_providers._http import HostThrottle


async def test_same_host_is_spaced_out():
    # Windows' default event-loop timer resolution can undershoot a very
    # short asyncio.sleep by a couple ms — use an interval well above that
    # noise floor rather than tightening the assertion.
    interval = 0.2
    throttle = HostThrottle(min_interval_seconds=interval)
    start = time.monotonic()
    await throttle.wait("https://api.example.com/a")
    await throttle.wait("https://api.example.com/b")
    elapsed = time.monotonic() - start
    assert elapsed >= interval * 0.9


async def test_different_hosts_do_not_wait_on_each_other():
    throttle = HostThrottle(min_interval_seconds=1.0)
    start = time.monotonic()
    await asyncio.gather(
        throttle.wait("https://a.example.com/x"),
        throttle.wait("https://b.example.com/x"),
    )
    elapsed = time.monotonic() - start
    assert elapsed < 0.5  # would be ~1s if they shared one lock/timer


async def test_url_without_host_is_a_noop():
    throttle = HostThrottle(min_interval_seconds=10.0)
    start = time.monotonic()
    await throttle.wait("not-a-url")
    elapsed = time.monotonic() - start
    assert elapsed < 0.1
