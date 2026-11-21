"""tctl keeps its leader Lease in the release namespace (#156).

With `taskpods.namespace` set, tctl used the TaskPod namespace for the Lease
too. Its Role grants Lease access only in the release namespace, so the read
returned 403, the error was re-raised and tctl exited: no task ever reached a
terminal state.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from click.testing import CliRunner
from kubernetes.client.exceptions import ApiException

from poiesis.cli.commands.poiesis import tctl as tctl_cli
from poiesis.core import tctl

RELEASE_NS = "poiesis"
TASK_NS = "poiesis-tasks"


class Pool:
    async def close(self) -> None:
        pass


class Harness:
    """Runs `tctl.run` with the Lease, the pool and the reconcile pass faked."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.lease_namespaces: list[str] = []
        self.reconciled: list[str] = []
        self.failures: list[ApiException] = []
        self.cancelled = asyncio.Event()

        async def lease(_coord: Any, **kwargs: Any) -> bool:
            self.lease_namespaces.append(kwargs["namespace"])
            if self.failures:
                raise self.failures.pop(0)
            return True

        async def reconcile_once(_core: Any, _pool: Any, namespace: str) -> None:
            self.reconciled.append(namespace)
            self.cancelled.set()

        async def create_pool(*_: Any, **__: Any) -> Pool:
            return Pool()

        monkeypatch.setattr(tctl, "try_acquire_or_renew", lease)
        monkeypatch.setattr(tctl, "_reconcile_once", reconcile_once)
        monkeypatch.setattr(tctl, "_install_signal_handlers", lambda: self.cancelled)
        monkeypatch.setattr(tctl, "CoordinationV1Api", lambda: None)
        monkeypatch.setattr(tctl, "CoreV1Api", lambda: None)
        monkeypatch.setattr(tctl.asyncpg, "create_pool", create_pool)
        monkeypatch.setattr(tctl, "_LEASE_RENEW_INTERVAL_SECONDS", 0.01)

    def run(self, **kwargs: Any) -> int:
        async def main() -> int:
            async with asyncio.timeout(5):
                return await tctl.run(TASK_NS, "dsn", identity="tctl-0", **kwargs)

        return asyncio.run(main())


def test_lease_is_held_in_the_release_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Lease uses the release namespace; Pods are read where tasks run."""
    harness = Harness(monkeypatch)
    assert harness.run(lease_namespace=RELEASE_NS) == 0
    assert set(harness.lease_namespaces) == {RELEASE_NS}
    assert harness.reconciled == [TASK_NS]


def test_lease_defaults_to_the_task_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a lease namespace the single-namespace layout is unchanged."""
    harness = Harness(monkeypatch)
    assert harness.run() == 0
    assert set(harness.lease_namespaces) == {TASK_NS}


@pytest.mark.parametrize("status", [403, 500, 0])
def test_lease_api_error_is_retried(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    """A failing Lease call is logged and retried; tctl neither exits nor leads."""
    harness = Harness(monkeypatch)
    harness.failures = [ApiException(status=status, reason="nope") for _ in range(2)]
    assert harness.run(lease_namespace=RELEASE_NS) == 0
    assert len(harness.lease_namespaces) > 2  # noqa: PLR2004
    assert harness.reconciled == [TASK_NS]
    assert f"lease {RELEASE_NS}/poiesis-tctl-leader unavailable" in caplog.text


def test_leader_stands_down_when_the_renewal_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A leader that can't renew stops reconciling until it holds the Lease."""
    harness = Harness(monkeypatch)
    calls = 0

    async def lease(_coord: Any, **_: Any) -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:  # noqa: PLR2004 - the first renewal as leader
            raise ApiException(status=500, reason="boom")
        return True

    monkeypatch.setattr(tctl, "try_acquire_or_renew", lease)
    assert harness.run(lease_namespace=RELEASE_NS) == 0
    assert calls == 4  # noqa: PLR2004 - acquire, failed renew, acquire, renew
    assert harness.reconciled == [TASK_NS]


def test_cli_passes_both_namespaces(monkeypatch: pytest.MonkeyPatch) -> None:
    """`poiesis tctl run` reads the release namespace for the Lease."""
    seen: dict[str, Any] = {}

    async def run(namespace: str, dsn: str, **kwargs: Any) -> int:
        seen.update(namespace=namespace, dsn=dsn, **kwargs)
        return 0

    monkeypatch.setattr(tctl_cli, "run", run)
    monkeypatch.setattr(tctl_cli, "load_config", lambda: None)
    monkeypatch.setenv("POIESIS_NAMESPACE", RELEASE_NS)
    monkeypatch.setenv("POIESIS_TASKPOD_NAMESPACE", TASK_NS)
    monkeypatch.setenv("DATABASE_URL", "dsn")
    monkeypatch.delenv("POIESIS_POD_NAME", raising=False)

    result = CliRunner().invoke(tctl_cli.TctlCommand().create_command(), ["run"])

    assert result.exit_code == 0, result.output
    assert seen == {
        "namespace": TASK_NS,
        "dsn": "dsn",
        "lease_namespace": RELEASE_NS,
        "identity": None,
    }
