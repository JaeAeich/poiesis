"""Poiesis API constants."""

#: Git hash of the GA4GH TES OpenAPI specification the API is derived from.
#: The shipped spec file is named ``<SPEC_GIT_HASH>.openapi.yaml`` and may
#: differ from upstream by implementor-specific but compliant edits.
SPEC_GIT_HASH = "c4c17c9"
#: TES API version implemented.
TES_VERSION = "v1.1.0"
#: URL prefix the FastAPI router is mounted under.
BASE_PATH = "ga4gh/tes/v1"
#: The default service-info ``id``, also sent to the decision service as
#: ``context.tes.service_id``; a deployment sets its own with
#: ``POIESIS_SERVICE_INFO_ID``.
SERVICE_ID = "org.ga4gh.poiesis"
