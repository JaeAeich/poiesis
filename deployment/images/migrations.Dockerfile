# syntax=docker/dockerfile:1.7
#
# Migrations image: the golang-migrate binary plus the bundled SQL files.
# Used by the pre-install / pre-upgrade hook Job in the Helm chart, and by
# the dev.yaml migration Job. Decoupled from the runtime image so:
#   - the runtime image carries no Go binary it never uses,
#   - migrations can roll out (or back) without rebuilding the API/TCtl image,
#   - the hook Job pulls a ~25 MB image instead of the full runtime.

FROM migrate/migrate:v4.19.1

COPY migrations /migrations

USER 65532:65532

ENTRYPOINT ["migrate", "-path", "/migrations"]
