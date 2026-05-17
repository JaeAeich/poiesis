"""Async Pod-watch iterator over the Kubernetes API.

The Kubernetes Python client's `watch.Watch().stream(...)` is a
synchronous, blocking generator. Both TRec (in-Pod recorder) and TCtl
(cluster-wide controller) need to consume that stream from asyncio
code. This module hides the sync→async bridge behind a single
async-iterator interface, so the consumer just `async for event in
watch_pods(...)`.

Two reasons this matters beyond duplication:

    1. The bridge (thread + asyncio.Queue + cross-thread put_nowait)
        is non-obvious. Putting it in one place means the next person
        who adds a Pod watcher gets it for free.
    2. Tests can substitute an alternative async iterator — fixture
        events instead of a real K8s API — without monkey-patching
        the kubernetes client.

The watcher reconnects on stream timeout (the kubernetes client returns
when its `timeout_seconds` window expires). It only surrenders when the
caller cancels its task or the underlying API raises a non-recoverable
exception.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import kubernetes

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from kubernetes.client import CoreV1Api

logger = logging.getLogger(__name__)


#: Default per-stream timeout. The kubernetes watch returns cleanly when
#: the server hasn't sent an event for this long; we reconnect.
_DEFAULT_STREAM_TIMEOUT_SECONDS = 300


@dataclass(frozen=True, slots=True)
class PodSelector:
    """Which Pods to watch.

    `field_selector` and `label_selector` map directly to the kubernetes
    API parameters of the same name. Both are optional; the union is
    typically what's wanted (selector strings are AND-combined by the
    API server itself).
    """

    namespace: str
    field_selector: str | None = None
    label_selector: str | None = None
    timeout_seconds: int = _DEFAULT_STREAM_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class PodEvent:
    """A single watch event: the kubelet's event type plus the Pod dict.

    `type` is one of `"ADDED"`, `"MODIFIED"`, `"DELETED"`, `"BOOKMARK"`,
    `"ERROR"`. The Pod is rendered to a plain dict so consumers don't
    depend on the kubernetes client's model classes.
    """

    type: str
    pod: dict[str, Any]


async def watch_pods(
    core_v1: CoreV1Api,
    selector: PodSelector,
) -> AsyncGenerator[PodEvent]:
    """Yield Pod events matching `selector` until cancelled.

    Internally runs the blocking kubernetes watch on a worker thread and
    forwards events through an asyncio queue. Stream-timeout reconnects
    are transparent. A fatal stream error logs and ends the iterator.
    """
    queue: asyncio.Queue[PodEvent | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    producer = loop.run_in_executor(
        None, _run_watch_thread, core_v1, selector, queue, loop
    )
    try:
        while True:
            event = await queue.get()
            if event is None:
                return
            yield event
    finally:
        # We can't actually stop the blocking watch from outside, but
        # cancelling the future lets the executor reclaim the slot once
        # the next stream-timeout completes.
        producer.cancel()


def _run_watch_thread(
    core_v1: CoreV1Api,
    selector: PodSelector,
    queue: asyncio.Queue[PodEvent | None],
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Thread body: stream watch events onto the asyncio queue.

    Reconnects on stream timeout. Pushes a `None` sentinel on
    unrecoverable errors so the consumer terminates cleanly.
    """
    try:
        while True:
            # kubernetes-stubs doesn't export the `watch` submodule that
            # the runtime kubernetes client publishes.
            watch = kubernetes.watch.Watch()  # ty: ignore[unresolved-attribute]
            stream_kwargs: dict[str, Any] = {
                "namespace": selector.namespace,
                "timeout_seconds": selector.timeout_seconds,
            }
            if selector.field_selector is not None:
                stream_kwargs["field_selector"] = selector.field_selector
            if selector.label_selector is not None:
                stream_kwargs["label_selector"] = selector.label_selector

            for raw in watch.stream(core_v1.list_namespaced_pod, **stream_kwargs):
                pod = raw["object"]
                event_type = raw.get("type", "MODIFIED")
                pod_dict = pod.to_dict() if hasattr(pod, "to_dict") else dict(pod)
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(
                        queue.put_nowait, PodEvent(type=event_type, pod=pod_dict)
                    )
            # Stream timed out; loop and reconnect.
    except Exception:
        logger.exception("pod watch stream failed")
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(queue.put_nowait, None)
