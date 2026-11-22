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
    become their models too. ``str``, ``int`` and ``bool`` values, and
    lists of them, are checked against the field's type; other kinds
    (``dict(…)`` fields such as labels, ``object``, dates) pass as they
    are, for the API server to check.

    Raises:
        ValueError: A key the model doesn't have, at any depth.
        TypeError: A value of the wrong JSON type, at any depth.
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
        kwargs[name] = _field_value(types[name], value, f"{model.__name__}.{key}")
    return model(**kwargs)


#: JSON types of the client's scalar type names (bool is not an int here).
_SCALARS: dict[str, tuple[type, ...]] = {"str": (str,), "int": (int,), "bool": (bool,)}


def _field_value(kind: str, value: Any, where: str = "") -> Any:
    """``value`` as the client type ``kind`` names (``V1X``, ``list[…]``, scalars).

    Raises:
        TypeError: ``value`` doesn't fit ``kind``.
    """
    if value is None:
        return None
    listed = re.fullmatch(r"list\[(.+)\]", kind)
    if listed:
        if not isinstance(value, list):
            raise TypeError(f"{where or kind} must be a list, got {value!r}")
        if any(item is None for item in value):
            raise TypeError(f"{where or kind} must not hold null, got {value!r}")
        return [_field_value(listed.group(1), item, where) for item in value]
    if re.fullmatch(r"V\w+", kind):
        return from_json(getattr(kubernetes.client, kind), value)
    if kind in _SCALARS:
        types = _SCALARS[kind]
        wrong_bool = isinstance(value, bool) and bool not in types
        if wrong_bool or not isinstance(value, types):
            raise TypeError(f"{where or kind} must be {kind}, got {value!r}")
    return value
