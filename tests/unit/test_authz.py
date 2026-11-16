"""Tests for authorization: the claim rule and the decision service hook.

The TES routes run in a real app with real token validation (fake
issuer, see `fake_issuer.py`), an in-memory task store instead of
Postgres and a recording stub decision service on the fake network.
The requests the stub receives are compared with golden files in
`golden/authz/`, which are shared with the decision-service side.
"""

import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fake_issuer import Issuer, Network
from fastapi import FastAPI
from fastapi.testclient import TestClient

from poiesis.api import app as app_module
from poiesis.api.auth import OIDCValidator, Principal
from poiesis.api.authz import Authz, strip_url
from poiesis.api.deps import get_db_conn, get_k8s, get_runtime_config
from poiesis.api.exceptions import APIError, handle_api_exception
from poiesis.api.routes import tasks as tasks_routes
from poiesis.api.settings import AuthSettings, AuthzSettings
from poiesis.api.tes.models import TesState, TesTask
from poiesis.db.tasks import ListFilters

GOLDEN = Path(__file__).parent / "golden" / "authz"
PDP = "https://pdp.example.org/access/v1/evaluation"
TASKS = "/ga4gh/tes/v1/tasks"
ENTITLEMENT = "eduperson_entitlement"
MEMBER = (
    "urn:geant:lifescience-ri.eu:group:example-vo:analysts#login.aai.lifescience-ri.eu"
)
SUBGROUPS = "urn:geant:lifescience-ri.eu:group:example-vo:"
TASK = {"executors": [{"image": "alpine", "command": ["true"]}]}

Decide = Callable[[dict[str, Any]], Any]


# -- fakes ----------------------------------------------------------------------


class Store:
    """In-memory stand-in for `poiesis.db.tasks` and the cancel transition."""

    def __init__(self) -> None:
        """Start empty."""
        self.tasks: dict[str, tuple[str, TesTask]] = {}

    def add(self, owner: str, task_id: str, **fields: Any) -> str:
        """Store a task of `owner` directly."""
        task = TesTask(id=task_id, state=TesState.RUNNING, executors=[], **fields)
        self.tasks[task_id] = (owner, task)
        return task_id

    async def create_task(self, _: Any, task: TesTask, principal: str) -> str:
        """Store a new task."""
        assert task.id is not None
        self.tasks[task.id] = (principal, task)
        return task.id

    async def get_task_meta(self, _: Any, task_id: str) -> dict[str, Any] | None:
        """Return owner, state and tags."""
        if task_id not in self.tasks:
            return None
        owner, task = self.tasks[task_id]
        assert task.state is not None
        return {"owner": owner, "state": task.state.value, "tags": task.tags or {}}

    async def get_task(self, _: Any, task_id: str, **kwargs: Any) -> TesTask | None:
        """Return the task, unfiltered."""
        assert kwargs.get("principal") is None
        return self.tasks[task_id][1] if task_id in self.tasks else None

    async def list_tasks(
        self, _: Any, filters: ListFilters, **__: Any
    ) -> tuple[list[TesTask], str | None]:
        """Page through tasks in insertion order, filtered by owner."""
        rows = [
            task
            for owner, task in self.tasks.values()
            if filters.principal in {None, owner}
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


def per_action(**decisions: bool) -> Decide:
    """Decide by `<action>` or `<action>_<resource id>`, default deny."""

    def decide(body: dict[str, Any]) -> Any:
        action, resource = body["action"]["name"], body["resource"]["id"]
        key = f"{action}_{resource}"
        return {"decision": decisions.get(key, decisions.get(action, False))}

    return decide


# -- fixtures --------------------------------------------------------------------


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

    def start(self, **settings: Any) -> TestClient:
        """Build the app with `AuthzSettings(**settings)`; return a client."""
        oidc = OIDCValidator(AuthSettings(userinfo_enabled=True))
        asyncio.run(oidc.bootstrap())
        app = FastAPI()
        app.add_exception_handler(APIError, handle_api_exception)
        app.include_router(tasks_routes.router, prefix="/ga4gh/tes/v1")
        app.state.oidc = oidc
        app.state.authz = Authz(AuthzSettings(**settings))
        app.dependency_overrides[get_db_conn] = lambda: None
        app.dependency_overrides[get_k8s] = K8s
        app.dependency_overrides[get_runtime_config] = lambda: SimpleNamespace(
            taskpod_namespace="ns"
        )
        token = self.issuer.token(**self.claims)
        return TestClient(app, headers={"Authorization": f"Bearer {token}"})

    def pdp_on(self, **settings: Any) -> TestClient:
        """Start with the stub decision service and the entitlement allowlisted."""
        defaults = {
            "decision_service_url": PDP,
            "decision_service_claims": (ENTITLEMENT,),
        }
        return self.start(**defaults | settings)


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


def gate(claims: dict[str, Any], **rule: Any) -> bool:
    """Whether the claim rule admits a principal with `claims`."""
    settings = {"required_claim_name": ENTITLEMENT} | rule
    try:
        Authz(AuthzSettings(**settings)).gate(Principal(id="a", claims=claims))
    except APIError:
        return False
    return True


class TestClaimRule:
    """The claim rule: exact values or raw prefixes, on a string or list."""

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
        assert gate({ENTITLEMENT: value}, required_claim_values=("a",)) is admitted

    @pytest.mark.parametrize(
        ("value", "admitted"),
        [("urn:g:vo:sub#x", True), ("urn:g:vox#x", False), ("urn:g:vo#x", False)],
    )
    def test_prefixes(self, value: str, *, admitted: bool) -> None:
        """Prefixes are raw: the delimiter is part of the prefix."""
        assert gate({ENTITLEMENT: [value]}, required_claim_prefixes=("urn:g:vo:",)) is (
            admitted
        )

    def test_off_without_name(self) -> None:
        """No claim name, no rule."""
        assert gate({}, required_claim_name="")

    @pytest.mark.parametrize(
        ("name", "claims"),
        [
            ("ctx.groups", {"ctx": {"groups": ["a"]}}),
            ("https://e.org/groups", {"https://e.org/groups": ["a"]}),
        ],
    )
    def test_names(self, name: str, claims: dict[str, Any]) -> None:
        """The claim is found by dotted path or by exact (URI) name."""
        assert gate(claims, required_claim_name=name, required_claim_values=("a",))


# -- startup checks ---------------------------------------------------------------


@pytest.mark.parametrize(
    "settings",
    [
        {"decision_service_url": PDP},
        {"required_claim_name": "g", "required_claim_values": ("a",)},
        {"decision_service_claims": ("g",)},
    ],
)
def test_refused_without_auth(settings: dict[str, Any]) -> None:
    """Authorization settings with auth disabled refuse to start."""
    with pytest.raises(ValueError, match="auth is disabled"):
        AuthzSettings(**settings).validate_for(auth_enabled=False)


@pytest.mark.parametrize(
    "settings",
    [{"required_claim_name": "g"}, {"required_claim_values": ("a",)}],
)
def test_incomplete_rule_refused(settings: dict[str, Any]) -> None:
    """A rule needs a name and values or prefixes."""
    with pytest.raises(ValueError, match="claim rule"):
        AuthzSettings(**settings).validate_for(auth_enabled=True)


def test_defaults_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing set is fine either way, and the timeout defaults to 2 s."""
    for name in os.environ:
        if name.startswith("POIESIS_AUTHZ_"):
            monkeypatch.delenv(name)
    settings = AuthzSettings()
    settings.validate_for(auth_enabled=False)
    assert settings.decision_service_timeout == 2  # noqa: PLR2004


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Lists are JSON arrays (values may contain commas)."""
    monkeypatch.setenv("POIESIS_AUTHZ_REQUIRED_CLAIM_VALUES", '["a,b", "c"]')
    monkeypatch.setenv("POIESIS_AUTHZ_DECISION_SERVICE_TIMEOUT", "0.5")
    assert AuthzSettings().required_claim_values == ("a,b", "c")
    assert AuthzSettings().decision_service_timeout == 0.5  # noqa: PLR2004
    monkeypatch.setenv("POIESIS_AUTHZ_DECISION_SERVICE_CLAIMS", "a,b")
    with pytest.raises(ValueError, match="not valid JSON"):
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


@pytest.mark.parametrize("url", ["ftp://pdp/x", "pdp.example.org/x"])
def test_url_must_be_http(url: str) -> None:
    """Only http(s) decision service URLs are accepted."""
    with pytest.raises(ValueError, match="http"):
        Authz(AuthzSettings(decision_service_url=url))


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
    env.store.add("bob", BOB_TASK)
    own = client.post(TASKS, json=TASK).json()["id"]
    assert client.get(f"{TASKS}/{BOB_TASK}").status_code == 404  # noqa: PLR2004
    assert client.post(f"{TASKS}/{BOB_TASK}:cancel").status_code == 404  # noqa: PLR2004
    assert client.get(f"{TASKS}/{own}").status_code == 200  # noqa: PLR2004
    assert [t["id"] for t in client.get(TASKS).json()["tasks"]] == [own]
    assert env.pdp.requests == []


def test_rule_only(env: Env) -> None:
    """A rule without a decision service and with no allowlist admits."""
    client = env.start(
        required_claim_name=ENTITLEMENT, required_claim_prefixes=(SUBGROUPS,)
    )
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
    """A failing rule gives 403 on every action; the PDP is not asked."""
    env.claims[ENTITLEMENT] = ["urn:geant:lifescience-ri.eu:group:other#x"]
    client = env.pdp_on(
        required_claim_name=ENTITLEMENT, required_claim_prefixes=(SUBGROUPS,)
    )
    env.store.add("bob", BOB_TASK)
    assert client.request(method, path, json=TASK).status_code == 403  # noqa: PLR2004
    assert env.pdp.requests == []


def test_rule_denies_service_client(env: Env) -> None:
    """A client-credentials token without the claim gets 403."""
    env.claims = {"azp": "service", "sub": "service-account"}
    client = env.start(required_claim_name=ENTITLEMENT, required_claim_values=(MEMBER,))
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
    assert owner == "alice"
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
    assert env.pdp.bodies[0]["subject"]["id"] == "alice"


def test_create_denied(env: Env) -> None:
    """A deny is a 403 and nothing is stored."""
    env.pdp.decide = per_action()
    assert env.pdp_on().post(TASKS, json=TASK).status_code == 403  # noqa: PLR2004
    assert env.store.tasks == {}


def test_rule_and_decision(env: Env) -> None:
    """Rule passes, decision denies: 403."""
    env.pdp.decide = per_action()
    client = env.pdp_on(
        required_claim_name=ENTITLEMENT, required_claim_prefixes=(SUBGROUPS,)
    )
    assert client.post(TASKS, json=TASK).status_code == 403  # noqa: PLR2004
    assert len(env.pdp.requests) == 1


def test_credential_file(env: Env, tmp_path: Path) -> None:
    """The optional PEP credential is sent as a bearer token."""
    credential = tmp_path / "credential"
    credential.write_text("pep-secret\n")
    env.pdp_on(decision_service_credential_file=str(credential)).post(TASKS, json=TASK)
    assert env.pdp.requests[0].headers["authorization"] == "Bearer pep-secret"


def test_get_foreign_allowed(env: Env) -> None:
    """The decision service may grant access to others' tasks."""
    env.store.add("bob", BOB_TASK, tags={"project": "x"})
    response = env.pdp_on().get(f"{TASKS}/{BOB_TASK}", params={"view": "BASIC"})
    assert response.status_code == 200  # noqa: PLR2004
    golden("get-other", env.pdp.bodies[0])


def test_get_and_cancel_denied(env: Env) -> None:
    """Denied get and cancel are 404 and leave the task alone."""
    env.pdp.decide = per_action()
    env.store.add("bob", BOB_TASK)
    client = env.pdp_on()
    assert client.get(f"{TASKS}/{BOB_TASK}").status_code == 404  # noqa: PLR2004
    assert client.post(f"{TASKS}/{BOB_TASK}:cancel").status_code == 404  # noqa: PLR2004
    assert env.store.tasks[BOB_TASK][1].state == TesState.RUNNING
    golden("cancel-other", env.pdp.bodies[1])
    assert env.pdp.bodies[2]["action"] == {"name": "GetTask", "properties": {}}


def test_cancel_denied_but_readable(env: Env) -> None:
    """Readable but not cancellable: 403."""
    env.pdp.decide = per_action(GetTask=True)
    env.store.add("bob", BOB_TASK)
    response = env.pdp_on().post(f"{TASKS}/{BOB_TASK}:cancel")
    assert response.status_code == 403  # noqa: PLR2004


def test_cancel_allowed(env: Env) -> None:
    """An allowed cancel moves the task to CANCELING."""
    env.store.add("alice", ALICE_TASK)
    assert env.pdp_on().post(f"{TASKS}/{ALICE_TASK}:cancel").status_code == 200  # noqa: PLR2004
    assert env.store.tasks[ALICE_TASK][1].state == TesState.CANCELING


@pytest.mark.parametrize("allowed", [True, False])
def test_missing_task(env: Env, *, allowed: bool) -> None:
    """A missing task is 404 whatever the decision; the PDP is still asked."""
    env.pdp.decide = per_action(GetTask=allowed, CancelTask=allowed)
    client = env.pdp_on()
    assert client.get(f"{TASKS}/{MISSING}").status_code == 404  # noqa: PLR2004
    assert client.post(f"{TASKS}/{MISSING}:cancel").status_code == 404  # noqa: PLR2004
    golden("get-missing", env.pdp.bodies[0])
    assert env.pdp.bodies[1]["resource"]["properties"] == {}


def test_legacy_task_has_no_owner(env: Env) -> None:
    """Tasks from before owners were stamped are sent without an owner."""
    env.store.add("__legacy__", BOB_TASK)
    env.pdp_on().get(f"{TASKS}/{BOB_TASK}")
    assert "owner" not in env.pdp.bodies[0]["resource"]["properties"]


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
    ],
    ids=["timeout", "down", "500", "not-json", "string", "missing", "not-object"],
)
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", TASKS),
        ("GET", f"{TASKS}/{BOB_TASK}"),
        ("GET", f"{TASKS}/{MISSING}"),
        ("POST", f"{TASKS}/{BOB_TASK}:cancel"),
        ("GET", TASKS),
    ],
)
def test_decision_service_failure(
    env: Env, answer: Any, method: str, path: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Any failure is a 503 with Retry-After, logged; nothing is executed."""
    env.pdp.decide = lambda _: answer
    env.store.add("bob", BOB_TASK)
    response = env.pdp_on().request(method, path, json=TASK)
    assert response.status_code == 503  # noqa: PLR2004
    assert response.headers["retry-after"] == "1"
    assert "Decision service failed" in caplog.text
    assert len(env.store.tasks) == 1
    assert env.store.tasks[BOB_TASK][1].state == TesState.RUNNING


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
        store.add("alice", f"00000000-0000-4000-8000-0000000000a{i}") for i in range(3)
    ]
    bob = [
        store.add("bob", f"00000000-0000-4000-8000-0000000000b{i}") for i in range(3)
    ]
    return alice, bob


def test_list_all(env: Env) -> None:
    """`all` allowed: every task, complete, no duplicates."""
    alice, bob = fill(env.store)
    env.pdp.decide = per_action(ListTasks_all=True)
    pages = page_through(env.pdp_on(), page_size=2)
    assert len(pages) == 3  # noqa: PLR2004
    assert sorted(i for page in pages for i in page) == sorted(alice + bob)
    golden("list-all", env.pdp.bodies[0])


def test_list_own(env: Env) -> None:
    """Only `own` allowed: own tasks, complete, pages of at most 2."""
    alice, _ = fill(env.store)
    env.pdp.decide = per_action(ListTasks_own=True)
    pages = page_through(env.pdp_on(), page_size=2)
    assert all(len(page) <= 2 for page in pages)  # noqa: PLR2004
    assert sorted(i for page in pages for i in page) == sorted(alice)
    golden("list-own", next(b for b in env.pdp.bodies if b["resource"]["id"] == "own"))


def test_list_scope_per_page(env: Env) -> None:
    """The scope is evaluated again for every page."""
    alice, _ = fill(env.store)
    env.pdp.decide = per_action(ListTasks_all=True)
    client = env.pdp_on()
    token = client.get(TASKS, params={"page_size": 2}).json()["next_page_token"]
    env.pdp.decide = per_action(ListTasks_own=True)
    page = client.get(TASKS, params={"page_size": 6, "page_token": token}).json()
    assert {t["id"] for t in page["tasks"]} <= set(alice)


def test_list_denied(env: Env) -> None:
    """Neither set allowed: 403."""
    env.pdp.decide = per_action()
    assert env.pdp_on().get(TASKS).status_code == 403  # noqa: PLR2004
    assert len(env.pdp.requests) == 2  # noqa: PLR2004


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
        decision_service_claims=(ENTITLEMENT, "groups"),
        required_claim_name="groups",
        required_claim_values=(MEMBER,),
    )
    assert client.post(TASKS, json=TASK).status_code == 200  # noqa: PLR2004
    claims = env.pdp.bodies[0]["subject"]["properties"]["claims"]
    assert claims == {ENTITLEMENT: [MEMBER], "groups": [MEMBER]}
