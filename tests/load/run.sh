#!/usr/bin/env bash
# Run tests/load/tasks.js from inside the cluster, next to the API, so the
# numbers aren't those of `kubectl port-forward`:
#   tests/load/run.sh [kube-context] [namespace]
# READ_RATE, LIST_RATE, CREATE_RATE and DURATION_SECONDS pass through to the
# script. Exits with k6's status: non-zero when a threshold fails.
set -euo pipefail

context="${1:-kind-poiesis-e2e}"
ns="${2:-poiesis}"
here="$(cd "$(dirname "$0")" && pwd)"
kc=(kubectl --context "$context" -n "$ns")

"${kc[@]}" delete pod k6 --ignore-not-found --wait >/dev/null
"${kc[@]}" create configmap k6-script --from-file="$here/tasks.js" \
  --dry-run=client -o yaml | "${kc[@]}" apply -f - >/dev/null

"${kc[@]}" apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: k6
spec:
  restartPolicy: Never
  containers:
    - name: k6
      image: grafana/k6:1.3.0
      args: ["run", "/scripts/tasks.js"]
      env:
        - {name: POIESIS_URL, value: "http://poiesis-api:8000"}
        - {name: READ_RATE, value: "${READ_RATE:-}"}
        - {name: LIST_RATE, value: "${LIST_RATE:-}"}
        - {name: CREATE_RATE, value: "${CREATE_RATE:-}"}
        - {name: DURATION_SECONDS, value: "${DURATION_SECONDS:-}"}
      volumeMounts:
        - {name: script, mountPath: /scripts}
  volumes:
    - name: script
      configMap: {name: k6-script}
YAML

# Running, then finished: the summary is at the end of its log.
"${kc[@]}" wait pod/k6 --for=condition=Ready --timeout=180s >/dev/null || true
"${kc[@]}" logs -f pod/k6
exit "$("${kc[@]}" get pod k6 \
  -o jsonpath='{.status.containerStatuses[0].state.terminated.exitCode}')"
