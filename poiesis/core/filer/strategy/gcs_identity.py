"""Google Cloud credentials for TIF/TOF from a Kubernetes ServiceAccount token.

Workload Identity Federation: the API projects a ServiceAccount token for
the pool provider's audience into TIF and TOF only. `GcsWorkloadIdentity`
reads it, trades it at Google's Security Token Service for a federated
access token and, when a service account is named, trades that for the
service account's access token at the IAM Credentials API. obstore calls
it for each new token (`GCSStore(credential_provider=...)`).

Nothing here uses the node's metadata server, which every container of
the Pod could reach.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from poiesis.errors import PoiesisError

if TYPE_CHECKING:
    from obstore.store import GCSCredential

logger = logging.getLogger(__name__)

STS_URL = "https://sts.googleapis.com/v1/token"
IAM_CREDENTIALS_URL = "https://iamcredentials.googleapis.com/v1"
#: Scope of the federated token, as Google's client libraries ask for it;
#: IAM still limits it to what the principal is granted.
STS_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
#: Scope of the impersonated service account's token: objects only.
SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"
#: A token this close to expiry is renewed before use.
_REFRESH_MARGIN = timedelta(minutes=5)
_TIMEOUT = httpx.Timeout(30.0)


class GcsIdentityError(PoiesisError, OSError):
    """The ServiceAccount token could not be traded for Google credentials."""


def token_audience(provider: str) -> str:
    """Audience of the ServiceAccount token for pool provider `provider`.

    `provider` is the provider's full name, ``//iam.googleapis.com/projects/
    <number>/locations/global/workloadIdentityPools/<pool>/providers/<id>``.
    A provider made without ``--allowed-audiences`` accepts that name with
    an ``https:`` prefix.
    """
    return f"https:{provider}"


class GcsWorkloadIdentity:
    """obstore credential provider for GCS through Workload Identity Federation."""

    def __init__(
        self,
        provider: str,
        token_file: str,
        service_account: str | None = None,
        *,
        sts_url: str | None = None,
        iam_credentials_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Trade the token in `token_file` at `provider`, as `service_account`.

        Without `service_account` the federated token itself is used: grant
        the pool's principal access to the buckets.
        """
        self.provider = provider
        self.token_file = token_file
        self.service_account = service_account
        self.sts_url = sts_url or STS_URL
        self.iam_credentials_url = iam_credentials_url or IAM_CREDENTIALS_URL
        self._transport = transport
        self._lock = asyncio.Lock()
        self._cached: GCSCredential | None = None

    async def __call__(self) -> GCSCredential:
        """A bearer token for GCS, renewed shortly before it expires."""
        async with self._lock:
            cached = self._cached
            if cached is not None and not _expiring(cached["expires_at"]):
                return cached
            async with httpx.AsyncClient(
                transport=self._transport, timeout=_TIMEOUT
            ) as client:
                credential = await self._fetch(client)
            self._cached = credential
            return credential

    async def _fetch(self, client: httpx.AsyncClient) -> GCSCredential:
        subject = Path(self.token_file).read_text().strip()
        federated = await _post(
            client,
            self.sts_url,
            json={
                "grantType": "urn:ietf:params:oauth:grant-type:token-exchange",
                "audience": self.provider,
                "scope": STS_SCOPE,
                "requestedTokenType": "urn:ietf:params:oauth:token-type:access_token",
                "subjectTokenType": "urn:ietf:params:oauth:token-type:jwt",
                "subjectToken": subject,
            },
        )
        token = _field(federated, "access_token", self.sts_url)
        expires_at = _expiry_in(federated)
        if not self.service_account:
            logger.debug("Federated token from %s", self.sts_url)
            return {"token": token, "expires_at": expires_at}
        url = (
            f"{self.iam_credentials_url}/projects/-/serviceAccounts/"
            f"{quote(self.service_account, safe='@')}:generateAccessToken"
        )
        impersonated = await _post(
            client,
            url,
            json={"scope": [SCOPE]},
            headers={"Authorization": f"Bearer {token}"},
        )
        logger.debug("Access token for %s", self.service_account)
        return {
            "token": _field(impersonated, "accessToken", url),
            "expires_at": _parse_time(_field(impersonated, "expireTime", url)),
        }


async def _post(
    client: httpx.AsyncClient,
    url: str,
    json: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        response = await client.post(url, json=json, headers=headers)
    except httpx.HTTPError as e:
        raise GcsIdentityError(f"POST {url}: {e}") from e
    if not response.is_success:
        raise GcsIdentityError(
            f"POST {url} returned {response.status_code}: {response.text[:300]}"
        )
    body = response.json()
    if not isinstance(body, dict):
        raise GcsIdentityError(f"POST {url}: answer is not a JSON object")
    return body


def _field(body: dict[str, Any], name: str, url: str) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value:
        raise GcsIdentityError(f"POST {url}: answer has no {name}")
    return value


def _expiry_in(body: dict[str, Any]) -> datetime | None:
    seconds = body.get("expires_in")
    if not isinstance(seconds, int | float):
        return None
    return datetime.now(UTC) + timedelta(seconds=seconds)


def _parse_time(value: str) -> datetime:
    """An RFC 3339 time such as ``2026-11-22T10:00:00Z``, in UTC."""
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _expiring(expires_at: datetime | None) -> bool:
    return expires_at is not None and expires_at - _REFRESH_MARGIN <= datetime.now(UTC)
