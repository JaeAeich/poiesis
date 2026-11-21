#!/usr/bin/env bash
# Run the GA4GH TES compliance suite (TES 1.1.0) against a Poiesis at $1
# (default http://localhost:8000) and fail unless every test passes. The
# runner itself exits 0 whatever the result, so its JSON report decides.
# Needs git and uv; the suite is pinned to a commit.
set -euo pipefail

server="${1:-http://localhost:8000}"
repo=https://github.com/ga4gh/openapi-test-runner.git
rev=bc3eb911e877521409348e0225852d072d4de196
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

git -C "$work" init -q suite
git -C "$work/suite" fetch -q --depth 1 "$repo" "$rev"
git -C "$work/suite" checkout -q FETCH_HEAD
cd "$work/suite"
# Its pins (pydantic 1, jsonschema 3) need an older Python.
uv venv -q -p 3.11 .venv
uv pip install -q -p .venv/bin/python -r requirements.txt .
mkdir out
# Runs from the checkout: it reads tests/ and writes compliance_suite/web/.
.venv/bin/openapi-test-runner report --server "$server/ga4gh/tes/" --version 1.1.0 \
  --output_path out > out/run.log 2>&1 || { tail -50 out/run.log; exit 1; }

python3 - out/report.json <<'PY'
import json, sys

report = json.load(open(sys.argv[1]))
summary = report["summary"]
print("compliance suite:", summary)
for phase in report["phases"]:
    for test in phase["tests"]:
        for case in test["cases"]:
            if case["status"] != "PASS":
                print(f"  {phase['phase_name']} / {test['test_name']} / {case['case_name']}: "
                      f"{case['status']} {case.get('message', '')}")
bad = summary["failed"] + summary["unknown"] + summary["warned"] + summary["skipped"]
sys.exit(1 if bad or not summary["passed"] else 0)
PY
