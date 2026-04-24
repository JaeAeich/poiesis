"""Kubernetes client wrappers.

Thin async-friendly facade over the (sync) `kubernetes` Python client.
The official client is synchronous; we run each call inside
`asyncio.to_thread` so it doesn't block the FastAPI event loop.

The signatures here are the only K8s surface the rest of Poiesis uses.
If/when we move to an async client (or to the Rust rewrite's
`kube-rs`), this is the seam that changes.
"""

from poiesis.k8s.client import K8sClient, load_config

__all__ = ["K8sClient", "load_config"]
