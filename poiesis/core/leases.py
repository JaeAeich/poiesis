"""Lease-based leader election against `coordination.k8s.io/v1`.

Lightweight client-side wrapper around the Lease API. Mirrors the
client-go semantics: a candidate tries to acquire (or renew, if they're
the holder) a Lease whose name and namespace are agreed up front. Only
one candidate holds the Lease at a time; the other(s) loop on
`try_acquire_or_renew`.

The kubernetes Python client only ships a ConfigMap-based lock, which
upstream has deprecated. Leases are the current standard and match the
ADR-0003 requirement.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from kubernetes.client import (
    CoordinationV1Api,
    V1Lease,
    V1LeaseSpec,
    V1ObjectMeta,
)
from kubernetes.client.exceptions import ApiException

logger = logging.getLogger(__name__)


async def try_acquire_or_renew(
    coord_v1: CoordinationV1Api,
    *,
    name: str,
    namespace: str,
    identity: str,
    lease_duration_seconds: int,
) -> bool:
    """Try to become the leader holding `<namespace>/<name>`.

    Returns True if `identity` now holds (or kept) the Lease, False otherwise.

    Logic mirrors client-go's `leaderelection.tryAcquireOrRenew`:
    - If no Lease exists, create one with `identity` as holder.
    - If the Lease is held by us, renew `renewTime`.
    - If the Lease is held by someone else and unexpired, give up.
    - If the Lease is held by someone else but expired, take it over.
    """
    now = datetime.now(UTC)
    existing = await _get_lease(coord_v1, name, namespace)
    if existing is None:
        return await _create_lease(
            coord_v1,
            name,
            namespace,
            identity,
            lease_duration_seconds,
            now,
        )

    spec = existing.spec or V1LeaseSpec()
    holder = spec.holder_identity
    renew_time = spec.renew_time
    duration = spec.lease_duration_seconds or lease_duration_seconds

    if holder == identity:
        return await _renew_lease(coord_v1, existing, identity, duration, now)

    if renew_time is not None and not _lease_expired(renew_time, duration, now):
        return False

    return await _renew_lease(coord_v1, existing, identity, duration, now)


def _lease_expired(
    renew_time: datetime,
    duration_seconds: int,
    now: datetime,
) -> bool:
    """Has the current holder's renewal window passed?"""
    elapsed = (now - renew_time).total_seconds()
    return elapsed > duration_seconds


async def _get_lease(
    coord_v1: CoordinationV1Api,
    name: str,
    namespace: str,
) -> V1Lease | None:
    try:
        return await asyncio.to_thread(coord_v1.read_namespaced_lease, name, namespace)
    except ApiException as exc:
        if exc.status == 404:  # noqa: PLR2004
            return None
        raise


async def _create_lease(
    coord_v1: CoordinationV1Api,
    name: str,
    namespace: str,
    identity: str,
    duration_seconds: int,
    now: datetime,
) -> bool:
    body = V1Lease(
        metadata=V1ObjectMeta(name=name, namespace=namespace),
        spec=V1LeaseSpec(
            holder_identity=identity,
            lease_duration_seconds=duration_seconds,
            acquire_time=now,
            renew_time=now,
            lease_transitions=0,
        ),
    )
    try:
        await asyncio.to_thread(coord_v1.create_namespaced_lease, namespace, body)
    except ApiException as exc:
        if exc.status == 409:  # noqa: PLR2004
            return False
        raise
    return True


async def _renew_lease(
    coord_v1: CoordinationV1Api,
    existing: V1Lease,
    identity: str,
    duration_seconds: int,
    now: datetime,
) -> bool:
    spec = existing.spec or V1LeaseSpec()
    transitions = spec.lease_transitions or 0
    if spec.holder_identity != identity:
        transitions += 1
    existing.spec = V1LeaseSpec(
        holder_identity=identity,
        lease_duration_seconds=duration_seconds,
        acquire_time=spec.acquire_time if spec.holder_identity == identity else now,
        renew_time=now,
        lease_transitions=transitions,
    )
    assert existing.metadata is not None
    name = existing.metadata.name
    namespace = existing.metadata.namespace
    assert name is not None
    assert namespace is not None
    try:
        await asyncio.to_thread(
            coord_v1.replace_namespaced_lease, name, namespace, existing
        )
    except ApiException as exc:
        if exc.status == 409:  # noqa: PLR2004
            return False
        raise
    return True


__all__ = ["try_acquire_or_renew"]
