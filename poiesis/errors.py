"""The root of every error Poiesis raises on purpose.

Each layer defines its own subclasses next to the code that raises them
(`poiesis.k8s`, `poiesis.db.pool`, the filers, `poiesis.api.exceptions`) and
translates what its libraries raise into them, so callers above a layer
never catch a library's exception. An error nobody handles reaches the
process's one boundary: the API's exception handlers, or the exit code and
termination message of trec, tif, tof and tctl.
"""


class PoiesisError(Exception):
    """Base class of the errors Poiesis raises on purpose."""
