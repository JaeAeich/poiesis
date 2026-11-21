"""Tests for API keys: minting, the authenticator, scopes and settings.

The real app runs (lifespan included) with a real JWT link against the
fake issuer (see `fake_issuer.py`), an in-memory `api_keys` table in
place of `poiesis.db.api_keys` and fake tasks, database and cluster.
"""

import asyncio
import base64
import contextlib
import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import pytest
from fake_issuer import (
    AUDIENCE,
    GATEWAY,
    GATEWAY_JWKS,
    ISSUER,
    Issuer,
    Network,
    set_issuers,
)
from fastapi.testclient import TestClient

from poiesis.api import app as app_module
from poiesis.api.apikey_auth import (
    ApiKeyAuthenticator,
    hash_key,
    key_from_header,
    new_key,
    well_formed,
)
from poiesis.api.auth import Principal
from poiesis.api.authz import Authz
from poiesis.api.exceptions import ServiceUnavailableError, UnauthorizedError
from poiesis.api.routes import tasks as tasks_routes
from poiesis.api.routes.api_keys import mint_refusal
from poiesis.api.settings import (
    ApiKeySettings,
    AuthSettings,
    AuthzSettings,
    IssuerSettings,
    format_ttl,
    parse_ttl,
)
from poiesis.api.tes.models import TesState, TesTask
from poiesis.db import api_keys as api_keys_db
from poiesis.db.api_keys import ApiKeyCredential, ApiKeyRecord

KEYS = "/poiesis/v1/api-keys"
TASKS = "/ga4gh/tes/v1/tasks"
TASK = {"executors": [{"image": "alpine", "command": ["true"]}]}
ALICE = f"{ISSUER}|alice"
TASK_ID = "00000000-0000-4000-8000-00000000000a"
#: The login client allowed to mint keys (`keyMinting.clients`).
LOGIN = "poiesis-cli"


# -- fakes ----------------------------------------------------------------------


class KeyTable:
    """In-memory `api_keys` table with the semantics of `poiesis.db.api_keys`."""

    def __init__(self) -> None:
        """Start empty and reachable."""
        self.rows: dict[uuid.UUID, dict[str, Any]] = {}
        self.down = False
        self.lookups = 0
        self.touched: list[dict[uuid.UUID, datetime]] = []

    def check(self) -> None:
        """Fail like an unreachable database while `down`."""
        if self.down:
            raise OSError("connection refused")

    def insert(self, key: str, owner: str = ALICE, **fields: Any) -> uuid.UUID:
        """Store a key directly; return its id."""
        key_id = uuid.uuid4()
        now = datetime.now(UTC)
        self.rows[key_id] = {
            "name": "k",
            "key_hash": hash_key(key),
            "owner": owner,
            "scopes": ("tasks:read", "tasks:write"),
            "claims_snapshot": {"claims": {"sub": "alice"}, "userinfo": {}},
            "created_at": now,
            "expires_at": now + timedelta(days=1),
            "last_used_at": None,
            "revoked_at": None,
        } | fields
        return key_id

    def record(self, key_id: uuid.UUID) -> ApiKeyRecord:
        """Return the owner's view of a row."""
        row = self.rows[key_id]
        return ApiKeyRecord(
            id=key_id,
            name=row["name"],
            scopes=tuple(row["scopes"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            last_used_at=row["last_used_at"],
            revoked_at=row["revoked_at"],
        )

    async def create_api_key(
        self, _: Any, *, key_id: uuid.UUID, ttl: timedelta, max_active: int, **row: Any
    ) -> ApiKeyRecord | None:
        """Insert unless the owner holds `max_active` active keys."""
        self.check()
        now = datetime.now(UTC)
        active = [
            r
            for r in self.rows.values()
            if r["owner"] == row["owner"]
            and r["revoked_at"] is None
            and r["expires_at"] > now
        ]
        if len(active) >= max_active:
            return None
        # Through JSON, like the jsonb column.
        snapshot = json.loads(json.dumps(row.pop("claims_snapshot")))
        self.rows[key_id] = row | {
            "scopes": tuple(row["scopes"]),
            "claims_snapshot": snapshot,
            "created_at": now,
            "expires_at": now + ttl,
            "last_used_at": None,
            "revoked_at": None,
        }
        return self.record(key_id)

    async def find_api_key(self, _: Any, key_hash: bytes) -> ApiKeyCredential | None:
        """Look a key up by hash."""
        self.lookups += 1
        self.check()
        for key_id, row in self.rows.items():
            if row["key_hash"] == key_hash:
                return ApiKeyCredential(
                    id=key_id,
                    owner=row["owner"],
                    scopes=tuple(row["scopes"]),
                    claims_snapshot=row["claims_snapshot"],
                    revoked=row["revoked_at"] is not None,
                    expired=row["expires_at"] <= datetime.now(UTC),
                )
        return None

    async def list_api_keys(self, _: Any, owner: str) -> list[ApiKeyRecord]:
        """Return the owner's keys."""
        self.check()
        return [self.record(i) for i, r in self.rows.items() if r["owner"] == owner]

    async def revoke_api_key(self, _: Any, key_id: uuid.UUID, owner: str) -> bool:
        """Revoke the owner's key."""
        self.check()
        row = self.rows.get(key_id)
        if row is None or row["owner"] != owner:
            return False
        row["revoked_at"] = row["revoked_at"] or datetime.now(UTC)
        return True

    async def touch_api_keys(self, _: Any, used: dict[uuid.UUID, datetime]) -> None:
        """Record one batch of usage times."""
        self.check()
        self.touched.append(dict(used))
        for key_id, at in used.items():
            self.rows[key_id]["last_used_at"] = at


class Pool:
    """Stands in for the asyncpg pool (the fakes ignore the connection)."""

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        """Hand out a dummy connection."""
        yield None

    async def close(self) -> None:
        """Nothing to close."""


class K8s:
    """Accepts every Job and PVC."""

    async def create_job(self, *_: Any) -> Any:
        """Return a created Job."""
        return SimpleNamespace(metadata=SimpleNamespace(uid="uid", name="job"))

    async def create_pvc(self, *_: Any) -> None:
        """Accept the PVC."""

    async def delete_job(self, *_: Any) -> None:
        """Accept the delete."""


@pytest.fixture
def issuer(network: Network, monkeypatch: pytest.MonkeyPatch) -> Issuer:
    """The fake issuer, allowed to mint keys; its tokens come from `LOGIN`."""
    set_issuers(
        monkeypatch,
        {"issuer": ISSUER, "audience": AUDIENCE, "keyMinting": {"clients": [LOGIN]}},
    )
    fake = network.add(Issuer())
    plain = fake.token

    def token(key: Any = None, **claims: Any) -> str:
        return plain(key, **({"azp": LOGIN} | claims))

    monkeypatch.setattr(fake, "token", token)
    return fake


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch) -> KeyTable:
    """An empty in-memory `api_keys` table, wired in."""
    keys = KeyTable()
    for name in (
        "create_api_key",
        "find_api_key",
        "list_api_keys",
        "revoke_api_key",
        "touch_api_keys",
    ):
        monkeypatch.setattr(api_keys_db, name, getattr(keys, name))
    return keys


@pytest.fixture
def tasks(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[str, TesTask]]:
    """Fake task storage and cluster for the TES routes; owner by task id."""
    stored: dict[str, tuple[str, TesTask]] = {}

    async def create_task(_: Any, task: TesTask, owner: str) -> str:
        assert task.id is not None
        stored[task.id] = (owner, task)
        return task.id

    async def get_task_meta(_: Any, task_id: str) -> dict[str, Any] | None:
        if task_id not in stored:
            return None
        return {"owner": stored[task_id][0], "state": "RUNNING", "tags": {}}

    async def get_task(_: Any, task_id: str, **__: Any) -> TesTask | None:
        return stored[task_id][1] if task_id in stored else None

    async def list_tasks(_: Any, filters: Any, **__: Any) -> tuple[list[TesTask], None]:
        return [t for o, t in stored.values() if filters.owner in {None, o}], None

    async def mark_canceling(*_: Any) -> bool:
        return True

    for function in (create_task, get_task_meta, get_task, list_tasks):
        monkeypatch.setattr(tasks_routes.tasks_db, function.__name__, function)
    monkeypatch.setattr(tasks_routes.state_db, "mark_canceling", mark_canceling)
    monkeypatch.setattr(
        tasks_routes, "build_taskpod_job", lambda *_: (SimpleNamespace(), None)
    )
    monkeypatch.setattr(tasks_routes, "attach_pvc_owner", lambda *_: None)
    return stored


@pytest.fixture
def app_env(
    issuer: Issuer,
    table: KeyTable,
    tasks: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> pytest.MonkeyPatch:
    """Fake database and cluster for the real app; returns `monkeypatch`."""

    async def create_pool(_: str) -> Pool:
        return Pool()

    monkeypatch.setattr(app_module, "create_pool", create_pool)
    monkeypatch.setattr(app_module, "load_config", lambda: None)
    monkeypatch.setattr(app_module, "K8sClient", K8s)
    return monkeypatch


@pytest.fixture
def client(app_env: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The started real app with default settings."""
    with TestClient(app_module.create_app()) as test_client:
        yield test_client


def bearer(token: str) -> dict[str, str]:
    """Return an `Authorization: Bearer` header."""
    return {"Authorization": f"Bearer {token}"}


def basic(user: str, password: str) -> dict[str, str]:
    """Return an `Authorization: Basic` header."""
    pair = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {pair}"}


def mint(client: TestClient, token: str, **body: Any) -> Any:
    """Mint a key with `token`; return the response."""
    return client.post(KEYS, json={"name": "run"} | body, headers=bearer(token))


def minted(client: TestClient, issuer: Issuer, **body: Any) -> dict[str, Any]:
    """Mint a key as alice; return the created key."""
    response = mint(client, issuer.token(), **body)
    assert response.status_code == HTTPStatus.CREATED, response.text
    return response.json()


# -- the key and its header ------------------------------------------------------


def test_key_format() -> None:
    """`poi_`, 43 base64url characters and a checksum, never a `.`; hashed."""
    keys = {new_key() for _ in range(100)}
    assert len(keys) == 100  # noqa: PLR2004
    for key in keys:
        assert key.startswith("poi_")
        assert len(key) == 53  # noqa: PLR2004
        assert "." not in key
        assert well_formed(key)
    key = keys.pop()
    assert hash_key(key) == hashlib.sha256(key.encode()).digest()


def test_checksum_catches_damage() -> None:
    """A changed character, a truncation or a made-up key fails the checksum."""
    key = new_key()
    flipped = key[:10] + ("A" if key[10] != "A" else "B") + key[11:]
    assert not well_formed(flipped)
    assert not well_formed(key[:-1])
    assert not well_formed(key + "x")
    assert not well_formed("poi_" + "x" * 49)


KEY = "poi_" + "A" * 43


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (f"Bearer {KEY}", KEY),
        (f"bearer  {KEY} ", KEY),
        (basic("x", KEY)["Authorization"], KEY),
        (basic("", KEY)["Authorization"], KEY),
        (basic("user", f"{KEY}:x")["Authorization"], f"{KEY}:x"),
        (basic("user", "password")["Authorization"], None),
        (basic(KEY, "password")["Authorization"], None),
        ("Basic not-base64!", None),
        ("Basic " + base64.b64encode(b"\xff:poi_").decode(), None),
        ("Bearer a.b.c", None),
        ("Bearer opaque", None),
        (f"Token {KEY}", None),
        (KEY, None),
        ("", None),
        (None, None),
    ],
)
def test_key_from_header(header: str | None, expected: str | None) -> None:
    """Bearer and Basic (key as password) carry a key; nothing else does."""
    assert key_from_header(header) == expected


# -- minting ----------------------------------------------------------------------


def test_mint_and_use(client: TestClient, issuer: Issuer, table: KeyTable) -> None:
    """A minted key is shown once, stored hashed, and works as Bearer and Basic."""
    created = minted(client, issuer, ttl="12h")
    assert set(created) == {"id", "name", "key", "scopes", "createdAt", "expiresAt"}
    assert created["scopes"] == ["tasks:read", "tasks:write"]
    row = table.rows[uuid.UUID(created["id"])]
    assert row["key_hash"] == hash_key(created["key"])
    assert created["key"] not in json.dumps(row, default=str)
    lifetime = datetime.fromisoformat(created["expiresAt"]) - datetime.fromisoformat(
        created["createdAt"]
    )
    assert lifetime == timedelta(hours=12)
    assert row["owner"] == ALICE

    key = created["key"]
    response = client.post(TASKS, json=TASK, headers=bearer(key))
    assert response.status_code == HTTPStatus.OK, response.text
    for headers in (bearer(key), basic("x", key), basic("nextflow", key)):
        response = client.get(TASKS, headers=headers)
        assert response.status_code == HTTPStatus.OK, response.text
        assert len(response.json()["tasks"]) == 1


def test_key_sees_owner_tasks(
    client: TestClient, issuer: Issuer, tasks: dict[str, Any]
) -> None:
    """A key acts as its owner: same tasks as the owner's token."""
    tasks[TASK_ID] = (ALICE, TesTask(id=TASK_ID, state=TesState.RUNNING, executors=[]))
    tasks["other"] = ("bob", TesTask(id="other", state=TesState.RUNNING, executors=[]))
    key = minted(client, issuer)["key"]
    response = client.get(f"{TASKS}/{TASK_ID}", headers=bearer(key))
    assert response.status_code == HTTPStatus.OK
    assert [
        t["id"] for t in client.get(TASKS, headers=bearer(key)).json()["tasks"]
    ] == [TASK_ID]


def test_snapshot(client: TestClient, issuer: Issuer, table: KeyTable) -> None:
    """The snapshot keeps the owner's claims without the token's own lifetime."""
    token = issuer.token(jti="t-1", iat=1, nbf=1, auth_time=1, groups=["lab-alpha"])
    created = mint(client, token).json()
    snapshot = table.rows[uuid.UUID(created["id"])]["claims_snapshot"]
    assert snapshot == {
        "claims": {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "alice",
            "groups": ["lab-alpha"],
            "azp": LOGIN,
        },
        "userinfo": {},
    }


@pytest.mark.parametrize(
    ("scopes", "stored"),
    [
        (["tasks:read"], ("tasks:read",)),
        (["tasks:write", "tasks:read", "tasks:write"], ("tasks:read", "tasks:write")),
    ],
)
def test_mint_scopes(
    client: TestClient,
    issuer: Issuer,
    table: KeyTable,
    scopes: list[str],
    stored: tuple[str, ...],
) -> None:
    """Requested scopes are stored deduplicated and sorted."""
    created = minted(client, issuer, scopes=scopes)
    assert table.rows[uuid.UUID(created["id"])]["scopes"] == stored


@pytest.mark.parametrize(
    "body",
    [
        {"name": ""},
        {"name": "x" * 101},
        {"name": "run", "ttl": "30"},
        {"name": "run", "ttl": "0d"},
        {"name": "run", "ttl": "1w"},
        {"name": "run", "ttl": "1000000d"},
        {"name": "run", "scopes": []},
        {"name": "run", "scopes": ["tasks:admin"]},
        {"name": "run", "owner": "bob"},
        {},
    ],
)
def test_mint_invalid_body(client: TestClient, issuer: Issuer, body: Any) -> None:
    """Malformed requests are refused before anything is stored."""
    response = client.post(KEYS, json=body, headers=bearer(issuer.token()))
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text


def test_ttl_default_and_max(
    app_env: pytest.MonkeyPatch, issuer: Issuer, table: KeyTable
) -> None:
    """No ttl is the default lifetime; one above the maximum is a 400."""
    app_env.setenv("POIESIS_AUTH_API_KEYS_DEFAULT_TTL", "2d")
    app_env.setenv("POIESIS_AUTH_API_KEYS_MAX_TTL", "48h")
    with TestClient(app_module.create_app()) as client:
        created = minted(client, issuer)
        row = table.rows[uuid.UUID(created["id"])]
        assert row["expires_at"] - row["created_at"] == timedelta(days=2)
        assert minted(client, issuer, ttl="48h")
        response = mint(client, issuer.token(), ttl="49h")
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()["message"] == "ttl 49h exceeds the maximum of 2d"
    assert len(table.rows) == 2  # noqa: PLR2004


def test_cap_per_owner(
    app_env: pytest.MonkeyPatch, issuer: Issuer, table: KeyTable
) -> None:
    """At the cap, minting is a 409 until a key is revoked or expires."""
    app_env.setenv("POIESIS_AUTH_API_KEYS_MAX_PER_OWNER", "2")
    with TestClient(app_module.create_app()) as client:
        first = minted(client, issuer)
        minted(client, issuer)
        response = mint(client, issuer.token())
        assert response.status_code == HTTPStatus.CONFLICT
        assert response.json()["error"] == "conflict"
        # Bob has his own allowance.
        assert mint(client, issuer.token(sub="bob")).status_code == HTTPStatus.CREATED
        headers = bearer(issuer.token())
        client.delete(f"{KEYS}/{first['id']}", headers=headers)
        assert mint(client, issuer.token()).status_code == HTTPStatus.CREATED


def test_mint_needs_key_minting(
    app_env: pytest.MonkeyPatch, issuer: Issuer, table: KeyTable
) -> None:
    """An issuer without `keyMinting` can't mint; listing still works."""
    set_issuers(app_env, {"issuer": ISSUER, "audience": AUDIENCE})
    with TestClient(app_module.create_app()) as client:
        response = mint(client, issuer.token())
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "can't mint" in response.json()["message"]
        listed = client.get(KEYS, headers=bearer(issuer.token()))
        assert listed.status_code == HTTPStatus.OK
    assert table.rows == {}


@pytest.mark.parametrize(
    ("claims", "allowed"),
    [
        ({"azp": LOGIN}, True),
        ({"azp": None, "client_id": LOGIN}, True),
        ({"azp": "poiesis-ci"}, False),
        ({"azp": None}, False),
    ],
    ids=["azp", "client_id", "service-client", "no-client"],
)
def test_mint_clients(
    client: TestClient, issuer: Issuer, claims: dict[str, Any], *, allowed: bool
) -> None:
    """Only tokens of a listed client (`azp`, else `client_id`) mint keys."""
    # `azp: None` overrides the fixture's default with a null claim.
    response = mint(client, issuer.token(**claims))
    expected = HTTPStatus.CREATED if allowed else HTTPStatus.FORBIDDEN
    assert response.status_code == expected, response.text


def _minting(**minting: Any) -> IssuerSettings:
    return IssuerSettings.model_validate(
        {"issuer": ISSUER, "audience": AUDIENCE, "keyMinting": minting}
    )


@pytest.mark.parametrize(
    ("auth_time", "refusal"),
    [
        (1000 - 60, None),
        (1000 - 600, None),
        (1000 - 601, "too old"),
        (1000 + 30, None),
        (1000 + 31, "in the future"),
        (None, "no auth_time"),
        ("900", "no auth_time"),
        (True, "no auth_time"),
    ],
)
def test_mint_max_auth_age(auth_time: Any, refusal: str | None) -> None:
    """With `maxAuthAge`, minting needs a login at most that many seconds ago."""
    claims = {"azp": LOGIN} | ({} if auth_time is None else {"auth_time": auth_time})
    principal = Principal(issuer=ISSUER, subject="alice", via="oidc", claims=claims)
    issuer = _minting(clients=[LOGIN], maxAuthAge=600)
    result = mint_refusal(principal, issuer, now=1000)
    if refusal is None:
        assert result is None
    else:
        assert result is not None
        assert refusal in result


def test_mint_without_issuer_settings() -> None:
    """An issuer that isn't configured (any more) can't mint."""
    principal = Principal(
        issuer=ISSUER, subject="alice", via="oidc", claims={"azp": LOGIN}
    )
    assert mint_refusal(principal, None, now=0) is not None
    assert mint_refusal(principal, _minting(clients=[LOGIN]), now=0) is None


@pytest.mark.parametrize(
    "minting",
    [
        {"clients": []},
        {"clients": [""]},
        {"clients": [LOGIN], "maxAuthAge": 0},
        {"clients": [LOGIN], "other": 1},
    ],
    ids=["no-clients", "empty-client", "zero-age", "unknown-key"],
)
def test_key_minting_settings_invalid(minting: dict[str, Any]) -> None:
    """`keyMinting` needs at least one client id and a positive age."""
    with pytest.raises(ValueError, match=r"keyMinting|clients|maxAuthAge|other"):
        _minting(**minting)


def test_key_cannot_manage_keys(client: TestClient, issuer: Issuer) -> None:
    """A key can't mint, list or revoke keys."""
    created = minted(client, issuer)
    headers = bearer(created["key"])
    for method, path in (
        ("POST", KEYS),
        ("GET", KEYS),
        ("DELETE", f"{KEYS}/{created['id']}"),
    ):
        response = client.request(method, path, json={"name": "x"}, headers=headers)
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "a key can't mint" in response.json()["message"]


def test_delegated_token_cannot_manage_keys(client: TestClient, issuer: Issuer) -> None:
    """A delegated token (with an `act` claim) can't manage keys."""
    token = issuer.token(act={"sub": "engine"})
    for method in ("POST", "GET"):
        response = client.request(
            method, KEYS, json={"name": "x"}, headers=bearer(token)
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json()["message"] == "delegated tokens can't manage keys"


def test_claim_rule_applies_to_minting(
    app_env: pytest.MonkeyPatch, issuer: Issuer
) -> None:
    """The claim rule gates key management like every TES call."""
    app_env.setenv("POIESIS_AUTHZ_REQUIRED_CLAIM_NAME", "groups")
    app_env.setenv("POIESIS_AUTHZ_REQUIRED_CLAIM_VALUES", '["lab-alpha"]')
    with TestClient(app_module.create_app()) as client:
        assert mint(client, issuer.token()).status_code == HTTPStatus.FORBIDDEN
        token = issuer.token(groups=["lab-alpha"])
        response = mint(client, token)
        assert response.status_code == HTTPStatus.CREATED
        key = response.json()["key"]
        # The key carries the snapshot, so it passes the rule too.
        assert client.get(TASKS, headers=bearer(key)).status_code == HTTPStatus.OK


def test_list_and_revoke_own_only(client: TestClient, issuer: Issuer) -> None:
    """Owners list and revoke their own keys only; a revoked key stops working."""
    alice, bob = bearer(issuer.token()), bearer(issuer.token(sub="bob"))
    mine = minted(client, issuer)
    theirs = mint(client, issuer.token(sub="bob")).json()

    listed = client.get(KEYS, headers=alice).json()
    assert [k["id"] for k in listed] == [mine["id"]]
    assert set(listed[0]) == {
        "id",
        "name",
        "scopes",
        "createdAt",
        "expiresAt",
        "lastUsedAt",
        "revokedAt",
    }
    assert listed[0]["revokedAt"] is None

    for key_id in (theirs["id"], str(uuid.uuid4())):
        response = client.delete(f"{KEYS}/{key_id}", headers=alice)
        assert response.status_code == HTTPStatus.NOT_FOUND
    assert (
        client.delete(f"{KEYS}/not-a-uuid", headers=alice).status_code
        == HTTPStatus.BAD_REQUEST
    )
    assert client.get(TASKS, headers=bearer(theirs["key"])).status_code == HTTPStatus.OK

    assert client.get(TASKS, headers=bearer(mine["key"])).status_code == HTTPStatus.OK
    for _ in range(2):  # revoking twice is fine
        response = client.delete(f"{KEYS}/{mine['id']}", headers=alice)
        assert response.status_code == HTTPStatus.NO_CONTENT
        assert response.content == b""
    response = client.get(TASKS, headers=bearer(mine["key"]))
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert client.get(KEYS, headers=alice).json()[0]["revokedAt"] is not None
    assert [k["id"] for k in client.get(KEYS, headers=bob).json()] == [theirs["id"]]


# -- authenticating with a key ---------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        bearer(new_key()),
        bearer("poi_short"),
        bearer("poi_" + "x" * 48 + "."),
        bearer("poi_" + "x" * 49),
        basic("x", new_key()),
    ],
    ids=["unknown", "short", "dot", "bad-checksum", "basic-unknown"],
)
def test_unknown_key_is_401(client: TestClient, headers: dict[str, str]) -> None:
    """A `poi_` credential that isn't a stored key is a 401."""
    response = client.get(TASKS, headers=headers)
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json()["message"] == "invalid token"


def test_malformed_key_skips_database(client: TestClient, table: KeyTable) -> None:
    """A credential that can't be a key is refused without a lookup."""
    client.get(TASKS, headers=bearer("poi_short"))
    key = new_key()
    client.get(TASKS, headers=bearer(key[:-1] + ("1" if key[-1] == "0" else "0")))
    assert table.lookups == 0


@pytest.mark.parametrize(
    "headers",
    [bearer("opaque-token"), basic("alice", "password")],
    ids=["opaque-bearer", "basic-password"],
)
def test_other_credentials_pass_through(
    client: TestClient, table: KeyTable, headers: dict[str, str]
) -> None:
    """Credentials that aren't keys are left alone: no lookup, chain's 401."""
    response = client.get(TASKS, headers=headers)
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json()["message"] == "invalid token"
    assert table.lookups == 0


def test_jwt_not_looked_up(client: TestClient, issuer: Issuer, table: KeyTable) -> None:
    """A JWT is the JWT link's: it never reaches the key table."""
    assert (
        client.get(TASKS, headers=bearer(issuer.token())).status_code == HTTPStatus.OK
    )
    assert table.lookups == 0


@pytest.mark.parametrize(
    "fields",
    [
        {"revoked_at": datetime.now(UTC)},
        {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        {"owner": "https://removed.example.org|alice"},
        {"owner": f"{ISSUER}|"},
    ],
    ids=["revoked", "expired", "removed-issuer", "no-subject"],
)
def test_refused_keys_are_401(
    client: TestClient, table: KeyTable, fields: dict[str, Any]
) -> None:
    """Revoked and expired keys, and keys of removed issuers, are 401s."""
    key = new_key()
    table.insert(key, **fields)
    for headers in (bearer(key), basic("x", key)):
        response = client.get(TASKS, headers=headers)
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json()["message"] == "invalid token"


def test_database_down_is_503(client: TestClient, table: KeyTable) -> None:
    """A database outage is a 503 with Retry-After, not a 401."""
    key = new_key()
    table.insert(key)
    table.down = True
    response = client.get(TASKS, headers=bearer(key))
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.headers["retry-after"] == "5"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", KEYS, {"name": "run"}),
        ("GET", KEYS, None),
        ("DELETE", f"{KEYS}/{TASK_ID}", None),
    ],
    ids=["mint", "list", "revoke"],
)
def test_key_management_database_down_is_503(
    client: TestClient,
    issuer: Issuer,
    table: KeyTable,
    method: str,
    path: str,
    body: Any,
) -> None:
    """Managing keys while the database is down is a retryable 503, not 500."""
    table.down = True
    response = client.request(method, path, json=body, headers=bearer(issuer.token()))
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.headers["retry-after"] == "5"


def test_flush_cancelled_keeps_batch(
    table: KeyTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A flush cancelled mid-write keeps its batch for the final flush."""
    key = new_key()
    key_id = table.insert(key)

    async def main() -> None:
        started = asyncio.Event()

        async def slow(conn: Any, used: dict[uuid.UUID, datetime]) -> None:
            started.set()
            await asyncio.sleep(10)

        authenticator = ApiKeyAuthenticator(Pool(), (ISSUER,))
        request: Any = SimpleNamespace(headers={"authorization": f"Bearer {key}"})
        await authenticator.authenticate(request)
        with monkeypatch.context() as patch:
            patch.setattr(api_keys_db, "touch_api_keys", slow)
            flushing = asyncio.create_task(authenticator.flush())
            async with asyncio.timeout(5):
                await started.wait()
            flushing.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await flushing
        await authenticator.aclose()

    asyncio.run(main())
    assert [batch.keys() for batch in table.touched] == [{key_id}]


def principal_for(table: KeyTable, key: str, issuers: tuple[str, ...]) -> Any:
    """Authenticate `key` with a fresh authenticator; principal or error."""

    async def main() -> Any:
        authenticator = ApiKeyAuthenticator(Pool(), issuers)
        request: Any = SimpleNamespace(headers={"authorization": f"Bearer {key}"})
        try:
            return await authenticator.authenticate(request)
        except (UnauthorizedError, ServiceUnavailableError) as exc:
            return exc

    return asyncio.run(main())


def test_principal(table: KeyTable) -> None:
    """The principal is the owner, via the key, with the snapshot's claims."""
    key = new_key()
    snapshot = {"claims": {"sub": "alice", "groups": ["g"]}, "userinfo": {"e": "x"}}
    key_id = table.insert(
        key, owner=f"{GATEWAY}|a|b", scopes=("tasks:read",), claims_snapshot=snapshot
    )
    principal = principal_for(table, key, (ISSUER, GATEWAY))
    assert principal == Principal(
        issuer=GATEWAY,
        subject="a|b",
        via="apikey",
        credential_id=str(key_id),
        scopes=frozenset({"tasks:read"}),
        claims={"sub": "alice", "groups": ["g"]},
        userinfo={"e": "x"},
    )
    assert principal.owner == f"{GATEWAY}|a|b"
    assert principal.claim("e") == "x"


def test_issuer_removed(table: KeyTable) -> None:
    """Removing an issuer from the settings disables its owners' keys."""
    key = new_key()
    table.insert(key)
    assert isinstance(principal_for(table, key, (ISSUER,)), Principal)
    assert isinstance(principal_for(table, key, (GATEWAY,)), UnauthorizedError)


# -- scopes -------------------------------------------------------------------------


def test_read_only_key(
    client: TestClient, issuer: Issuer, tasks: dict[str, Any]
) -> None:
    """A `tasks:read` key may get and list, but not create or cancel."""
    tasks[TASK_ID] = (ALICE, TesTask(id=TASK_ID, state=TesState.RUNNING, executors=[]))
    headers = bearer(minted(client, issuer, scopes=["tasks:read"])["key"])
    assert client.get(TASKS, headers=headers).status_code == HTTPStatus.OK
    assert (
        client.get(f"{TASKS}/{TASK_ID}", headers=headers).status_code == HTTPStatus.OK
    )
    for path in (TASKS, f"{TASKS}/{TASK_ID}:cancel"):
        response = client.post(path, json=TASK, headers=headers)
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json()["message"] == "API key lacks scope tasks:write"
    assert list(tasks) == [TASK_ID]


def test_write_implies_read(
    client: TestClient, issuer: Issuer, tasks: dict[str, Any]
) -> None:
    """A `tasks:write` key may also read."""
    headers = bearer(minted(client, issuer, scopes=["tasks:write"])["key"])
    task_id = client.post(TASKS, json=TASK, headers=headers).json()["id"]
    assert (
        client.get(f"{TASKS}/{task_id}", headers=headers).status_code == HTTPStatus.OK
    )
    response = client.post(f"{TASKS}/{task_id}:cancel", headers=headers)
    assert response.status_code == HTTPStatus.OK


def test_key_without_scopes(client: TestClient, table: KeyTable) -> None:
    """A key without scopes may do nothing."""
    key = new_key()
    table.insert(key, scopes=())
    response = client.get(TASKS, headers=bearer(key))
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["message"] == "API key lacks scope tasks:read"


def test_token_scopes_unaffected(client: TestClient, issuer: Issuer) -> None:
    """Token principals aren't limited by key scopes, whatever they carry."""
    headers = bearer(issuer.token(scope="openid"))
    assert client.post(TASKS, json=TASK, headers=headers).status_code == HTTPStatus.OK


# -- last_used_at ---------------------------------------------------------------


def test_last_used_batched(table: KeyTable) -> None:
    """Uses are written in one batch per flush, never per request."""
    first, second = new_key(), new_key()
    first_id, second_id = table.insert(first), table.insert(second)

    async def main() -> None:
        authenticator = ApiKeyAuthenticator(Pool(), (ISSUER,), flush_interval=3600)
        await authenticator.start()
        for key in (first, second, first, first):
            request: Any = SimpleNamespace(headers={"authorization": f"Bearer {key}"})
            await authenticator.authenticate(request)
        assert table.touched == []
        await authenticator.flush()
        assert len(table.touched) == 1
        assert table.touched[0].keys() == {first_id, second_id}
        await authenticator.flush()  # nothing new: no write
        assert len(table.touched) == 1

        # A failed write is kept and retried with the next batch.
        request = SimpleNamespace(headers={"authorization": f"Bearer {first}"})
        await authenticator.authenticate(request)
        table.down = True
        await authenticator.flush()
        table.down = False
        assert len(table.touched) == 1
        # Shutdown writes what is left.
        await authenticator.aclose()
        assert len(table.touched) == 2  # noqa: PLR2004
        assert table.touched[1].keys() == {first_id}

    asyncio.run(main())
    assert table.rows[first_id]["last_used_at"] is not None


def test_last_used_flushed_in_background(table: KeyTable) -> None:
    """The background task flushes on its interval."""
    key = new_key()
    key_id = table.insert(key)

    async def main() -> None:
        authenticator = ApiKeyAuthenticator(Pool(), (ISSUER,), flush_interval=0.01)
        await authenticator.start()
        request: Any = SimpleNamespace(headers={"authorization": f"Bearer {key}"})
        try:
            await authenticator.authenticate(request)
            for _ in range(200):
                if table.touched:
                    break
                await asyncio.sleep(0.01)
            # Before `aclose`, whose final flush would hide a dead loop.
            assert table.touched
            assert table.touched[0].keys() == {key_id}
        finally:
            await authenticator.aclose()

    asyncio.run(main())


# -- decision service ------------------------------------------------------------


def test_subject_names_the_key() -> None:
    """The AuthZEN subject says how the caller authenticated."""
    authz = Authz(AuthzSettings())
    key = Principal(
        issuer=ISSUER,
        subject="alice",
        via="apikey",
        credential_id="k-1",
        scopes=frozenset({"tasks:read"}),
        # The minting token's scope stays in the snapshot, but isn't sent.
        claims={"scope": "openid profile"},
    )
    token = Principal(issuer=ISSUER, subject="alice", via="oidc", claims={})
    assert authz._subject(key)["properties"] == {
        "iss": ISSUER,
        "via": "apikey",
        "credential_id": "k-1",
        "scope": ["tasks:read"],
        "claims": {},
    }
    assert authz._subject(token)["properties"]["via"] == "oidc"
    assert "credential_id" not in authz._subject(token)["properties"]


# -- settings -----------------------------------------------------------------------


def test_settings_defaults() -> None:
    """Keys are on, 30 days by default, at most 90 days and 20 per owner."""
    settings = ApiKeySettings()
    assert settings.enabled
    assert settings.default_ttl == timedelta(days=30)
    assert settings.max_ttl == timedelta(days=90)
    assert settings.max_per_owner == 20  # noqa: PLR2004


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`POIESIS_AUTH_API_KEYS_*` sets the limits."""
    monkeypatch.setenv("POIESIS_AUTH_API_KEYS_ENABLED", "false")
    monkeypatch.setenv("POIESIS_AUTH_API_KEYS_DEFAULT_TTL", "12h")
    monkeypatch.setenv("POIESIS_AUTH_API_KEYS_MAX_TTL", "7d")
    monkeypatch.setenv("POIESIS_AUTH_API_KEYS_MAX_PER_OWNER", "3")
    settings = ApiKeySettings()
    assert not settings.enabled
    assert (settings.default_ttl, settings.max_ttl) == (
        timedelta(hours=12),
        timedelta(days=7),
    )
    assert settings.max_per_owner == 3  # noqa: PLR2004


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("POIESIS_AUTH_API_KEYS_DEFAULT_TTL", "91d", "exceeds"),
        ("POIESIS_AUTH_API_KEYS_MAX_TTL", "29d", "exceeds"),
        ("POIESIS_AUTH_API_KEYS_MAX_TTL", "0d", "<n>d"),
        ("POIESIS_AUTH_API_KEYS_DEFAULT_TTL", "-1d", "<n>d"),
        ("POIESIS_AUTH_API_KEYS_DEFAULT_TTL", "30", "<n>d"),
        ("POIESIS_AUTH_API_KEYS_MAX_TTL", "P90D", "<n>d"),
        ("POIESIS_AUTH_API_KEYS_MAX_PER_OWNER", "0", "at least 1"),
        ("POIESIS_AUTH_API_KEYS_MAX_PER_OWNER", "-1", "at least 1"),
        ("POIESIS_AUTH_API_KEYS_MAX_PER_OWNER", "many", "integer"),
    ],
)
def test_settings_invalid(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str, message: str
) -> None:
    """Limits that can't hold refuse to start."""
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=message):
        ApiKeySettings()


@pytest.mark.parametrize(
    ("value", "ttl"),
    [("1h", timedelta(hours=1)), ("30d", timedelta(days=30)), ("48h", timedelta(2))],
)
def test_parse_ttl(value: str, ttl: timedelta) -> None:
    """Lifetimes are `<n>d` or `<n>h`."""
    assert parse_ttl(value) == ttl


def test_format_ttl() -> None:
    """Whole days print as days, anything else as hours."""
    assert format_ttl(timedelta(days=90)) == "90d"
    assert format_ttl(timedelta(hours=36)) == "36h"


def test_swagger_ui_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Swagger UI login names a configured issuer and a client."""
    set_issuers(monkeypatch, {"issuer": ISSUER, "audience": AUDIENCE})
    assert AuthSettings().swagger_ui is None
    monkeypatch.setenv("POIESIS_AUTH_SWAGGER_UI_ISSUER", ISSUER)
    monkeypatch.setenv("POIESIS_AUTH_SWAGGER_UI_CLIENT_ID", "poiesis-cli")
    login = AuthSettings().swagger_ui
    assert login is not None
    assert (login.issuer, login.client_id, login.scopes) == (
        ISSUER,
        "poiesis-cli",
        "openid",
    )


@pytest.mark.parametrize(
    ("variables", "message"),
    [
        ({"POIESIS_AUTH_SWAGGER_UI_ISSUER": ISSUER}, "both"),
        ({"POIESIS_AUTH_SWAGGER_UI_CLIENT_ID": "cli"}, "both"),
        (
            {
                "POIESIS_AUTH_SWAGGER_UI_ISSUER": "https://elsewhere.example.org",
                "POIESIS_AUTH_SWAGGER_UI_CLIENT_ID": "cli",
            },
            "not one of the issuers",
        ),
        (
            {
                "POIESIS_AUTH_SWAGGER_UI_ISSUER": GATEWAY,
                "POIESIS_AUTH_SWAGGER_UI_CLIENT_ID": "cli",
            },
            "discovery",
        ),
    ],
    ids=["no-client", "no-issuer", "unknown-issuer", "jwks-uri-issuer"],
)
def test_swagger_ui_settings_invalid(
    monkeypatch: pytest.MonkeyPatch, variables: dict[str, str], message: str
) -> None:
    """An incomplete login, or one at an issuer that can't serve it, refuses."""
    set_issuers(
        monkeypatch,
        {"issuer": ISSUER, "audience": AUDIENCE},
        {"issuer": GATEWAY, "audience": AUDIENCE, "jwksUri": GATEWAY_JWKS},
    )
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=message):
        AuthSettings()


# -- app wiring and OpenAPI ------------------------------------------------------


def chain(client: TestClient) -> list[str]:
    """Return the names of the app's authenticators, in order."""
    app: Any = client.app
    return [authenticator.name for authenticator in app.state.authenticators]


def test_chain_order(client: TestClient) -> None:
    """The key link comes after the JWT link."""
    names = chain(client)
    assert names == ["jwt", "apikey"]


def test_disabled_keys(app_env: pytest.MonkeyPatch, issuer: Issuer) -> None:
    """With keys off there are no key routes and keys don't authenticate."""
    app_env.setenv("POIESIS_AUTH_API_KEYS_ENABLED", "false")
    with TestClient(app_module.create_app()) as client:
        names = chain(client)
        assert names == ["jwt"]
        assert mint(client, issuer.token()).status_code == HTTPStatus.NOT_FOUND
        assert KEYS not in client.get("/openapi.json").json()["paths"]
        assert (
            client.get(TASKS, headers=bearer(new_key())).status_code
            == HTTPStatus.UNAUTHORIZED
        )


def test_openapi_bearer(client: TestClient) -> None:
    """With auth on, the API documents a bearer scheme on its own routes only."""
    spec = client.get("/openapi.json").json()
    assert spec["components"]["securitySchemes"] == {
        "bearer": {
            "type": "http",
            "scheme": "bearer",
            "description": "An access token of a configured issuer, or a "
            "Poiesis API key (`poi_…`).",
        }
    }
    paths = spec["paths"]
    for path, method in ((TASKS, "post"), (TASKS, "get"), (KEYS, "post")):
        assert paths[path][method]["security"] == [{"bearer": []}]
    assert "security" not in paths["/ga4gh/tes/v1/service-info"]["get"]
    assert paths[KEYS]["post"]["tags"] == ["ApiKeys"]
    assert "/poiesis/v1/api-keys/{id}" in paths


def test_openapi_login(app_env: pytest.MonkeyPatch) -> None:
    """With a Swagger UI login, `/docs` offers OIDC with PKCE for its client."""
    app_env.setenv("POIESIS_AUTH_SWAGGER_UI_ISSUER", ISSUER)
    app_env.setenv("POIESIS_AUTH_SWAGGER_UI_CLIENT_ID", "poiesis-cli")
    app_env.setenv("POIESIS_AUTH_SWAGGER_UI_SCOPES", "openid profile")
    with TestClient(app_module.create_app()) as client:
        spec = client.get("/openapi.json").json()
        assert spec["components"]["securitySchemes"]["oidc"] == {
            "type": "openIdConnect",
            "openIdConnectUrl": f"{ISSUER}/.well-known/openid-configuration",
            "description": f"Log in at {ISSUER}.",
        }
        assert spec["paths"][KEYS]["post"]["security"] == [
            {"bearer": []},
            {"oidc": ["openid", "profile"]},
        ]
        docs = client.get("/docs").text
        assert '"clientId": "poiesis-cli"' in docs
        assert '"usePkceWithAuthorizationCodeGrant": true' in docs
        assert '"scopes": "openid profile"' in docs


def test_openapi_without_auth(app_env: pytest.MonkeyPatch) -> None:
    """With auth off there is nothing to authorize and no key routes."""
    app_env.setenv("POIESIS_AUTH_ENABLED", "false")
    with TestClient(app_module.create_app()) as client:
        spec = client.get("/openapi.json").json()
        assert "securitySchemes" not in spec.get("components", {})
        assert KEYS not in spec["paths"]
        assert "initOAuth" not in client.get("/docs").text
