"""Named object stores: which store serves the bucket an object-store URL names.

A deployment has a default store per provider (the chart's ``s3``, ``gcs``
and ``azure`` blocks) and may add named stores (``objectStores``), each
with its own endpoint, credentials and bucket patterns. A pattern is a
bucket name (a container, for Azure), or a prefix ending in ``*``. A URL
``s3://bucket/key`` goes to the named store of that provider whose patterns
match the bucket, else to the provider's default store. Patterns of two
stores of one provider may not overlap, so at most one store matches;
`check_stores` refuses overlaps when the API starts.

Credentials stay in Secrets: TIF and TOF read a store's keys from env vars
named by `secret_env_name`, set from the store's ``existingSecret``.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

if TYPE_CHECKING:
    from collections.abc import Iterable

#: Provider of a store → the URL scheme it serves.
PROVIDER_SCHEMES: dict[str, str] = {"s3": "s3", "gcs": "gs", "azure": "az"}

#: S3 server-side encryption modes; SSE-C needs a key per request.
S3_SSE_MODES = frozenset({"AES256", "aws:kms", "aws:kms:dsse"})

#: Keys a store's ``existingSecret`` may hold, by provider. A key in
#: `OPTIONAL_SECRET_KEYS` may be missing.
SECRET_KEYS: dict[str, tuple[str, ...]] = {
    "s3": ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"),
    "gcs": ("GOOGLE_SERVICE_ACCOUNT_KEY",),
    "azure": ("AZURE_STORAGE_ACCOUNT_KEY", "AZURE_STORAGE_SAS_TOKEN"),
}
OPTIONAL_SECRET_KEYS = frozenset(
    {"AWS_SESSION_TOKEN", "AZURE_STORAGE_ACCOUNT_KEY", "AZURE_STORAGE_SAS_TOKEN"}
)

#: Options each provider takes, besides name, provider, buckets, anonymous.
_OPTIONS: dict[str, frozenset[str]] = {
    "s3": frozenset(
        {
            "endpoint",
            "region",
            "existing_secret",
            "role_arn",
            "virtual_hosted_style",
            "server_side_encryption",
            "kms_key_id",
            "requester_pays",
        }
    ),
    "gcs": frozenset(
        {
            "endpoint",
            "existing_secret",
            "workload_identity_provider",
            "service_account",
        }
    ),
    "azure": frozenset(
        {"endpoint", "account_name", "existing_secret", "client_id", "tenant_id"}
    ),
}
_COMMON = frozenset({"name", "provider", "buckets", "anonymous"})

#: A store name: a DNS label, short enough for the env var and volume names
#: made from it.
_NAME = r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$"
#: A bucket pattern: a bucket name, a prefix ending in ``*``, or ``*``.
_PATTERN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)?\*?$")


class ObjectStoreSpec(BaseModel):
    """One named object store, as in the chart's ``objectStores`` (camelCase).

    Attributes:
        name: Names the store in errors and in its env vars.
        provider: ``s3``, ``gcs`` or ``azure``.
        buckets: Bucket names (containers, for Azure) and ``prefix*``
            patterns the store serves.
        anonymous: Send unsigned requests, for public buckets; no
            credentials.
        endpoint: S3 endpoint, GCS base URL or Azure blob endpoint; None
            for the provider's public one.
        region: S3 region.
        existing_secret: Secret in the TaskPod namespace holding the
            store's keys (`SECRET_KEYS`).
        role_arn: IAM role TIF/TOF assume with a ServiceAccount token.
        virtual_hosted_style: S3 virtual-hosted-style requests.
        server_side_encryption: S3 SSE mode of uploads.
        kms_key_id: KMS key for ``aws:kms`` and ``aws:kms:dsse``.
        requester_pays: Send ``x-amz-request-payer: requester``.
        account_name: Azure storage account.
        client_id: Azure workload identity client ID.
        tenant_id: Azure workload identity tenant ID.
        workload_identity_provider: Full name of the Google workload
            identity pool provider.
        service_account: Google service account to impersonate.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", frozen=True
    )

    name: str = Field(pattern=_NAME, max_length=40)
    provider: Literal["s3", "gcs", "azure"]
    buckets: tuple[str, ...] = Field(min_length=1)
    anonymous: bool = False
    endpoint: str | None = None
    region: str | None = None
    existing_secret: str | None = None
    role_arn: str | None = None
    virtual_hosted_style: bool = False
    server_side_encryption: str | None = None
    kms_key_id: str | None = None
    requester_pays: bool = False
    account_name: str | None = None
    client_id: str | None = None
    tenant_id: str | None = None
    workload_identity_provider: str | None = None
    service_account: str | None = None

    @field_validator(
        "endpoint",
        "region",
        "existing_secret",
        "role_arn",
        "server_side_encryption",
        "kms_key_id",
        "account_name",
        "client_id",
        "tenant_id",
        "workload_identity_provider",
        "service_account",
        mode="before",
    )
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        """``""``, as the chart writes an option left blank, is unset."""
        return None if value == "" else value

    @field_validator("buckets")
    @classmethod
    def _check_patterns(cls, buckets: tuple[str, ...]) -> tuple[str, ...]:
        for pattern in buckets:
            if not pattern or not _PATTERN.match(pattern):
                raise ValueError(
                    f"bucket pattern {pattern!r} is not a bucket name, a prefix "
                    "ending in '*', or '*'"
                )
        return buckets

    @model_validator(mode="after")
    def _check(self) -> ObjectStoreSpec:
        """Refuse options of another provider and credentials that clash."""
        where = f"object store {self.name!r}"
        foreign = sorted(
            to_camel(f)
            for f in self.model_fields_set - _COMMON - _OPTIONS[self.provider]
            if getattr(self, f)
        )
        if foreign:
            raise ValueError(
                f"{where}: {', '.join(foreign)} not an option of provider "
                f"{self.provider}"
            )
        if self.endpoint and not self.endpoint.startswith(("http://", "https://")):
            raise ValueError(f"{where}: endpoint must be an http(s):// URL")
        sources = [
            to_camel(f)
            for f in (
                "existing_secret",
                "role_arn",
                "client_id",
                "workload_identity_provider",
            )
            if getattr(self, f)
        ]
        if self.anonymous and sources:
            raise ValueError(f"{where}: anonymous takes no {', '.join(sources)}")
        if len(sources) > 1:
            raise ValueError(f"{where}: set one of {', '.join(sources)}")
        check = {
            "s3": self._check_s3,
            "gcs": self._check_gcs,
            "azure": self._check_azure,
        }
        check[self.provider](where)
        return self

    def _check_s3(self, where: str) -> None:
        sse = self.server_side_encryption
        if sse is not None and sse not in S3_SSE_MODES:
            raise ValueError(
                f"{where}: serverSideEncryption must be one of "
                f"{sorted(S3_SSE_MODES)}, got {sse!r}"
            )
        if self.kms_key_id and sse not in {"aws:kms", "aws:kms:dsse"}:
            raise ValueError(
                f"{where}: kmsKeyId needs serverSideEncryption aws:kms or aws:kms:dsse"
            )

    def _check_gcs(self, where: str) -> None:
        provider = self.workload_identity_provider
        if not (self.anonymous or self.existing_secret or provider):
            raise ValueError(
                f"{where}: needs existingSecret, workloadIdentityProvider or "
                "anonymous: without any, TIF and TOF would use the node's "
                "metadata server, which executors reach too"
            )
        if provider and not provider.startswith("//"):
            raise ValueError(
                f"{where}: workloadIdentityProvider is the provider's full name, "
                "//iam.googleapis.com/projects/<number>/locations/global/"
                "workloadIdentityPools/<pool>/providers/<provider>"
            )
        if self.service_account and not provider:
            raise ValueError(f"{where}: serviceAccount needs workloadIdentityProvider")

    def _check_azure(self, where: str) -> None:
        if not self.account_name:
            raise ValueError(f"{where}: needs accountName")
        if bool(self.client_id) != bool(self.tenant_id):
            raise ValueError(f"{where}: clientId and tenantId are set together")

    @property
    def scheme(self) -> str:
        """The URL scheme the store serves."""
        return PROVIDER_SCHEMES[self.provider]

    def serves(self, bucket: str) -> bool:
        """Whether one of the store's patterns matches `bucket`."""
        return any(bucket_matches(p, bucket) for p in self.buckets)

    def secret_keys(self) -> tuple[str, ...]:
        """Keys TIF/TOF read from the store's Secret; none without one."""
        return SECRET_KEYS[self.provider] if self.existing_secret else ()


def bucket_matches(pattern: str, bucket: str) -> bool:
    """``data*`` matches buckets starting with ``data``; ``data``, only ``data``."""
    if pattern.endswith("*"):
        return bucket.startswith(pattern[:-1])
    return bucket == pattern


def patterns_overlap(a: str, b: str) -> bool:
    """Whether some bucket matches both patterns."""
    a_prefix, b_prefix = a.endswith("*"), b.endswith("*")
    if a_prefix and b_prefix:
        return a.startswith(b[:-1]) or b.startswith(a[:-1])
    if a_prefix:
        return b.startswith(a[:-1])
    if b_prefix:
        return a.startswith(b[:-1])
    return a == b


def check_stores(stores: Iterable[ObjectStoreSpec]) -> None:
    """Refuse duplicate names and patterns two stores of a provider share."""
    seen: list[ObjectStoreSpec] = []
    names: set[str] = set()
    for store in stores:
        if store.name in names:
            raise ValueError(f"two object stores are named {store.name!r}")
        names.add(store.name)
        for other in seen:
            if other.provider != store.provider:
                continue
            for a in other.buckets:
                for b in store.buckets:
                    if patterns_overlap(a, b):
                        raise ValueError(
                            f"object stores {other.name!r} ({a!r}) and "
                            f"{store.name!r} ({b!r}) both match some "
                            f"{store.provider} buckets; make their bucket "
                            "patterns disjoint"
                        )
        seen.append(store)


def find_store(
    stores: Iterable[ObjectStoreSpec], scheme: str, bucket: str
) -> ObjectStoreSpec | None:
    """The named store for `bucket` under `scheme`; None for the default store."""
    return next((s for s in stores if s.scheme == scheme and s.serves(bucket)), None)


def parse_stores(raw: str | None) -> tuple[ObjectStoreSpec, ...]:
    """Stores from their JSON list; empty or unset is none. Checked."""
    if not raw or not raw.strip():
        return ()
    entries = json.loads(raw)
    if not isinstance(entries, list):
        raise ValueError("object stores must be a JSON list")  # noqa: TRY004
    stores = tuple(ObjectStoreSpec.model_validate(e) for e in entries)
    check_stores(stores)
    return stores


def dump_stores(stores: Iterable[ObjectStoreSpec]) -> str:
    """The JSON list `parse_stores` reads back; options left default are omitted."""
    return json.dumps(
        [
            s.model_dump(mode="json", by_alias=True, exclude_defaults=True)
            for s in stores
        ],
        separators=(",", ":"),
    )


def secret_env_name(store: str, key: str) -> str:
    """Env var through which TIF/TOF get `key` of store `store`'s Secret.

    ``POIESIS_STORE_<NAME>_<KEY>``, the name upper case with ``-`` as ``_``.
    Store names are lower case and the keys share no suffix, so two stores
    never get the same variable.
    """
    return f"POIESIS_STORE_{store.upper().replace('-', '_')}_{key}"


def gcs_token_name(provider: str, default_provider: str | None) -> str:
    """Name of the identity token for Google pool provider `provider`.

    ``gcp`` for the default store's provider, so stores sharing it share
    the token; otherwise named after the provider, so each audience gets
    one token.
    """
    if provider == default_provider:
        return "gcp"
    return f"gcp-{hashlib.sha256(provider.encode()).hexdigest()[:10]}"
