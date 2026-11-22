"""Named object stores next to each provider's default store (#198).

A URL ``s3://bucket/key`` goes to the named store of its provider whose
bucket patterns match, else to the provider's default store. Overlapping
patterns are refused at startup. Each store's keys reach TIF/TOF only, as
references to its Secret; a store can be anonymous (unsigned requests).
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient
from kubernetes.client import ApiClient
from obstore.store import S3Store
from pydantic import ValidationError

from poiesis.api.app import create_app
from poiesis.api.settings import AuthSettings, Settings
from poiesis.api.tes.models import TesExecutor, TesInput, TesOutput, TesTask
from poiesis.core.constants import (
    DRS_OBJECT_STORES_ENV,
    IDENTITY_TOKEN_DIR,
    OBJECT_STORE_DEFAULTS_ENV,
    OBJECT_STORES_ENV,
)
from poiesis.core.services.filer.object_stores import (
    ObjectStoreSpec,
    bucket_matches,
    check_stores,
    dump_stores,
    find_store,
    gcs_token_name,
    parse_stores,
    patterns_overlap,
    secret_env_name,
)
from poiesis.core.services.filer.strategy import drs_filer, object_store_filer
from poiesis.core.services.filer.strategy.object_store_filer import (
    ObjectStoreError,
    ObjectUrl,
    make_store,
)
from poiesis.core.taskpod import RuntimeConfig, build_taskpod_job

GCS_PROVIDER = (
    "//iam.googleapis.com/projects/123/locations/global/"
    "workloadIdentityPools/other/providers/cluster"
)

#: A public AWS bucket set, an on-prem Ceph with its own keys, and a second
#: Google project through workload identity.
STORES = [
    {
        "name": "open-data",
        "provider": "s3",
        "buckets": ["1000genomes", "gnomad-*"],
        "region": "us-east-1",
        "anonymous": True,
    },
    {
        "name": "ceph",
        "provider": "s3",
        "buckets": ["lab-*"],
        "endpoint": "http://ceph:7480",
        "existingSecret": "poiesis-ceph",
    },
    {
        "name": "other-project",
        "provider": "gcs",
        "buckets": ["shared"],
        "workloadIdentityProvider": GCS_PROVIDER,
    },
]

STORAGE_ENV = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_ENDPOINT_URL",
    "AWS_REGION",
    "POIESIS_TASKPOD_S3_SECRET",
    "POIESIS_TASKPOD_EXTRA_ENV",
    "POIESIS_TASKPOD_EXTRA_VOLUMES",
    "POIESIS_S3_ENABLED",
    "POIESIS_S3_ROLE_ARN",
    "POIESIS_S3_ANONYMOUS",
    "POIESIS_GCS_ENABLED",
    "POIESIS_GCS_ANONYMOUS",
    "POIESIS_TASKPOD_GCS_SECRET",
    "POIESIS_GCS_WORKLOAD_IDENTITY_PROVIDER",
    "POIESIS_AZURE_ENABLED",
    "POIESIS_AZURE_ANONYMOUS",
    "POIESIS_AZURE_ACCOUNT_NAME",
    "POIESIS_TASKPOD_AZURE_SECRET",
    OBJECT_STORES_ENV,
    OBJECT_STORE_DEFAULTS_ENV,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in STORAGE_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("POIESIS_TASKPOD_DATABASE_SECRET", "task-db")


def spec(**values: object) -> ObjectStoreSpec:
    return ObjectStoreSpec.model_validate(
        {"name": "x", "provider": "s3", "buckets": ["b"], **values}
    )


def settings() -> Settings:
    return Settings(auth=AuthSettings(enabled=False))


def task(*urls: str) -> TesTask:
    return TesTask(
        id="t1",
        inputs=[TesInput(path=f"/in/{n}", url=u) for n, u in enumerate(urls)],
        outputs=[TesOutput(path=f"/out/{n}", url=u) for n, u in enumerate(urls)],
        executors=[TesExecutor(image="busybox:1.36", command=["true"])],
    )


def pod_spec(config: RuntimeConfig, *urls: str) -> dict:
    _, job = build_taskpod_job(task(*urls), config)
    return ApiClient().sanitize_for_serialization(job.spec.template.spec)


def containers(spec: dict) -> dict[str, dict]:
    return {c["name"]: c for c in [*spec["initContainers"], *spec["containers"]]}


def env(container: dict) -> dict[str, dict]:
    return {e["name"]: e for e in container.get("env", [])}


# --- Matching -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "bucket", "matches"),
    [
        ("data", "data", True),
        ("data", "data2", False),
        ("data*", "data", True),
        ("data*", "data-raw", True),
        ("data*", "dat", False),
        ("*", "anything", True),
        ("Data", "data", False),
    ],
)
def test_bucket_patterns(pattern: str, bucket: str, matches: bool) -> None:
    """A name matches itself; ``prefix*`` matches every bucket it starts."""
    assert bucket_matches(pattern, bucket) is matches


def test_a_named_store_serves_its_buckets_and_only_of_its_provider() -> None:
    stores = parse_stores(json.dumps(STORES))
    assert find_store(stores, "s3", "gnomad-v4").name == "open-data"
    assert find_store(stores, "s3", "lab-2").name == "ceph"
    assert find_store(stores, "gs", "shared").name == "other-project"
    # No pattern matches: the default store.
    assert find_store(stores, "s3", "elsewhere") is None
    # A gcs store serves no s3:// bucket of the same name.
    assert find_store(stores, "s3", "shared") is None


@pytest.mark.parametrize(
    ("a", "b", "overlap"),
    [
        ("data", "data", True),
        ("data", "other", False),
        ("data*", "data-raw", True),
        ("data-raw", "data*", True),
        ("data*", "dat*", True),
        ("data*", "date*", False),
        ("*", "x", True),
        ("lab-a", "lab-b*", False),
    ],
)
def test_pattern_overlap(a: str, b: str, overlap: bool) -> None:
    assert patterns_overlap(a, b) is overlap


def test_overlapping_stores_of_one_provider_are_refused() -> None:
    stores = [
        spec(name="a", buckets=["lab-*"], anonymous=True),
        spec(name="b", buckets=["lab-archive"], anonymous=True),
    ]
    with pytest.raises(ValueError, match=r"'a' \('lab-\*'\) and 'b'"):
        check_stores(stores)


def test_the_same_bucket_under_two_providers_is_allowed() -> None:
    check_stores(
        [
            spec(name="a", buckets=["data"], anonymous=True),
            spec(
                name="b",
                provider="azure",
                buckets=["data"],
                accountName="acct",
                anonymous=True,
            ),
        ]
    )


def test_duplicate_store_names_are_refused() -> None:
    with pytest.raises(ValueError, match="two object stores are named 'a'"):
        check_stores(
            [
                spec(name="a", buckets=["x"], anonymous=True),
                spec(name="a", buckets=["y"], anonymous=True),
            ]
        )


@pytest.mark.parametrize(
    ("values", "match"),
    [
        ({"name": "Ceph_1"}, "should match pattern"),
        ({"buckets": []}, "at least 1 item"),
        ({"buckets": ["a*b"]}, "not a bucket name"),
        ({"accountName": "acct"}, "accountName not an option of provider s3"),
        ({"endpoint": "ceph:7480"}, "http"),
        ({"anonymous": True, "existingSecret": "s"}, "anonymous takes no"),
        ({"existingSecret": "s", "roleArn": "arn:x"}, "set one of"),
        ({"kmsKeyId": "k"}, "kmsKeyId needs"),
        ({"provider": "gcs"}, "needs existingSecret, workloadIdentityProvider"),
        (
            {"provider": "gcs", "workloadIdentityProvider": "projects/1"},
            "full name",
        ),
        ({"provider": "azure", "anonymous": True}, "needs accountName"),
        (
            {"provider": "azure", "accountName": "a", "clientId": "c"},
            "set together",
        ),
        ({"secret": "s"}, "Extra inputs"),
    ],
)
def test_unusable_store_options_are_refused(values: dict, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        spec(**values)


def test_blank_options_are_unset() -> None:
    """The chart writes options left blank as ``""``."""
    store = spec(anonymous=True, endpoint="", existingSecret="", accountName="")
    assert store.endpoint is None
    assert store.existing_secret is None


def test_secret_env_names_differ_per_store() -> None:
    names = {
        secret_env_name(store, key)
        for store in ("a", "a-b", "b", "aws", "a-aws")
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
    }
    assert len(names) == 15  # noqa: PLR2004
    assert secret_env_name("a-b", "AWS_ACCESS_KEY_ID") == (
        "POIESIS_STORE_A_B_AWS_ACCESS_KEY_ID"
    )


# --- API startup ----------------------------------------------------------------


def test_overlapping_stores_stop_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    stores = [*STORES, {**STORES[0], "name": "more", "buckets": ["gnomad-v4"]}]
    monkeypatch.setenv(OBJECT_STORES_ENV, json.dumps(stores))
    with pytest.raises(ValueError, match=f"{OBJECT_STORES_ENV} is invalid"):
        settings()


def test_unknown_store_option_stops_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OBJECT_STORES_ENV, json.dumps([{**STORES[0], "bucket": "x"}]))
    with pytest.raises(ValueError, match=f"{OBJECT_STORES_ENV} is invalid"):
        settings()


def test_extra_env_cannot_set_a_store_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "POIESIS_TASKPOD_EXTRA_ENV",
        json.dumps([{"name": "POIESIS_STORE_CEPH_AWS_ACCESS_KEY_ID", "value": "x"}]),
    )
    with pytest.raises(ValueError, match="collides with a chart-internal env var"):
        settings()


def test_extra_volume_cannot_take_a_token_volume_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OBJECT_STORES_ENV, json.dumps(STORES))
    name = f"{gcs_token_name(GCS_PROVIDER, None)}-identity-token"
    monkeypatch.setenv(
        "POIESIS_TASKPOD_EXTRA_VOLUMES", json.dumps([{"name": name, "emptyDir": {}}])
    )
    with pytest.raises(ValueError, match="identity token"):
        settings()


# --- TaskPod wiring -------------------------------------------------------------


def test_two_stores_reach_tif_and_tof_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """The table (no secret values) and Secret references, on the filers only."""
    monkeypatch.setenv("POIESIS_TASKPOD_S3_SECRET", "poiesis-s3")
    monkeypatch.setenv(OBJECT_STORES_ENV, json.dumps(STORES))
    spec_ = pod_spec(settings().runtime_config(), "s3://lab-1/in", "s3://other/in")
    found = containers(spec_)
    for name in ("tif", "tof"):
        filer = env(found[name])
        table = json.loads(filer[OBJECT_STORES_ENV]["value"])
        assert [s["name"] for s in table] == ["open-data", "ceph", "other-project"]
        assert filer[OBJECT_STORE_DEFAULTS_ENV]["value"] == "s3"
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            ref = filer[secret_env_name("ceph", key)]["valueFrom"]["secretKeyRef"]
            assert ref["name"] == "poiesis-ceph"
            assert ref["key"] == key
            assert ref.get("optional") is (True if key == "AWS_SESSION_TOKEN" else None)
        # The default store's keys stay as they were.
        assert filer["AWS_ACCESS_KEY_ID"]["valueFrom"]["secretKeyRef"]["name"] == (
            "poiesis-s3"
        )
        assert not [n for n in filer if n.startswith("POIESIS_STORE_OPEN_DATA")]
    for name, container in found.items():
        if name in ("tif", "tof"):
            continue
        assert not [n for n in env(container) if n.startswith("POIESIS_STORE_")], name
        assert OBJECT_STORES_ENV not in env(container), name


def test_named_workload_identity_gets_its_own_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One token per audience: the second Google pool provider gets its own."""
    monkeypatch.setenv(
        OBJECT_STORES_ENV,
        json.dumps(
            [
                *STORES,
                {
                    "name": "aws-private",
                    "provider": "s3",
                    "buckets": ["private"],
                    "roleArn": "arn:aws:iam::1:role/r",
                },
                {
                    "name": "aws-private-2",
                    "provider": "s3",
                    "buckets": ["private-2"],
                    "roleArn": "arn:aws:iam::1:role/r2",
                },
            ]
        ),
    )
    config = settings().runtime_config()
    gcp = gcs_token_name(GCS_PROVIDER, None)
    assert config.filer_identity_audiences == {
        "aws": "sts.amazonaws.com",
        gcp: f"https:{GCS_PROVIDER}",
    }
    found = containers(pod_spec(config, "s3://lab-1/in"))
    mounts = {m["mountPath"] for m in found["tof"]["volumeMounts"]}
    assert f"{IDENTITY_TOKEN_DIR}/{gcp}" in mounts
    assert f"{IDENTITY_TOKEN_DIR}/aws" in mounts
    # No default-store variables for a named store's role.
    assert "AWS_ROLE_ARN" not in env(found["tof"])


def test_the_default_store_shares_its_token_with_a_named_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POIESIS_GCS_ENABLED", "true")
    monkeypatch.setenv("POIESIS_GCS_WORKLOAD_IDENTITY_PROVIDER", GCS_PROVIDER)
    monkeypatch.setenv(OBJECT_STORES_ENV, json.dumps(STORES))
    assert settings().runtime_config().filer_identity_audiences == {
        "gcp": f"https:{GCS_PROVIDER}"
    }


def test_no_named_stores_change_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POIESIS_TASKPOD_S3_SECRET", "poiesis-s3")
    found = containers(pod_spec(settings().runtime_config(), "s3://b/k"))
    for container in found.values():
        names = set(env(container))
        assert OBJECT_STORES_ENV not in names
        assert OBJECT_STORE_DEFAULTS_ENV not in names


# --- Submit and service-info ----------------------------------------------------


def test_only_named_stores_accept_their_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default S3 off: a bucket no named store serves is a 400 naming it."""
    monkeypatch.setenv(OBJECT_STORES_ENV, json.dumps(STORES))
    config = settings().runtime_config()
    build_taskpod_job(
        task("s3://lab-1/in", "s3://gnomad-v4/x", "gs://shared/k"), config
    )
    with pytest.raises(ValueError, match="names S3 bucket 'private', which no store"):
        build_taskpod_job(task("s3://lab-1/in", "s3://private/k"), config)
    with pytest.raises(ValueError, match="no Azure Blob Storage credentials"):
        build_taskpod_job(task("az://c/k"), config)


def test_the_default_store_takes_the_other_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POIESIS_TASKPOD_S3_SECRET", "poiesis-s3")
    monkeypatch.setenv(OBJECT_STORES_ENV, json.dumps(STORES))
    build_taskpod_job(task("s3://private/k"), settings().runtime_config())


def test_service_info_lists_schemes_of_named_stores_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OBJECT_STORES_ENV, json.dumps(STORES))
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    body = TestClient(create_app()).get("/ga4gh/tes/v1/service-info").json()
    assert body["storage"] == [
        "ftp://",
        "ftps://",
        "gs://",
        "http://",
        "https://",
        "s3://",
    ]
    assert "ceph" not in json.dumps(body)


def test_drs_offers_the_schemes_of_named_stores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OBJECT_STORES_ENV, json.dumps(STORES))
    monkeypatch.setenv("POIESIS_DRS_ENABLED", "true")
    found = containers(pod_spec(settings().runtime_config(), "s3://lab-1/k"))
    assert env(found["tif"])[DRS_OBJECT_STORES_ENV]["value"] == "s3,gs"


# --- Filer ----------------------------------------------------------------------


@pytest.fixture
def filer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """TIF/TOF env: the default S3 store on SeaweedFS, and the named stores."""
    monkeypatch.setenv(OBJECT_STORES_ENV, dump_stores(parse_stores(json.dumps(STORES))))
    monkeypatch.setenv(OBJECT_STORE_DEFAULTS_ENV, "s3")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://seaweedfs:9000")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "default-id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "default-secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "default-token")
    monkeypatch.setenv(secret_env_name("ceph", "AWS_ACCESS_KEY_ID"), "ceph-id")
    monkeypatch.setenv(secret_env_name("ceph", "AWS_SECRET_ACCESS_KEY"), "ceph-secret")


class Recorder:
    """Stands in for `S3Store`: keeps the AWS env and options it was built with."""

    def __init__(self) -> None:
        self.built: list[tuple[dict[str, str], dict]] = []

    def __call__(self, bucket: str, **options: object) -> object:
        aws = {k: v for k, v in os.environ.items() if k.startswith("AWS_")}
        self.built.append((aws, {"bucket": bucket, **options}))
        return object()


@pytest.mark.usefixtures("filer_env")
def test_named_store_is_built_with_its_own_env_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default store's endpoint and keys never reach a named store."""
    recorder = Recorder()
    monkeypatch.setattr(object_store_filer, "S3Store", recorder)
    make_store(ObjectUrl("s3", "lab-1", "k"))
    make_store(ObjectUrl("s3", "gnomad-v4", "k"))
    make_store(ObjectUrl("s3", "private", "k"))
    (ceph_env, ceph), (open_env, open_), (default_env, _) = recorder.built
    assert ceph_env == {
        "AWS_ENDPOINT_URL": "http://ceph:7480",
        "AWS_ACCESS_KEY_ID": "ceph-id",
        "AWS_SECRET_ACCESS_KEY": "ceph-secret",
    }
    assert ceph["client_options"]["allow_http"] is True
    assert open_env == {"AWS_REGION": "us-east-1"}
    assert open_["config"] == {"skip_signature": True}
    assert default_env["AWS_ACCESS_KEY_ID"] == "default-id"
    assert default_env["AWS_ENDPOINT_URL"] == "http://seaweedfs:9000"
    # And the process env is back as it was.
    assert os.environ["AWS_SESSION_TOKEN"] == "default-token"
    assert "AWS_REGION" not in os.environ


@pytest.mark.usefixtures("filer_env")
def test_anonymous_named_store_builds_next_to_default_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A half set of default keys would fail the build if it leaked in."""
    monkeypatch.delenv("AWS_ACCESS_KEY_ID")
    store = make_store(ObjectUrl("s3", "1000genomes", "k"))
    assert isinstance(store, S3Store)
    assert store.config == {"bucket": "1000genomes", "skip_signature": "true"}


def test_anonymous_default_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POIESIS_S3_ANONYMOUS", "true")
    monkeypatch.setenv("POIESIS_GCS_ANONYMOUS", "true")
    monkeypatch.setenv("POIESIS_AZURE_ANONYMOUS", "true")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_NAME", "acct")
    for scheme in ("s3", "gs", "az"):
        store = make_store(ObjectUrl(scheme, "public", "k"))
        assert store.config["skip_signature"] == "true", scheme


@pytest.mark.usefixtures("filer_env")
def test_unserved_bucket_fails_in_the_filer_when_the_default_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OBJECT_STORE_DEFAULTS_ENV, "")
    with pytest.raises(ObjectStoreError, match="serves s3://private"):
        make_store(ObjectUrl("s3", "private", "k"))


@pytest.mark.usefixtures("filer_env")
def test_drs_skips_object_store_urls_no_store_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DRS-resolved URLs go through the same lookup as a task's own."""
    monkeypatch.setenv(OBJECT_STORE_DEFAULTS_ENV, "")
    monkeypatch.setenv("POIESIS_DRS_ENABLED", "true")
    monkeypatch.setenv(DRS_OBJECT_STORES_ENV, "s3")
    obj = {
        "access_methods": [
            {"type": "s3", "access_url": {"url": "s3://private/k"}},
            {"type": "s3", "access_url": {"url": "s3://lab-1/k"}},
        ]
    }
    monkeypatch.setattr(drs_filer, "_get_json", lambda _url, _uri: obj)
    assert drs_filer.resolve("drs://drs.example.org/o") == ("s3://lab-1/k", {})
    obj["access_methods"].pop()
    with pytest.raises(drs_filer.DrsError, match="no access method"):
        drs_filer.resolve("drs://drs.example.org/o")
