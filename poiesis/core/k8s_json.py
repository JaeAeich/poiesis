"""Kubernetes client models from their JSON form, with unknown keys refused.

Operators give Kubernetes objects in chart values as JSON (camelCase).
`from_json` turns such an object into the client's model, so a typo in a
key fails when the API starts rather than when the API server refuses a
TaskPod.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import kubernetes.client

if TYPE_CHECKING:
    from collections.abc import Mapping


def from_json[M](model: type[M], data: Mapping[str, Any]) -> M:
    """A Kubernetes client model from its JSON form (camelCase keys).

    Nested objects (``V1…`` fields) and lists of them (``list[V1…]``)
    become their models too. Other values pass as they are: scalars, lists
    of scalars and ``dict(…)`` fields (e.g. labels) are not converted, and
    no value is type-checked; the API server does that.

    Raises:
        ValueError: A key the model doesn't have, at any depth.
        TypeError: Something other than an object where it expects one.
    """
    if not isinstance(data, dict):
        raise TypeError(f"{model.__name__} must be an object, got {data!r}")
    # Every client model has both maps; the type stubs don't declare them.
    attribute_map: dict[str, str] = getattr(model, "attribute_map")  # noqa: B009
    types: dict[str, str] = getattr(model, "openapi_types")  # noqa: B009
    fields = {v: k for k, v in attribute_map.items()}
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        if key not in fields:
            raise ValueError(f"{model.__name__} has no field {key!r}")
        name = fields[key]
        kwargs[name] = _field_value(types[name], value)
    return model(**kwargs)


def _field_value(kind: str, value: Any) -> Any:
    """``value`` as the client type ``kind`` names (``V1X``, ``list[V1X]``)."""
    if value is None:
        return None
    listed = re.fullmatch(r"list\[(V\w+)\]", kind)
    if listed and isinstance(value, list):
        nested = getattr(kubernetes.client, listed.group(1))
        return [from_json(nested, item) for item in value]
    if re.fullmatch(r"V\w+", kind):
        return from_json(getattr(kubernetes.client, kind), value)
    return value
