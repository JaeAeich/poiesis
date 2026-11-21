"""Tests for authorization: the claim rules and the decision service hook.

The TES routes run in a real app with real token validation (fake
issuer, see `fake_issuer.py`), an in-memory task store instead of
Postgres and a recording stub decision service on the fake network.
The requests the stub receives are compared with golden files in
`golden/authz/`, which are shared with the decision-service side.
"""

import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import httpx
import pytest
from fake_issuer import AUDIENCE, ISSUER, OTHER_ISSUER, Issuer, Network
from fastapi import FastAPI
from fastapi.testclient import TestClient

from poiesis.api import app as app_module
from poiesis.api import audit
from poiesis.api.auth import Actor, Principal
from poiesis.api.authz import Authz, parse_decision, strip_url
from poiesis.api.deps import get_db_pool, get_k8s, get_runtime_config
from poiesis.api.exceptions import APIError, handle_api_exception
from poiesis.api.jwt_auth import JWTAuthenticator
from poiesis.api.routes import tasks as tasks_routes
from poiesis.api.settings import AuthzSettings, IssuerSettings
from poiesis.api.tes.models import TesState, TesTask
from poiesis.db.tasks import ListFilters, TaskScope

GOLDEN = Path(__file__).parent / "golden" / "authz"
PDP = "https://pdp.example.org/access/v1/evaluation"
TASKS = "/ga4gh/tes/v1/tasks"
ENTITLEMENT = "eduperson_entitlement"
MEMBER = (
    "urn:geant:lifescience-ri.eu:group:example-vo:analysts#login.aai.lifescience-ri.eu"
)
SUBGROUPS = "urn:geant:lifescience-ri.eu:group:example-vo:"
TASK = {"executors": [{"image": "alpine", "command": ["true"]}]}
#: Owner ids (`issuer|subject`) of the fake issuer's alice and bob.
ALICE = f"{ISSUER}|alice"
BOB = f"{ISSUER}|bob"
#: The other owner in the golden requests, shared with the decision-service
#: side; owner ids are opaque, so any value other than the caller's works.
GOLDEN_BOB = "bob"

Decide = Callable[[dict[str, Any]], Any]


# -- fakes ----------------------------------------------------------------------


class Store:
    """In-memory stand-in for `poiesis.db.tasks` and the cancel transition."""

    def __init__(self) -> None:
        """Start empty."""
        self.tasks: dict[str, tuple[str, TesTask]] = {}
        self.groups: dict[str, list[str]] = {}

    def add(
        self, owner: str, task_id: str, groups: list[str] | None = None, **fields: Any
    ) -> str:
        """Store a task of `owner` directly, shared with `groups`."""
        task = TesTask(id=task_id, state=TesState.RUNNING, executors=[], **fields)
        self.tasks[task_id] = (owner, task)
        self.groups[task_id] = groups or []
        return task_id

    async def create_task(
        self, _: Any, task: TesTask, owner: str, groups: Any = ()
    ) -> str:
        """Store a new task."""
        assert task.id is not None
        self.tasks[task.id] = (owner, task)
        self.groups[task.id] = list(groups)
        return task.id

    async def get_task_meta(self, _: Any, task_id: str) -> dict[str, Any] | None:
        """Return owner, state, tags and groups."""
        if task_id not in self.tasks:
            return None
        owner, task = self.tasks[task_id]
        assert task.state is not None
        return {
            "owner": owner,
            "state": task.state.value,
            "tags": task.tags or {},
            "groups": self.groups[task_id],
        }

    def visible(self, filters: ListFilters, task_id: str) -> bool:
        """Mirror the visibility clause of `poiesis.db.tasks.list_tasks`."""
        owner, task = self.tasks[task_id]
        if filters.owner in {None, owner}:
            return True
        scope = filters.scope
        if scope is None:
            return False
        tags = task.tags or {}
        return (
            (scope.owners is None or owner in scope.owners)
            and (
                scope.groups is None
                or bool(set(scope.groups) & set(self.groups[task_id]))
            )
            and (scope.tags is None or any(tags.get(k) == v for k, v in scope.tags))
        )

    async def get_task(self, _: Any, task_id: str, **kwargs: Any) -> TesTask | None:
        """Return the task, unfiltered."""
        assert kwargs.get("owner") is None
        return self.tasks[task_id][1] if task_id in self.tasks else None

    async def list_tasks(
        self, _: Any, filters: ListFilters, **__: Any
    ) -> tuple[list[TesTask], str | None]:
        """Page through tasks in insertion order, filtered by visibility."""
        rows = [
            task
            for task_id, (_, task) in self.tasks.items()
            if self.visible(filters, task_id)
        ]
        start = int(filters.page_token or 0)
        page = rows[start : start + filters.page_size]
        more = start + filters.page_size < len(rows)
        return page, str(start + filters.page_size) if more else None

    async def mark_canceling(self, _: Any, task_id: str) -> bool:
        """Move the task to CANCELING."""
        self.tasks[task_id][1].state = TesState.CANCELING
        return True


class K8s:
    """Accepts every Job and PVC."""

    async def create_job(self, *_: Any) -> Any:
        """Return a created Job."""
        return SimpleNamespace(metadata=SimpleNamespace(uid="uid", name="job"))

    async def create_pvc(self, *_: Any) -> None:
        """Accept the PVC."""

    async def delete_job(self, *_: Any) -> None:
        """Accept the delete."""


class Pdp:
    """A recording stub decision service with scripted decisions."""

    def __init__(self) -> None:
        """Allow everything until told otherwise."""
        self.decide: Decide = lambda _: {"decision": True}
        self.requests: list[httpx.Request] = []

    @property
    def bodies(self) -> list[dict[str, Any]]:
        """The JSON bodies received so far."""
        return [json.loads(r.content) for r in self.requests]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Answer with the scripted decision (a dict, response or exception)."""
        self.requests.append(request)
        answer = self.decide(json.loads(request.content))
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)


def per_action(tes: dict[str, Any] | None = None, **decisions: bool) -> Decide:
    """Decide by `<action>` or `<action>_<resource id>`, default deny.

    `tes` is added to every answer as `context.tes`.
    """

    def decide(body: dict[str, Any]) -> Any:
        action, resource = body["action"]["name"], body["resource"]["id"]
        key = f"{action}_{resource}"
        answer: dict[str, Any] = {
            "decision": decisions.get(key, decisions.get(action, False))
        }
        if tes is not None:
            answer["context"] = {"tes": tes}
        return answer

    return decide


# -- fixtures --------------------------------------------------------------------


class Pool:
    """Stands in for the asyncpg pool; counts and tracks held connections."""

    def __init__(self) -> None:
        """Start with nothing acquired."""
        self.acquired = 0
        self.held = 0

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        """Hand out a dummy connection (the store fakes ignore it)."""
        self.acquired += 1
        self.held += 1
        try:
            yield None
        finally:
            self.held -= 1


class Env:
    """A Poiesis API under test, with its fakes."""

    def __init__(self, issuer: Issuer, pdp: Pdp, store: Store) -> None:
        """Wire the fakes."""
        self.issuer, self.pdp, self.store = issuer, pdp, store
        self.claims: dict[str, Any] = {
            "azp": "tes-client",
            "scope": "openid eduperson_entitlement",
            ENTITLEMENT: [MEMBER],
        }

    def start(
        self, issuer: dict[str, Any] | None = None, **settings: Any
    ) -> TestClient:
        """Build the app with `AuthzSettings(**settings)`; return a client.

        `issuer` adds (camelCase) settings to the fake issuer's entry.
        """
        entry = IssuerSettings.model_validate(
            {"issuer": ISSUER, "audience": AUDIENCE, "userinfo": {"enabled": True}}
            | (issuer or {})
        )
        oidc = JWTAuthenticator([entry])
        asyncio.run(oidc.start())
        app = FastAPI()
        app.add_exception_handler(APIError, handle_api_exception)
        app.add_middleware(audit.RequestIdMiddleware)
        app.include_router(tasks_routes.router, prefix="/ga4gh/tes/v1")
        app.state.authenticators = [oidc]
        app.state.authz = Authz(AuthzSettings(**settings), [entry])
        self.pool = Pool()
        app.dependency_overrides[get_db_pool] = lambda: self.pool
        app.dependency_overrides[get_k8s] = K8s
        app.dependency_overrides[get_runtime_config] = lambda: SimpleNamespace(
            taskpod_namespace="ns"
        )
        token = self.issuer.token(**self.claims)
        return TestClient(app, headers={"Authorization": f"Bearer {token}"})

    def pdp_on(
        self, issuer: dict[str, Any] | None = None, **settings: Any
    ) -> TestClient:
        """Start with the stub decision service and the entitlement allowlisted."""
        defaults = {
            "decision_service_url": PDP,
            "decision_service_claims": (ENTITLEMENT,),
        }
        return self.start(issuer, **defaults | settings)


def rule(name: str = ENTITLEMENT, **match: Any) -> dict[str, Any]:
    """Return issuer settings with a `requiredClaim` on `name`."""
    return {"requiredClaim": {"name": name} | match}


@pytest.fixture
def env(issuer: Issuer, network: Network, monkeypatch: pytest.MonkeyPatch) -> Env:
    """A fresh environment with an empty store and a permissive stub."""
    pdp, store = Pdp(), Store()
    network.hosts["pdp.example.org"] = pdp
    for name in ("create_task", "get_task_meta", "get_task", "list_tasks"):
        monkeypatch.setattr(tasks_routes.tasks_db, name, getattr(store, name))
    monkeypatch.setattr(tasks_routes.state_db, "mark_canceling", store.mark_canceling)
    monkeypatch.setattr(
        tasks_routes, "build_taskpod_job", lambda *_: (SimpleNamespace(), None)
    )
    monkeypatch.setattr(tasks_routes, "attach_pvc_owner", lambda *_: None)
    return Env(issuer, pdp, store)


BOB_TASK = "00000000-0000-4000-8000-00000000000b"
ALICE_TASK = "00000000-0000-4000-8000-00000000000a"
MISSING = "00000000-0000-4000-8000-0000000000ff"


def golden(name: str, body: dict[str, Any]) -> None:
    """Assert `body` equals the golden request `name` (written if missing).

    The caller's identity is replaced by the shared placeholders
    (`{{subject_id}}`, `{{iss}}`, `{{sub}}`, `{{client_id}}`), which each
    TES fills in with its own values.
    """
    subject = body["subject"]
    subject["id"] = "{{subject_id}}"
    for key in ("iss", "sub", "client_id"):
        subject["properties"][key] = "{{%s}}" % key  # noqa: UP031
    path = GOLDEN / f"{name}.json"
    if not path.exists() or os.environ.get("POIESIS_WRITE_GOLDEN"):
        data = json.loads(path.read_text()) if path.exists() else {"name": name}
        data["request"] = body
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        pytest.fail(f"wrote {path}; review it and rerun")
    assert body == json.loads(path.read_text())["request"]


# -- URL stripping ---------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    json.loads((GOLDEN / "url-stripping.json").read_text()),
    ids=lambda case: case["input"],
)
def test_strip_url(case: dict[str, Any]) -> None:
    """URLs lose userinfo, query and fragment by the shared string rules."""
    assert strip_url(case["input"]) == case["expected"]


# -- claim rule ------------------------------------------------------------------


def gate(claims: dict[str, Any], name: str = ENTITLEMENT, **match: Any) -> bool:
    """Whether the issuer's claim rule on `name` admits a principal with `claims`.

    Without `match` the issuer has no rule.
    """
    entry = {"issuer": ISSUER, "audience": AUDIENCE} | (
        rule(name, **match) if match else {}
    )
    issuers = [IssuerSettings.model_validate(entry)]
    try:
        principal = Principal(issuer=ISSUER, subject="a", via="oidc", claims=claims)
        Authz(AuthzSettings(), issuers).gate(principal)
    except APIError:
        return False
    return True


class TestClaimRule:
    """A claim rule: exact values or raw prefixes, on a string or list."""

    @pytest.mark.parametrize(
        ("value", "admitted"),
        [
            ("a", True),
            (["x", "a"], True),
            (["x"], False),
            ("A", False),
            ([], False),
            (["a", 1], False),
            ({"a": "a"}, False),
            (None, False),
        ],
    )
    def test_values(self, value: Any, *, admitted: bool) -> None:
        """Exact values match a string or any list element; other types deny."""
        assert gate({ENTITLEMENT: value}, values=["a"]) is admitted

    @pytest.mark.parametrize(
        ("value", "admitted"),
        [("urn:g:vo:sub#x", True), ("urn:g:vox#x", False), ("urn:g:vo#x", False)],
    )
    def test_prefixes(self, value: str, *, admitted: bool) -> None:
        """Prefixes are raw: the delimiter is part of the prefix."""
        assert gate({ENTITLEMENT: [value]}, prefixes=["urn:g:vo:"]) is admitted

    def test_off_without_rule(self) -> None:
        """An issuer without a rule admits its principals."""
        assert gate({})

    @pytest.mark.parametrize(
        ("name", "claims"),
        [
            ("ctx.groups", {"ctx": {"groups": ["a"]}}),
            ("https://e.org/groups", {"https://e.org/groups": ["a"]}),
        ],
    )
    def test_names(self, name: str, claims: dict[str, Any]) -> None:
        """The claim is found by dotted path or by exact (URI) name."""
        assert gate(claims, name, values=["a"])


def judge(
    network: Network, other_rule: dict[str, Any], *tokens: tuple[str, dict[str, Any]]
) -> list[bool]:
    """Authenticate tokens of two issuers and gate them; whether each passes.

    The fake issuer requires the entitlement `MEMBER`; the other issuer
    has `other_rule` (camelCase settings). `tokens` are (issuer, claims).
    """
    fakes = {
        ISSUER: network.add(Issuer()),
        OTHER_ISSUER: network.add(Issuer(OTHER_ISSUER)),
    }
    entries = [
        IssuerSettings.model_validate(
            {"issuer": ISSUER, "audience": AUDIENCE} | rule(values=[MEMBER])
        ),
        IssuerSettings.model_validate(
            {"issuer": OTHER_ISSUER, "audience": AUDIENCE} | other_rule
        ),
    ]
    authz = Authz(AuthzSettings(), entries)

    async def main() -> list[bool]:
        oidc = JWTAuthenticator(entries)
        await oidc.start()
        results = []
        try:
            for iss, claims in tokens:
                token = fakes[iss].token(**claims)
                request: Any = SimpleNamespace(
                    headers={"authorization": f"Bearer {token}"}
                )
                principal = await oidc.authenticate(request)
                assert principal is not None
                try:
                    authz.gate(principal)
                except APIError:
                    results.append(False)
                else:
                    results.append(True)
        finally:
            await oidc.aclose()
        return results

    return asyncio.run(main())


class TestRulePerIssuer:
    """A claim rule binds to its issuer: (`iss`, claim, value), never the value."""

    member: ClassVar = {ENTITLEMENT: [MEMBER]}

    def test_other_issuer_copying_the_value(self, network: Network) -> None:
        """Another issuer's token with the value is judged by that issuer's rule.

        The other issuer has no rule: its tokens are admitted with or
        without the value. With a rule of its own, the copied value
        doesn't help.
        """
        assert judge(network, {}, (OTHER_ISSUER, self.member), (OTHER_ISSUER, {})) == [
            True,
            True,
        ]
        assert judge(
            network,
            rule(values=["urn:other"]),
            (OTHER_ISSUER, self.member),
            (OTHER_ISSUER, {ENTITLEMENT: ["urn:other"]}),
        ) == [False, True]

    def test_own_issuer(self, network: Network) -> None:
        """The rule's own issuer needs the value; others' values don't count."""
        assert judge(
            network,
            rule(values=["urn:other"]),
            (ISSUER, self.member),
            (ISSUER, {}),
            (ISSUER, {ENTITLEMENT: ["urn:other"]}),
        ) == [True, False, False]


# -- startup checks ---------------------------------------------------------------


@pytest.mark.parametrize(
    "settings",
    [{"decision_service_url": PDP}, {"decision_service_claims": ("g",)}],
)
def test_refused_without_auth(settings: dict[str, Any]) -> None:
    """Authorization settings with auth disabled refuse to start."""
    with pytest.raises(ValueError, match="auth is disabled"):
        AuthzSettings(**settings).validate_for(auth_enabled=False)


@pytest.mark.parametrize(
    ("claim_rule", "message"),
    [
        ({"name": "g"}, "values or prefixes"),
        ({"name": "g", "values": [], "prefixes": []}, "values or prefixes"),
        ({"values": ["a"]}, "name"),
        ({"name": "", "values": ["a"]}, "name"),
        ({"name": "g", "prefixes": [""]}, "must not be empty"),
        ({"name": "g", "values": ["a", ""]}, "must not be empty"),
        ({"name": "g", "values": ["a"], "value": "a"}, "value"),
    ],
    ids=[
        "no-values",
        "empty-lists",
        "no-name",
        "empty-name",
        "empty-prefix",
        "empty-value",
        "unknown-key",
    ],
)
def test_incomplete_rule_refused(claim_rule: dict[str, Any], message: str) -> None:
    """A rule needs a name and non-empty values or prefixes."""
    entry = {"issuer": ISSUER, "audience": AUDIENCE, "requiredClaim": claim_rule}
    with pytest.raises(ValueError, match=f"(?s)requiredClaim.*{message}"):
        IssuerSettings.model_validate(entry)


@pytest.mark.parametrize(
    "name",
    [
        "POIESIS_AUTHZ_REQUIRED_CLAIM_NAME",
        "POIESIS_AUTHZ_REQUIRED_CLAIM_VALUES",
        "POIESIS_AUTHZ_REQUIRED_CLAIM_PREFIXES",
    ],
)
def test_global_claim_rule_refused(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """A leftover global claim rule variable refuses to start, even empty.

    It matched claim values whichever issuer the token came from; the
    message names the per-issuer replacement.
    """
    monkeypatch.setenv(name, "")
    with pytest.raises(ValueError, match=rf"{name}.*auth\.issuers\[\]\.requiredClaim"):
        AuthzSettings()


@pytest.mark.parametrize(
    "settings",
    [
        {"decision_service_claims": ("g",)},
        {"decision_service_credential_file": "/run/credential"},
        {"decision_service_url": "ftp://pdp/x"},
        {"decision_service_url": "pdp.example.org/x"},
        {"decision_service_url": "https://"},
        {"decision_service_url": "http:///evaluation"},
        {"decision_service_url": "http://:80/"},
    ],
    ids=[
        "claims-only",
        "credential-only",
        "ftp",
        "no-scheme",
        "no-host",
        "empty-host",
        "port-only",
    ],
)
def test_decision_service_needs_http_url(settings: dict[str, Any]) -> None:
    """Decision service settings need an http(s) URL."""
    with pytest.raises(ValueError, match="DECISION_SERVICE_URL"):
        AuthzSettings(**settings).validate_for(auth_enabled=True)


def test_defaults_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing set is fine either way, and the timeout defaults to 2 s."""
    for name in os.environ:
        if name.startswith("POIESIS_AUTHZ_"):
            monkeypatch.delenv(name)
    settings = AuthzSettings()
    settings.validate_for(auth_enabled=False)
    assert settings.decision_service_timeout == 2  # noqa: PLR2004


@pytest.mark.parametrize("value", ["0", "-1", "soon", "nan", "inf"])
def test_timeout_invalid(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """A timeout that isn't a positive number of seconds refuses to start."""
    monkeypatch.setenv("POIESIS_AUTHZ_DECISION_SERVICE_TIMEOUT", value)
    with pytest.raises(ValueError, match="DECISION_SERVICE_TIMEOUT"):
        AuthzSettings()


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_timeout_argument_invalid(value: float) -> None:
    """The same holds when the settings are built in code."""
    with pytest.raises(ValueError, match="decision_service_timeout"):
        AuthzSettings(decision_service_timeout=value)


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Lists are JSON arrays (values may contain commas)."""
    monkeypatch.setenv("POIESIS_AUTHZ_DECISION_SERVICE_CLAIMS", '["a,b", "c"]')
    monkeypatch.setenv("POIESIS_AUTHZ_DECISION_SERVICE_TIMEOUT", "0.5")
    assert AuthzSettings().decision_service_claims == ("a,b", "c")
    assert AuthzSettings().decision_service_timeout == 0.5  # noqa: PLR2004
    monkeypatch.setenv("POIESIS_AUTHZ_DECISION_SERVICE_CLAIMS", "a,b")
    with pytest.raises(ValueError, match="not valid JSON"):
        AuthzSettings()
    monkeypatch.setenv("POIESIS_AUTHZ_DECISION_SERVICE_CLAIMS", '{"a": "b"}')
    with pytest.raises(TypeError, match="array of strings"):
        AuthzSettings()
    monkeypatch.setenv("POIESIS_AUTHZ_DECISION_SERVICE_CLAIMS", '["a", 1]')
    with pytest.raises(TypeError, match="array of strings"):
        AuthzSettings()


def test_lifespan_refuses_authz_without_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app refuses to start before touching the database."""
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    monkeypatch.setenv("POIESIS_AUTHZ_DECISION_SERVICE_URL", PDP)
    with (
        pytest.raises(ValueError, match="auth is disabled"),
        TestClient(app_module.create_app()),
    ):
        pass


def test_empty_credential_refused(tmp_path: Path) -> None:
    """An empty credential file refuses to start."""
    credential = tmp_path / "credential"
    credential.write_text("\n")
    settings = AuthzSettings(
        decision_service_url=PDP, decision_service_credential_file=str(credential)
    )
    with pytest.raises(ValueError, match="empty"):
        Authz(settings)


@pytest.mark.parametrize(
    ("url", "warns"),
    [
        ("http://pdp.authz.svc/e", True),
        ("http://127.0.0.1:8181/e", False),
        ("http://localhost/e", False),
        ("https://pdp/e", False),
    ],
)
def test_plain_http_warns(
    url: str, *, warns: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """Plain http to a non-loopback host only warns (transport is the mesh's)."""
    Authz(AuthzSettings(decision_service_url=url))
    assert ("plain http" in caplog.text) is warns


# -- conformance: no decision service ----------------------------------------------


def test_builtin_owner_rule(env: Env) -> None:
    """Without configuration: create allowed, others' tasks 404, list own."""
    client = env.start()
    env.store.add(BOB, BOB_TASK)
    own = client.post(TASKS, json=TASK).json()["id"]
    assert client.get(f"{TASKS}/{BOB_TASK}").status_code == 404  # noqa: PLR2004
    assert client.post(f"{TASKS}/{BOB_TASK}:cancel").status_code == 404  # noqa: PLR2004
    assert client.get(f"{TASKS}/{own}").status_code == 200  # noqa: PLR2004
    assert [t["id"] for t in client.get(TASKS).json()["tasks"]] == [own]
    assert env.pdp.requests == []


def _nulls(value: Any, path: str = "") -> list[str]:
    """Return the paths of every `null` in a JSON value."""
    if value is None:
        return [path]
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in _nulls(v, f"{path}.{k}")]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in _nulls(v, f"{path}[{i}]")]
    return []


@pytest.mark.parametrize("view", ["MINIMAL", "BASIC", "FULL"])
def test_responses_omit_null(env: Env, view: str) -> None:
    """Unset fields are left out, never `null` (py-tes can't parse it)."""
    client = env.start()
    own = client.post(TASKS, json=TASK).json()["id"]
    got = client.get(f"{TASKS}/{own}", params={"view": view})
    listed = client.get(TASKS, params={"view": view})
    assert got.status_code == listed.status_code == 200  # noqa: PLR2004
    assert got.json()["id"] == own
    assert [t["id"] for t in listed.json()["tasks"]] == [own]
    assert _nulls(got.json()) == []
    assert _nulls(listed.json()) == []


def test_server_assigned_fields(env: Env) -> None:
    """Without configuration too, client id, state, logs and time are ignored."""
    submitted = TASK | {
        "id": BOB_TASK,
        "state": "COMPLETE",
        "creation_time": "2000-01-01T00:00:00+0000",
        "logs": [{"logs": [], "outputs": []}],
    }
    task_id = env.start().post(TASKS, json=submitted).json()["id"]
    assert task_id != BOB_TASK
    task = env.store.tasks[task_id][1]
    assert task.state == TesState.QUEUED
    assert task.logs is None
    assert task.creation_time is not None
    assert not task.creation_time.startswith("2000")


def test_rule_only(env: Env) -> None:
    """A rule without a decision service and with no allowlist admits."""
    client = env.start(rule(prefixes=[SUBGROUPS]))
    assert client.post(TASKS, json=TASK).status_code == 200  # noqa: PLR2004


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", TASKS),
        ("GET", f"{TASKS}/{BOB_TASK}"),
        ("POST", f"{TASKS}/{BOB_TASK}:cancel"),
        ("GET", TASKS),
    ],
)
def test_rule_denies_before_decision(env: Env, method: str, path: str) -> None:
    """A failing rule gives 403 on every action; PDP and database untouched."""
    env.claims[ENTITLEMENT] = ["urn:geant:lifescience-ri.eu:group:other#x"]
    client = env.pdp_on(rule(prefixes=[SUBGROUPS]))
    env.store.add(BOB, BOB_TASK)
    assert client.request(method, path, json=TASK).status_code == 403  # noqa: PLR2004
    assert env.pdp.requests == []
    assert env.pool.acquired == 0


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", TASKS),
        ("GET", f"{TASKS}/{BOB_TASK}"),
        ("POST", f"{TASKS}/{BOB_TASK}:cancel"),
        ("GET", TASKS),
    ],
)
def test_no_connection_held_during_decision(
    env: Env, network: Network, method: str, path: str
) -> None:
    """No pooled connection is held while the decision service is asked."""
    client = env.pdp_on(sharing=True)
    stub = network.hosts["pdp.example.org"]
    held: list[int] = []

    def spy(request: httpx.Request) -> httpx.Response:
        held.append(env.pool.held)
        return stub(request)

    network.hosts["pdp.example.org"] = spy
    env.store.add(BOB, BOB_TASK)
    client.request(method, path, json=TASK)
    assert held
    assert set(held) == {0}


def test_rule_denies_service_client(env: Env) -> None:
    """A client-credentials token without the claim gets 403."""
    env.claims = {"azp": "service", "sub": "service-account"}
    client = env.start(rule(values=[MEMBER]))
    assert client.post(TASKS, json=TASK).status_code == 403  # noqa: PLR2004


# -- conformance: decision service --------------------------------------------------


def test_create(env: Env) -> None:
    """The create request is the golden one; the owner is the subject id."""
    submit = json.loads((GOLDEN / "create.json").read_text())["submit"]
    response = env.pdp_on().post(TASKS, json=submit)
    assert response.status_code == 200  # noqa: PLR2004
    task_id = response.json()["id"]
    assert task_id != submit["id"]
    owner, task = env.store.tasks[task_id]
    assert owner == ALICE
    assert task.state == TesState.QUEUED
    assert task.logs is None
    golden("create", env.pdp.bodies[0])
    request = env.pdp.requests[0]
    assert len(request.headers["x-request-id"]) == 36  # noqa: PLR2004 (a UUID)
    assert "authorization" not in request.headers


def test_create_ignores_client_headers(env: Env) -> None:
    """Identity comes from the token; the request id is generated."""
    client = env.pdp_on()
    client.headers.update({"X-Request-ID": "client-id", "X-User": "mallory"})
    client.post(TASKS, json=TASK | {"tags": {"owner": "mallory"}})
    request = env.pdp.requests[0]
    assert request.headers["x-request-id"] != "client-id"
    assert env.pdp.bodies[0]["subject"]["id"] == ALICE


def test_create_denied(env: Env) -> None:
    """A deny is a 403 and nothing is stored."""
    env.pdp.decide = per_action()
    assert env.pdp_on().post(TASKS, json=TASK).status_code == 403  # noqa: PLR2004
    assert env.store.tasks == {}


def test_rule_and_decision(env: Env) -> None:
    """Rule passes, decision denies: 403."""
    env.pdp.decide = per_action()
    client = env.pdp_on(rule(prefixes=[SUBGROUPS]))
    assert client.post(TASKS, json=TASK).status_code == 403  # noqa: PLR2004
    assert len(env.pdp.requests) == 1


def test_credential_file(env: Env, tmp_path: Path) -> None:
    """The optional PEP credential is sent as a bearer token."""
    credential = tmp_path / "credential"
    credential.write_text("pep-secret\n")
    env.pdp_on(decision_service_credential_file=str(credential)).post(TASKS, json=TASK)
    assert env.pdp.requests[0].headers["authorization"] == "Bearer pep-secret"


def test_get_foreign_allowed(env: Env) -> None:
    """With sharing on, the decision service may grant access to others' tasks."""
    env.store.add(GOLDEN_BOB, BOB_TASK, ["lab-alpha"], tags={"project": "x"})
    client = env.pdp_on(sharing=True)
    response = client.get(f"{TASKS}/{BOB_TASK}", params={"view": "BASIC"})
    assert response.status_code == 200  # noqa: PLR2004
    golden("get-other", env.pdp.bodies[0])


def test_get_and_cancel_denied(env: Env) -> None:
    """Denied get and cancel are 404 and leave the task alone."""
    env.pdp.decide = per_action()
    env.store.add(GOLDEN_BOB, BOB_TASK)
    client = env.pdp_on(sharing=True)
    assert client.get(f"{TASKS}/{BOB_TASK}").status_code == 404  # noqa: PLR2004
    assert client.post(f"{TASKS}/{BOB_TASK}:cancel").status_code == 404  # noqa: PLR2004
    assert env.store.tasks[BOB_TASK][1].state == TesState.RUNNING
    golden("cancel-other", env.pdp.bodies[1])
    assert env.pdp.bodies[2]["action"] == {"name": "GetTask", "properties": {}}


def test_cancel_denied_but_readable(env: Env) -> None:
    """Readable but not cancellable: 403."""
    env.pdp.decide = per_action(GetTask=True)
    env.store.add(BOB, BOB_TASK)
    response = env.pdp_on(sharing=True).post(f"{TASKS}/{BOB_TASK}:cancel")
    assert response.status_code == 403  # noqa: PLR2004


def test_cancel_allowed(env: Env) -> None:
    """An allowed cancel moves the task to CANCELING."""
    env.store.add(ALICE, ALICE_TASK)
    response = env.pdp_on().post(f"{TASKS}/{ALICE_TASK}:cancel")
    assert response.status_code == 200  # noqa: PLR2004
    assert env.store.tasks[ALICE_TASK][1].state == TesState.CANCELING
    assert [body["action"]["name"] for body in env.pdp.bodies] == ["CancelTask"]


@pytest.mark.parametrize("allowed", [True, False])
def test_missing_task(env: Env, *, allowed: bool) -> None:
    """With sharing on, a missing task is 404 whatever the decision, but asked.

    Cancel always asks GetTask as well (case 11c): an allowed cancel of a
    missing task must not cost fewer calls than a denied one.
    """
    env.pdp.decide = per_action(GetTask=allowed, CancelTask=allowed)
    client = env.pdp_on(sharing=True)
    assert client.get(f"{TASKS}/{MISSING}").status_code == 404  # noqa: PLR2004
    assert client.post(f"{TASKS}/{MISSING}:cancel").status_code == 404  # noqa: PLR2004
    golden("get-missing", env.pdp.bodies[0])
    cancel = env.pdp.bodies[1:]
    assert [body["action"] for body in cancel] == [
        {"name": name, "properties": {}} for name in ("CancelTask", "GetTask")
    ]
    assert all(body["resource"]["properties"] == {} for body in cancel)
    ids = {request.headers["x-request-id"] for request in env.pdp.requests}
    assert len(ids) == len(env.pdp.requests)


def test_legacy_task_matches_nobody(env: Env) -> None:
    """Tasks from before owners were stamped are nobody's; sent as they are."""
    env.store.add("__legacy__", BOB_TASK)
    assert env.start().get(f"{TASKS}/{BOB_TASK}").status_code == 404  # noqa: PLR2004
    env.pdp_on(sharing=True).get(f"{TASKS}/{BOB_TASK}")
    assert env.pdp.bodies[0]["resource"]["properties"]["owner"] == "__legacy__"


def test_subject_is_owner(env: Env) -> None:
    """`subject.id` is the owner id; `iss` and `sub` are the issuer and `sub`."""
    env.pdp_on().post(TASKS, json=TASK)
    subject = env.pdp.bodies[0]["subject"]
    assert subject["id"] == ALICE
    assert subject["properties"]["iss"] == ISSUER
    assert subject["properties"]["sub"] == "alice"
    assert subject["properties"]["via"] == "oidc"
    assert "actor" not in subject["properties"]
    assert "credential_id" not in subject["properties"]


# -- delegation ----------------------------------------------------------------------


def test_builtin_rule_refuses_actor(env: Env) -> None:
    """Without a decision service, a delegated token (`act`) gets 403."""
    env.claims["act"] = {"sub": "engine"}
    client = env.start()
    env.store.add(ALICE, ALICE_TASK)
    for method, path in (("POST", TASKS), ("GET", f"{TASKS}/{ALICE_TASK}")):
        response = client.request(method, path, json=TASK)
        assert response.status_code == 403  # noqa: PLR2004
        assert "decision service" in response.json()["message"]
    assert env.store.tasks.keys() == {ALICE_TASK}


def test_builtin_rule_accepts_listed_actor(env: Env) -> None:
    """A listed actor of the token's issuer acts for the subject, as the owner."""
    env.claims["act"] = {"sub": "gateway"}
    client = env.start({"actors": ["portal", "gateway"]})
    env.store.add(ALICE, ALICE_TASK)
    env.store.add(BOB, BOB_TASK)
    created = client.post(TASKS, json=TASK)
    assert created.status_code == 200  # noqa: PLR2004
    assert env.store.tasks[created.json()["id"]][0] == ALICE
    assert client.get(f"{TASKS}/{ALICE_TASK}").status_code == 200  # noqa: PLR2004
    # Still the owner rule: the actor gets no more than the subject.
    assert client.get(f"{TASKS}/{BOB_TASK}").status_code == 404  # noqa: PLR2004


@pytest.mark.parametrize(
    "act",
    [
        {"sub": "engine"},
        {"sub": "gateway", "iss": OTHER_ISSUER},
        {"sub": "gateway", "iss": f"{ISSUER}/"},
    ],
    ids=["unlisted", "other-issuer", "near-issuer"],
)
def test_builtin_rule_refuses_other_actors(env: Env, act: dict[str, Any]) -> None:
    """An unlisted actor, or a listed id of another issuer, gets 403."""
    env.claims["act"] = act
    client = env.start({"actors": ["gateway"]})
    response = client.post(TASKS, json=TASK)
    assert response.status_code == 403  # noqa: PLR2004
    assert "decision service" in response.json()["message"]
    assert env.store.tasks == {}


@pytest.mark.parametrize("allowed", [True, False])
def test_listed_actor_with_decision_service(env: Env, *, allowed: bool) -> None:
    """With a decision service, it decides for listed actors as for any other."""
    env.claims["act"] = {"sub": "gateway"}
    env.pdp.decide = per_action(CreateTask=allowed)
    response = env.pdp_on({"actors": ["gateway"]}).post(TASKS, json=TASK)
    assert response.status_code == (200 if allowed else 403)
    subject = env.pdp.bodies[0]["subject"]
    assert subject["properties"]["actor"] == {"iss": ISSUER, "sub": "gateway"}


@pytest.mark.parametrize(
    ("act", "actor"),
    [
        ({"sub": "engine"}, {"iss": ISSUER, "sub": "engine"}),
        (
            {"iss": "https://ci.example.org", "sub": "repo:x", "act": {"sub": "y"}},
            {"iss": "https://ci.example.org", "sub": "repo:x"},
        ),
    ],
    ids=["issuer-default", "own-issuer-nested-ignored"],
)
def test_actor_sent_to_decision_service(
    env: Env, act: dict[str, Any], actor: dict[str, str]
) -> None:
    """The decision service gets the actor next to the subject and decides."""
    env.claims["act"] = act
    assert env.pdp_on().post(TASKS, json=TASK).status_code == 200  # noqa: PLR2004
    subject = env.pdp.bodies[0]["subject"]
    assert subject["id"] == ALICE
    assert subject["properties"]["actor"] == actor


@pytest.mark.parametrize(
    "answer",
    [
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("down"),
        httpx.Response(500, json={"decision": True}),
        httpx.Response(200, content=b"not json"),
        {"decision": "true"},
        {"allow": True},
        ["decision", True],
        {"decision": True, "context": {"tes": {"scope": {"state": ["RUNNING"]}}}},
        {"decision": True, "context": {"tes": {"obligations": "audit"}}},
    ],
    ids=[
        "timeout",
        "down",
        "500",
        "not-json",
        "string",
        "missing",
        "not-object",
        "unknown-scope-dimension",
        "obligations-not-list",
    ],
)
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", TASKS),
        ("GET", f"{TASKS}/{BOB_TASK}"),
        ("GET", f"{TASKS}/{MISSING}"),
        ("POST", f"{TASKS}/{BOB_TASK}:cancel"),
        ("POST", f"{TASKS}/{MISSING}:cancel"),
        ("GET", TASKS),
    ],
)
def test_decision_service_failure(
    env: Env, answer: Any, method: str, path: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Any failure is a 503 with Retry-After, logged; nothing is executed."""
    env.pdp.decide = lambda _: answer
    env.store.add(BOB, BOB_TASK)
    response = env.pdp_on(sharing=True).request(method, path, json=TASK)
    assert response.status_code == 503  # noqa: PLR2004
    assert response.headers["retry-after"] == "1"
    assert "Decision service failed" in caplog.text
    assert len(env.store.tasks) == 1
    assert env.store.tasks[BOB_TASK][1].state == TesState.RUNNING


@pytest.mark.parametrize(
    ("task_id", "cancel"),
    [(BOB_TASK, False), (MISSING, False), (MISSING, True)],
)
def test_failure_on_second_cancel_call(env: Env, task_id: str, *, cancel: bool) -> None:
    """A failure of the GetTask call after a cancel is a 503 too.

    GetTask follows a denied cancel, and any cancel of a missing task.
    """
    env.pdp.decide = lambda body: (
        {"decision": cancel}
        if body["action"]["name"] == "CancelTask"
        else httpx.Response(500)
    )
    env.store.add(BOB, BOB_TASK)
    response = env.pdp_on(sharing=True).post(f"{TASKS}/{task_id}:cancel")
    assert response.status_code == 503  # noqa: PLR2004


def test_decision_service_too_slow(env: Env, network: Network) -> None:
    """The timeout bounds the whole call."""

    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json={"decision": True})

    network.hosts["pdp.example.org"] = slow  # type: ignore[assignment]
    client = env.pdp_on(decision_service_timeout=0.05)
    assert client.post(TASKS, json=TASK).status_code == 503  # noqa: PLR2004


def page_through(client: TestClient, page_size: int) -> list[list[str]]:
    """Return the task ids of every page."""
    pages, token = [], None
    while True:
        params: dict[str, Any] = {"page_size": page_size}
        if token:
            params["page_token"] = token
        body = client.get(TASKS, params=params).json()
        pages.append([t["id"] for t in body["tasks"]])
        token = body.get("next_page_token")
        if not token:
            return pages


def fill(store: Store) -> tuple[list[str], list[str]]:
    """Store three tasks each of alice and bob; return their ids."""
    alice = [
        store.add(ALICE, f"00000000-0000-4000-8000-0000000000a{i}") for i in range(3)
    ]
    bob = [store.add(BOB, f"00000000-0000-4000-8000-0000000000b{i}") for i in range(3)]
    return alice, bob


def test_list_all(env: Env) -> None:
    """Sharing on, `all` allowed: every task, complete, no duplicates."""
    alice, bob = fill(env.store)
    env.pdp.decide = per_action(ListTasks_all=True)
    pages = page_through(env.pdp_on(sharing=True), page_size=2)
    assert len(pages) == 3  # noqa: PLR2004
    assert sorted(i for page in pages for i in page) == sorted(alice + bob)
    golden("list-all", env.pdp.bodies[0])


@pytest.mark.parametrize("sharing", [False, True])
def test_list_own(env: Env, *, sharing: bool) -> None:
    """Only `own` allowed: own tasks, complete, pages of at most 2."""
    alice, _ = fill(env.store)
    env.pdp.decide = per_action(ListTasks_own=True)
    pages = page_through(env.pdp_on(sharing=sharing), page_size=2)
    assert all(len(page) <= 2 for page in pages)  # noqa: PLR2004
    assert sorted(i for page in pages for i in page) == sorted(alice)
    golden("list-own", next(b for b in env.pdp.bodies if b["resource"]["id"] == "own"))


def test_list_scope_per_page(env: Env) -> None:
    """The scope is evaluated again for every page."""
    alice, _ = fill(env.store)
    env.pdp.decide = per_action(ListTasks_all=True)
    client = env.pdp_on(sharing=True)
    token = client.get(TASKS, params={"page_size": 2}).json()["next_page_token"]
    env.pdp.decide = per_action(ListTasks_own=True)
    page = client.get(TASKS, params={"page_size": 6, "page_token": token}).json()
    assert {t["id"] for t in page["tasks"]} <= set(alice)


@pytest.mark.parametrize(("sharing", "calls"), [(False, 1), (True, 2)])
def test_list_denied(env: Env, *, sharing: bool, calls: int) -> None:
    """Neither set allowed (sharing on) or `own` denied (off): 403."""
    env.pdp.decide = per_action()
    assert env.pdp_on(sharing=sharing).get(TASKS).status_code == 403  # noqa: PLR2004
    assert len(env.pdp.requests) == calls


def test_claims_allowlist(env: Env) -> None:
    """Only allowlisted claims reach the PDP; never the token."""
    env.claims |= {"email": "alice@example.org"}
    token = env.start().headers["Authorization"].removeprefix("Bearer ")
    env.pdp_on().post(TASKS, json=TASK)
    subject = env.pdp.bodies[0]["subject"]
    assert subject["properties"]["claims"] == {ENTITLEMENT: [MEMBER]}
    assert token not in env.pdp.requests[0].content.decode()


def test_userinfo_claims(env: Env) -> None:
    """Userinfo fills claims the token lacks; the token wins when both have one."""
    env.issuer.userinfo = {"groups": [MEMBER], ENTITLEMENT: ["other"]}
    client = env.pdp_on(
        rule("groups", values=[MEMBER]),
        decision_service_claims=(ENTITLEMENT, "groups"),
    )
    assert client.post(TASKS, json=TASK).status_code == 200  # noqa: PLR2004
    claims = env.pdp.bodies[0]["subject"]["properties"]["claims"]
    assert claims == {ENTITLEMENT: [MEMBER], "groups": [MEMBER]}


# -- tes-authzen/2: rich decisions -----------------------------------------------


def _scope_json(scope: TaskScope | None) -> dict[str, Any] | None:
    """Return `scope` as in the golden response cases (`tags` as pairs)."""
    if scope is None:
        return None
    return {
        name: [list(value) if name == "tags" else value for value in values]
        for name, values in (
            ("owners", scope.owners),
            ("groups", scope.groups),
            ("tags", scope.tags),
        )
        if values is not None
    }


@pytest.mark.parametrize(
    "case",
    json.loads((GOLDEN / "responses.json").read_text()),
    ids=lambda case: case["name"],
)
def test_response(case: dict[str, Any]) -> None:
    """Responses are read by the shared cases; malformed ones are refused.

    `allow` is the effective decision, after obligations.
    """
    expect = case["expect"]
    if expect.get("malformed"):
        with pytest.raises(ValueError, match="."):
            parse_decision(case["response"])
        return
    decision = parse_decision(case["response"])
    assert (decision.allow and not decision.obligations) is expect["allow"]
    assert _scope_json(decision.scope) == expect.get("scope")
    assert list(decision.groups) == expect.get("groups", [])


def test_plain_decision_service(env: Env) -> None:
    """A plain yes/no decision service works for every operation, unchanged."""
    client = env.pdp_on()
    own = client.post(TASKS, json=TASK).json()["id"]
    assert client.get(f"{TASKS}/{own}").status_code == 200  # noqa: PLR2004
    assert [t["id"] for t in client.get(TASKS).json()["tasks"]] == [own]
    assert client.post(f"{TASKS}/{own}:cancel").status_code == 200  # noqa: PLR2004
    assert [b["action"]["name"] for b in env.pdp.bodies] == [
        "CreateTask",
        "GetTask",
        "ListTasks",
        "CancelTask",
    ]
    assert env.store.groups[own] == []


def authz_logs(caplog: pytest.LogCaptureFixture) -> list[Any]:
    """Return the records logged by `poiesis.api.authz`."""
    return [r for r in caplog.records if r.name == "poiesis.api.authz"]


def test_obligation_denies(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    """An allow with an unknown obligation is a deny, logged with its names."""
    env.pdp.decide = lambda _: {
        "decision": True,
        "context": {"tes": {"obligations": ["log-access", "notify-pi"]}},
    }
    env.store.add(ALICE, ALICE_TASK)
    client = env.pdp_on()
    assert client.post(TASKS, json=TASK).status_code == 403  # noqa: PLR2004
    assert client.get(TASKS).status_code == 403  # noqa: PLR2004
    # A denied get is a 404, as for any deny.
    assert client.get(f"{TASKS}/{ALICE_TASK}").status_code == 404  # noqa: PLR2004
    assert env.store.tasks.keys() == {ALICE_TASK}
    warnings = [r for r in authz_logs(caplog) if r.levelname == "WARNING"]
    assert len(warnings) == 3  # noqa: PLR2004
    assert all("['log-access', 'notify-pi']" in r.getMessage() for r in warnings)


def test_advice_ignored(env: Env) -> None:
    """Advice doesn't change the decision."""
    env.pdp.decide = lambda _: {
        "decision": True,
        "context": {"tes": {"advice": ["consider-quota"]}},
    }
    assert env.pdp_on().post(TASKS, json=TASK).status_code == 200  # noqa: PLR2004


def test_reason_logged_not_returned(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    """The reason is logged with the decision, never sent to the client."""
    reason = "not a member of project x"
    env.pdp.decide = lambda _: {
        "decision": False,
        "context": {"tes": {"reason": reason}},
    }
    response = env.pdp_on().post(TASKS, json=TASK)
    assert response.status_code == 403  # noqa: PLR2004
    assert reason not in response.text
    assert repr(reason) in caplog.text


@pytest.mark.parametrize(
    "tes",
    [[], {"scope": {"owners": "x"}}, {"groups": [1]}, {"reason": 1}],
    ids=["tes-list", "owners-string", "groups-number", "reason-number"],
)
def test_malformed_context_is_failure(
    env: Env, tes: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Wrong types in `context.tes` are a 503, like a failed decision service."""
    env.pdp.decide = lambda _: {"decision": True, "context": {"tes": tes}}
    response = env.pdp_on().post(TASKS, json=TASK)
    assert response.status_code == 503  # noqa: PLR2004
    assert response.headers["retry-after"] == "1"
    assert "Decision service failed (invalid response" in caplog.text
    assert env.store.tasks == {}


# -- sharing ------------------------------------------------------------------------


@pytest.mark.parametrize("sharing", [False, True])
def test_create_groups_only_with_sharing(env: Env, *, sharing: bool) -> None:
    """The decision's groups are stored with sharing on only, never the claims."""
    env.claims["groups"] = ["community"]
    env.pdp.decide = per_action({"groups": ["lab-alpha", "lab-beta"]}, CreateTask=True)
    client = env.pdp_on(sharing=sharing, decision_service_claims=("groups",))
    task_id = client.post(TASKS, json=TASK).json()["id"]
    assert env.store.groups[task_id] == (["lab-alpha", "lab-beta"] if sharing else [])


def test_create_groups_absent(env: Env) -> None:
    """With sharing on and no groups in the decision, the task has none."""
    env.claims["groups"] = ["community"]
    task_id = env.pdp_on(sharing=True).post(TASKS, json=TASK).json()["id"]
    assert env.store.groups[task_id] == []


def test_sharing_off_lists_own_only(env: Env) -> None:
    """Sharing off: one `own` question; own tasks even if all would be allowed."""
    alice, _ = fill(env.store)
    env.pdp.decide = per_action(
        {"scope": {"owners": [BOB]}}, ListTasks_all=True, ListTasks_own=True
    )
    pages = page_through(env.pdp_on(), page_size=2)
    assert sorted(i for page in pages for i in page) == sorted(alice)
    assert {b["resource"]["id"] for b in env.pdp.bodies} == {"own"}
    assert len(env.pdp.requests) == len(pages)


@pytest.mark.parametrize(
    ("method", "task_id", "path"),
    [
        ("GET", BOB_TASK, f"{TASKS}/{BOB_TASK}"),
        ("GET", MISSING, f"{TASKS}/{MISSING}"),
        ("POST", BOB_TASK, f"{TASKS}/{BOB_TASK}:cancel"),
        ("POST", MISSING, f"{TASKS}/{MISSING}:cancel"),
    ],
)
def test_sharing_off_foreign_and_missing(
    env: Env, method: str, task_id: str, path: str
) -> None:
    """Sharing off: foreign and missing tasks are 404 without asking, alike."""
    env.store.add(BOB, BOB_TASK)
    response = env.pdp_on().request(method, path)
    assert response.status_code == 404  # noqa: PLR2004
    assert response.json()["message"] == f"task {task_id} not found"
    assert env.pdp.requests == []
    assert env.store.tasks[BOB_TASK][1].state == TesState.RUNNING


@pytest.mark.parametrize("allowed", [True, False])
def test_sharing_off_own_task_asked(env: Env, *, allowed: bool) -> None:
    """Sharing off: get and cancel of an own task are still asked."""
    env.store.add(ALICE, ALICE_TASK)
    env.pdp.decide = per_action(GetTask=allowed, CancelTask=allowed)
    client = env.pdp_on()
    status = 200 if allowed else 404
    assert client.get(f"{TASKS}/{ALICE_TASK}").status_code == status
    assert client.post(f"{TASKS}/{ALICE_TASK}:cancel").status_code == status
    asked = ["GetTask", "CancelTask"] + ([] if allowed else ["GetTask"])
    assert [b["action"]["name"] for b in env.pdp.bodies] == asked


def test_sharing_off_own_cancel_denied_but_readable(env: Env) -> None:
    """Sharing off: an own task readable but not cancellable is 403."""
    env.store.add(ALICE, ALICE_TASK)
    env.pdp.decide = per_action(GetTask=True)
    response = env.pdp_on().post(f"{TASKS}/{ALICE_TASK}:cancel")
    assert response.status_code == 403  # noqa: PLR2004


CAROL = f"{ISSUER}|carol"


def share(store: Store) -> dict[str, str]:
    """Store tasks of alice and others with groups and tags; ids by name."""
    return {
        "alice": store.add(ALICE, "00000000-0000-4000-8000-0000000000a0"),
        "bob-alpha": store.add(
            BOB, "00000000-0000-4000-8000-0000000000b0", ["lab-alpha"]
        ),
        "bob-x": store.add(
            BOB, "00000000-0000-4000-8000-0000000000b1", tags={"project": "x"}
        ),
        "bob-alpha-y": store.add(
            BOB,
            "00000000-0000-4000-8000-0000000000b2",
            ["lab-alpha", "lab-beta"],
            tags={"project": "y"},
        ),
        "carol-alpha": store.add(
            CAROL, "00000000-0000-4000-8000-0000000000c0", ["lab-alpha"]
        ),
        "carol-z": store.add(
            CAROL, "00000000-0000-4000-8000-0000000000c1", tags={"project": "z"}
        ),
    }


@pytest.mark.parametrize(
    ("scope", "shared"),
    [
        (None, []),
        ({}, []),
        ({"owners": [BOB]}, ["bob-alpha", "bob-x", "bob-alpha-y"]),
        ({"groups": ["lab-alpha"]}, ["bob-alpha", "bob-alpha-y", "carol-alpha"]),
        ({"groups": ["lab-beta", "lab-gamma"]}, ["bob-alpha-y"]),
        ({"tags": {"project": ["x", "z"]}}, ["bob-x", "carol-z"]),
        ({"owners": [BOB], "groups": ["lab-alpha"]}, ["bob-alpha", "bob-alpha-y"]),
        ({"groups": ["lab-alpha"], "tags": {"project": ["y"]}}, ["bob-alpha-y"]),
        ({"owners": [BOB], "tags": {"project": ["z"]}}, []),
        ({"owners": [], "groups": ["lab-alpha"]}, []),
    ],
    ids=[
        "absent",
        "empty",
        "owners",
        "groups",
        "groups-any",
        "tags-any",
        "owners-and-groups",
        "groups-and-tags",
        "disjoint",
        "empty-dimension",
    ],
)
def test_sharing_on_own_and_scope(
    env: Env, scope: dict[str, Any] | None, shared: list[str]
) -> None:
    """Sharing on, `all` denied: own tasks and those of the `own` scope."""
    ids = share(env.store)
    tes = None if scope is None else {"scope": scope}
    env.pdp.decide = per_action(tes, ListTasks_own=True)
    pages = page_through(env.pdp_on(sharing=True), page_size=2)
    listed = sorted(i for page in pages for i in page)
    assert listed == sorted(ids[name] for name in ["alice", *shared])


def test_sharing_on_all(env: Env) -> None:
    """Sharing on, `all` allowed: every task, whatever the `own` scope."""
    ids = share(env.store)
    env.pdp.decide = per_action({"scope": {"owners": [BOB]}}, ListTasks_all=True)
    listed = env.pdp_on(sharing=True).get(TASKS).json()["tasks"]
    assert sorted(t["id"] for t in listed) == sorted(ids.values())


def test_sharing_on_scope_of_all_ignored(env: Env) -> None:
    """A scope on a denied `all` adds nothing; `own` decides."""
    ids = share(env.store)

    def decide(body: dict[str, Any]) -> Any:
        if body["resource"]["id"] == "all":
            scope = {"owners": [BOB]}
            return {"decision": False, "context": {"tes": {"scope": scope}}}
        return {"decision": True}

    env.pdp.decide = decide
    listed = env.pdp_on(sharing=True).get(TASKS).json()["tasks"]
    assert [t["id"] for t in listed] == [ids["alice"]]


def test_sharing_on_neither(env: Env) -> None:
    """Sharing on, neither set allowed: 403, even with a scope."""
    share(env.store)
    env.pdp.decide = per_action({"scope": {"owners": [BOB]}})
    assert env.pdp_on(sharing=True).get(TASKS).status_code == 403  # noqa: PLR2004


@pytest.mark.parametrize(("owners", "status"), [(2, 200), (3, 403)])
def test_max_owners(
    env: Env, owners: int, status: int, caplog: pytest.LogCaptureFixture
) -> None:
    """A scope naming more than `maxOwners` owners denies, logged as an error.

    Duplicates count once.
    """
    scope = {"owners": [f"owner-{i}" for i in range(owners)] + ["owner-0"]}
    env.pdp.decide = per_action({"scope": scope}, ListTasks_own=True)
    response = env.pdp_on(sharing=True, max_owners=2).get(TASKS)
    assert response.status_code == status
    errors = [r for r in authz_logs(caplog) if r.levelname == "ERROR"]
    assert len(errors) == (0 if status == 200 else 1)  # noqa: PLR2004
    assert all("authz.maxOwners (2)" in r.getMessage() for r in errors)


def test_sharing_needs_decision_service() -> None:
    """Sharing without a decision service refuses to start; it would do nothing."""
    with pytest.raises(ValueError, match="DECISION_SERVICE_URL"):
        AuthzSettings(sharing=True).validate_for(auth_enabled=True)
    with pytest.raises(ValueError, match="auth is disabled"):
        AuthzSettings(sharing=True).validate_for(auth_enabled=False)


@pytest.mark.parametrize(
    ("value", "sharing"),
    [
        ("", False),
        ("true", True),
        ("ON", True),
        ("1", True),
        ("false", False),
        ("no", False),
    ],
)
def test_sharing_from_env(
    monkeypatch: pytest.MonkeyPatch, value: str, *, sharing: bool
) -> None:
    """`POIESIS_AUTHZ_SHARING` is a boolean, off by default."""
    monkeypatch.setenv("POIESIS_AUTHZ_SHARING", value)
    assert AuthzSettings().sharing is sharing


@pytest.mark.parametrize("value", ["of", "enabled", "2", "yeah"])
def test_sharing_typo_refused(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """An unrecognised boolean refuses to start rather than guess."""
    monkeypatch.setenv("POIESIS_AUTHZ_SHARING", value)
    with pytest.raises(ValueError, match="POIESIS_AUTHZ_SHARING"):
        AuthzSettings()


def test_max_owners_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`POIESIS_AUTHZ_MAX_OWNERS` defaults to 1000 and must be at least 1."""
    monkeypatch.delenv("POIESIS_AUTHZ_MAX_OWNERS", raising=False)
    assert AuthzSettings().max_owners == 1000  # noqa: PLR2004
    monkeypatch.setenv("POIESIS_AUTHZ_MAX_OWNERS", "5")
    assert AuthzSettings().max_owners == 5  # noqa: PLR2004
    for value in ("0", "-1"):
        monkeypatch.setenv("POIESIS_AUTHZ_MAX_OWNERS", value)
        with pytest.raises(ValueError, match="max_owners"):
            AuthzSettings()
    monkeypatch.setenv("POIESIS_AUTHZ_MAX_OWNERS", "many")
    with pytest.raises(ValueError, match="POIESIS_AUTHZ_MAX_OWNERS"):
        AuthzSettings()


# -- built-in admin ------------------------------------------------------------------

ADMINS = "poiesis-admins"
#: The fake issuer's built-in admin rule.
ADMIN_RULE = {"admin": {"name": "groups", "values": [ADMINS]}}


def tasks_of(client: TestClient) -> list[str]:
    """The ids of the tasks the client lists."""
    return [t["id"] for t in client.get(TASKS).json()["tasks"]]


def test_admin_read_off_is_owner_only(env: Env) -> None:
    """By default an admin sees, gets and cancels their own tasks only."""
    env.claims["groups"] = [ADMINS]
    client = env.start(ADMIN_RULE)
    env.store.add(ALICE, ALICE_TASK)
    env.store.add(BOB, BOB_TASK)
    assert tasks_of(client) == [ALICE_TASK]
    assert client.get(f"{TASKS}/{BOB_TASK}").status_code == 404  # noqa: PLR2004
    assert client.post(f"{TASKS}/{BOB_TASK}:cancel").status_code == 404  # noqa: PLR2004
    assert env.store.tasks[BOB_TASK][1].state == TesState.RUNNING


def test_admin_read_on(env: Env) -> None:
    """With adminRead, an admin lists every task and gets and cancels any."""
    env.claims["groups"] = ["users", ADMINS]
    client = env.start(ADMIN_RULE, admin_read=True)
    env.store.add(ALICE, ALICE_TASK)
    env.store.add(BOB, BOB_TASK)
    assert sorted(tasks_of(client)) == sorted([ALICE_TASK, BOB_TASK])
    assert client.get(f"{TASKS}/{BOB_TASK}").status_code == 200  # noqa: PLR2004
    assert client.post(f"{TASKS}/{BOB_TASK}:cancel").status_code == 200  # noqa: PLR2004
    assert env.store.tasks[BOB_TASK][1].state == TesState.CANCELING
    assert client.get(f"{TASKS}/{MISSING}").status_code == 404  # noqa: PLR2004
    assert client.post(f"{TASKS}/{MISSING}:cancel").status_code == 404  # noqa: PLR2004
    assert env.pdp.requests == []


@pytest.mark.parametrize(
    "groups", [[], ["poiesis-admins-x"], ["/poiesis-admins"]], ids=str
)
def test_admin_read_on_non_admin(env: Env, groups: list[str]) -> None:
    """With adminRead, everyone else still sees their own tasks only."""
    env.claims["groups"] = groups
    client = env.start(ADMIN_RULE, admin_read=True)
    env.store.add(ALICE, ALICE_TASK)
    env.store.add(BOB, BOB_TASK)
    assert tasks_of(client) == [ALICE_TASK]
    assert client.get(f"{TASKS}/{BOB_TASK}").status_code == 404  # noqa: PLR2004


def admins(*entries: dict[str, Any], **settings: Any) -> Authz:
    """An `Authz` for issuer entries given as (camelCase) settings."""
    issuers = [
        IssuerSettings.model_validate({"audience": AUDIENCE} | entry)
        for entry in entries
    ]
    return Authz(AuthzSettings(**settings), issuers)


def principal(iss: str = ISSUER, via: str = "oidc", **claims: Any) -> Principal:
    """A principal of `iss` with `claims`."""
    return Principal(issuer=iss, subject="alice", via=via, claims=claims)


def test_admin_rule_per_issuer() -> None:
    """An admin rule binds to its issuer: another issuer's value doesn't count.

    Also not by namespace: a second issuer sharing the namespace has its
    own rule (here none).
    """
    authz = admins(
        {"issuer": ISSUER} | ADMIN_RULE,
        {"issuer": OTHER_ISSUER, "admin": {"name": "groups", "prefixes": ["ops:"]}},
        {"issuer": "https://renamed.example.org", "namespace": ISSUER},
    )
    assert authz.is_admin(principal(groups=[ADMINS]))
    assert authz.is_admin(principal(groups=ADMINS))
    assert not authz.is_admin(principal(groups=["ops:root"]))
    assert not authz.is_admin(principal(OTHER_ISSUER, groups=[ADMINS]))
    assert authz.is_admin(principal(OTHER_ISSUER, groups=["ops:root"]))
    renamed = principal("https://renamed.example.org", groups=[ADMINS])
    assert not authz.is_admin(renamed)


def test_admin_rule_api_key() -> None:
    """An API key is judged on its claims snapshot, under its issuer."""
    authz = admins({"issuer": ISSUER} | ADMIN_RULE)
    assert authz.is_admin(principal(via="apikey", groups=[ADMINS]))
    assert not authz.is_admin(principal(via="apikey", groups=["users"]))


def test_admin_rule_never_delegated() -> None:
    """A delegated token is never an admin, even with a listed actor."""
    authz = admins({"issuer": ISSUER, "actors": ["gateway"]} | ADMIN_RULE)
    delegated = Principal(
        issuer=ISSUER,
        subject="alice",
        via="oidc",
        actor=Actor(issuer=ISSUER, subject="gateway", listed=True),
        claims={"groups": [ADMINS]},
    )
    assert not authz.is_admin(delegated)


def test_delegated_admin_token_owner_only(env: Env) -> None:
    """A delegated admin token gets no admin powers, adminRead or not."""
    env.claims |= {"groups": [ADMINS], "act": {"sub": "gateway"}}
    client = env.start(ADMIN_RULE | {"actors": ["gateway"]}, admin_read=True)
    env.store.add(ALICE, ALICE_TASK)
    env.store.add(BOB, BOB_TASK)
    assert tasks_of(client) == [ALICE_TASK]
    assert client.get(f"{TASKS}/{BOB_TASK}").status_code == 404  # noqa: PLR2004
    assert client.post(f"{TASKS}/{BOB_TASK}:cancel").status_code == 404  # noqa: PLR2004


@pytest.mark.parametrize("sharing", [False, True])
def test_admin_ignored_with_decision_service(
    env: Env, caplog: pytest.LogCaptureFixture, *, sharing: bool
) -> None:
    """With a decision service, admin is its policy; the admin rule is ignored."""
    env.claims["groups"] = [ADMINS]
    env.pdp.decide = per_action(ListTasks_own=True, GetTask=True, CancelTask=True)
    client = env.pdp_on(ADMIN_RULE, admin_read=True, sharing=sharing)
    env.store.add(ALICE, ALICE_TASK)
    env.store.add(BOB, BOB_TASK)
    assert tasks_of(client) == [ALICE_TASK]
    if not sharing:
        assert client.get(f"{TASKS}/{BOB_TASK}").status_code == 404  # noqa: PLR2004
    authz: Authz = client.app.state.authz  # type: ignore[attr-defined]
    assert not authz.is_admin(principal(groups=[ADMINS]))
    warnings = [r.getMessage() for r in authz_logs(caplog) if r.levelname == "WARNING"]
    assert any("built-in admin settings" in w and ISSUER in w for w in warnings)


def test_admin_read_only_warns_with_decision_service(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`adminRead` alone with a decision service is also reported as ignored."""
    Authz(AuthzSettings(decision_service_url=PDP, admin_read=True))
    assert "built-in admin settings" in caplog.text
    assert "adminRead on" in caplog.text


def test_admin_read_without_admins_warns(caplog: pytest.LogCaptureFixture) -> None:
    """`adminRead` without any issuer's admin rule names nobody; it warns."""
    Authz(AuthzSettings(admin_read=True), [])
    assert "no issuer has an admin rule" in caplog.text
    caplog.clear()
    admins({"issuer": ISSUER} | ADMIN_RULE, admin_read=True)
    assert caplog.text == ""


@pytest.mark.parametrize(
    ("value", "admin_read"),
    [("", False), ("true", True), ("1", True), ("off", False)],
)
def test_admin_read_from_env(
    monkeypatch: pytest.MonkeyPatch, value: str, *, admin_read: bool
) -> None:
    """`POIESIS_AUTHZ_ADMIN_READ` is a boolean, off by default."""
    monkeypatch.setenv("POIESIS_AUTHZ_ADMIN_READ", value)
    assert AuthzSettings().admin_read is admin_read


@pytest.mark.parametrize("value", ["of", "enabled", "2"])
def test_admin_read_typo_refused(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """An unrecognised boolean refuses to start rather than guess."""
    monkeypatch.setenv("POIESIS_AUTHZ_ADMIN_READ", value)
    with pytest.raises(ValueError, match="POIESIS_AUTHZ_ADMIN_READ"):
        AuthzSettings()


def test_admin_read_needs_auth() -> None:
    """`adminRead` with auth disabled refuses to start; nobody could be admin."""
    with pytest.raises(ValueError, match="auth is disabled"):
        AuthzSettings(admin_read=True).validate_for(auth_enabled=False)
    AuthzSettings(admin_read=True).validate_for(auth_enabled=True)


@pytest.mark.parametrize(
    "rule",
    [{"name": "g"}, {"name": "", "values": ["a"]}, {"name": "g", "values": [""]}],
    ids=["no-values", "empty-name", "empty-value"],
)
def test_incomplete_admin_rule_refused(rule: dict[str, Any]) -> None:
    """An admin rule is checked like `requiredClaim`."""
    entry = {"issuer": ISSUER, "audience": AUDIENCE, "admin": rule}
    with pytest.raises(ValueError, match="admin"):
        IssuerSettings.model_validate(entry)


# -- audit log -------------------------------------------------------------------------


def audited(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    """The audit lines written so far (each must be JSON)."""
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def summary(line: dict[str, Any]) -> tuple[Any, ...]:
    """The event, outcome, decider and admin flag of a task audit line."""
    return line["event"], line["outcome"], line["decided_by"], line["admin"]


def test_audit_builtin(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    """Every task operation is one line: who, what, which task, the outcome.

    No token, and no claim value (the entitlement) appears.
    """
    client = env.start()
    env.store.add(BOB, BOB_TASK)
    own = client.post(TASKS, json=TASK).json()["id"]
    client.get(f"{TASKS}/{own}")
    client.get(f"{TASKS}/{BOB_TASK}")
    client.get(TASKS)
    client.post(f"{TASKS}/{MISSING}:cancel")
    out = capsys.readouterr().out
    token = client.headers["authorization"].removeprefix("Bearer ")
    assert token not in out
    assert MEMBER not in out
    lines = [json.loads(line) for line in out.splitlines()]
    assert [summary(line) for line in lines] == [
        ("task.create", "allow", "builtin", False),
        ("task.get", "allow", "builtin", False),
        ("task.get", "deny", "builtin", False),
        ("task.list", "allow", "builtin", False),
        ("task.cancel", "deny", "builtin", False),
    ]
    assert [line.get("task_id") for line in lines] == [
        own,
        own,
        BOB_TASK,
        None,
        MISSING,
    ]
    assert lines[3]["list_scope"] == "own"
    for line in lines:
        assert line["owner"] == ALICE
        assert line["issuer"] == ISSUER
        assert line["via"] == "oidc"
        assert line["client"] == "tes-client"
        assert not {"actor", "credential_id"} & line.keys()
    assert len({line["request_id"] for line in lines}) == len(lines)


def test_audit_admin(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    """What the admin rule alone allowed is flagged `admin`."""
    env.claims |= {"groups": [ADMINS], "jti": "token-1"}
    client = env.start(ADMIN_RULE, admin_read=True)
    env.store.add(ALICE, ALICE_TASK)
    env.store.add(BOB, BOB_TASK)
    client.get(TASKS)
    client.get(f"{TASKS}/{ALICE_TASK}")
    client.get(f"{TASKS}/{BOB_TASK}")
    client.post(f"{TASKS}/{BOB_TASK}:cancel")
    lines = audited(capsys)
    assert [summary(line) for line in lines] == [
        ("task.list", "allow", "builtin", True),
        ("task.get", "allow", "builtin", False),
        ("task.get", "allow", "builtin", True),
        ("task.cancel", "allow", "builtin", True),
    ]
    assert lines[0]["list_scope"] == "all"
    assert lines[3]["task_id"] == BOB_TASK
    assert {line["credential_id"] for line in lines} == {"token-1"}
    assert ADMINS not in json.dumps(lines)


def test_audit_decision_service(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    """Decisions of the service are `decision_service`; a create deny has no id."""
    env.store.add(BOB, BOB_TASK)
    env.pdp.decide = per_action(
        {"scope": {"owners": [BOB]}}, ListTasks_own=True, GetTask=True
    )
    client = env.pdp_on(sharing=True)
    client.post(TASKS, json=TASK)
    client.get(f"{TASKS}/{BOB_TASK}")
    client.get(TASKS)
    client.post(f"{TASKS}/{BOB_TASK}:cancel")
    lines = audited(capsys)
    assert [summary(line) for line in lines] == [
        ("task.create", "deny", "decision_service", False),
        ("task.get", "allow", "decision_service", False),
        ("task.list", "allow", "decision_service", False),
        ("task.cancel", "deny", "decision_service", False),
    ]
    assert "task_id" not in lines[0]
    assert lines[2]["list_scope"] == "own+scope"
    assert "list_scope" not in lines[3]


@pytest.mark.parametrize(
    ("sharing", "decide", "scope"),
    [
        (True, per_action(ListTasks_all=True), "all"),
        (False, per_action(ListTasks=True), "own"),
    ],
    ids=["all", "own"],
)
def test_audit_list_scope(
    env: Env,
    capsys: pytest.CaptureFixture[str],
    *,
    sharing: bool,
    decide: Decide,
    scope: str,
) -> None:
    """A list says which set was listed."""
    env.pdp.decide = decide
    env.pdp_on(sharing=sharing).get(TASKS)
    (line,) = audited(capsys)
    assert line["list_scope"] == scope


@pytest.mark.parametrize(
    ("method", "path", "event"),
    [
        ("POST", TASKS, "task.create"),
        ("GET", f"{TASKS}/{BOB_TASK}", "task.get"),
        ("GET", TASKS, "task.list"),
        ("POST", f"{TASKS}/{BOB_TASK}:cancel", "task.cancel"),
    ],
)
def test_audit_decision_service_down(
    env: Env, capsys: pytest.CaptureFixture[str], method: str, path: str, event: str
) -> None:
    """A failing decision service (503) is one `error` line per request."""
    env.store.add(BOB, BOB_TASK)
    env.pdp.decide = lambda _: httpx.ConnectError("down")
    response = env.pdp_on(sharing=True).request(method, path, json=TASK)
    assert response.status_code == 503  # noqa: PLR2004
    (line,) = audited(capsys)
    assert (line["event"], line["outcome"], line["decided_by"]) == (
        event,
        "error",
        "decision_service",
    )


def test_audit_rule_deny(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    """A claim rule refusal is a built-in deny of the operation asked for."""
    client = env.start(rule(values=["urn:other"]))
    client.post(TASKS, json=TASK)
    client.get(f"{TASKS}/{BOB_TASK}")
    client.get(f"{TASKS}/not-a-uuid")
    lines = audited(capsys)
    assert [summary(line) for line in lines] == [
        ("task.create", "deny", "builtin", False),
        ("task.get", "deny", "builtin", False),
        ("task.get", "deny", "builtin", False),
    ]
    assert [line.get("task_id") for line in lines] == [None, BOB_TASK, None]


def test_audit_max_owners_deny(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    """Poiesis's own scope limit refusing the service's allow is built-in."""
    env.pdp.decide = per_action({"scope": {"owners": ["a", "b"]}}, ListTasks_own=True)
    env.pdp_on(sharing=True, max_owners=1).get(TASKS)
    (line,) = audited(capsys)
    assert summary(line) == ("task.list", "deny", "builtin", False)


def test_audit_actor(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    """A delegated token's line names the actor."""
    env.claims["act"] = {"sub": "gateway"}
    env.start({"actors": ["gateway"]}).get(TASKS)
    (line,) = audited(capsys)
    assert line["actor"] == {"iss": ISSUER, "sub": "gateway"}
    assert line["owner"] == ALICE


def test_audit_request_id(
    env: Env, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """The client's X-Request-ID is echoed, audited and logged with decisions.

    The decision service still gets an id of Poiesis's own per call.
    """
    client = env.pdp_on()
    response = client.get(TASKS, headers={"X-Request-ID": "trace-42"})
    assert response.headers["x-request-id"] == "trace-42"
    (line,) = audited(capsys)
    assert line["request_id"] == "trace-42"
    assert env.pdp.requests[0].headers["x-request-id"] != "trace-42"
    assert "API request trace-42" in caplog.text
    generated = client.get(TASKS).headers["x-request-id"]
    assert audited(capsys)[0]["request_id"] == generated


def test_audit_disabled(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    """With the audit log off, nothing is written; the request id stays."""
    audit.configure(enabled=False)
    client = env.start()
    response = client.post(TASKS, json=TASK)
    client.get(TASKS)
    assert capsys.readouterr().out == ""
    assert response.headers["x-request-id"]
