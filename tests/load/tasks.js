// Load test of the TES API: k6 run tests/load/tasks.js
//
// Against a deployment with auth off (tests/e2e/setup.sh), port-forwarded:
//   kubectl -n poiesis port-forward svc/poiesis-api 8000:8000 &
//   POIESIS_URL=http://localhost:8000 k6 run tests/load/tasks.js
//
// Three scenarios run one after another, so their latencies don't mix:
//   reads   service-info and GetTask at READ_RATE requests a second,
//   lists   ListTasks (BASIC view, 50 a page) at LIST_RATE,
//   creates CreateTask at CREATE_RATE; each one makes a Job and a PVC, so
//           keep it small on a laptop cluster.
import http from "k6/http";
import { check } from "k6";

const base = `${__ENV.POIESIS_URL || "http://localhost:8000"}/ga4gh/tes/v1`;
const duration = __ENV.DURATION || "30s";
const rate = (name, fallback) => Number(__ENV[name] || fallback);

const scenario = (exec, perSecond, startAfter) => ({
  executor: "constant-arrival-rate",
  exec,
  rate: perSecond,
  timeUnit: "1s",
  duration,
  startTime: `${startAfter * (parseInt(duration) + 5)}s`,
  preAllocatedVUs: 50,
  maxVUs: 400,
});

export const options = {
  scenarios: {
    reads: scenario("reads", rate("READ_RATE", 200), 0),
    lists: scenario("lists", rate("LIST_RATE", 50), 1),
    creates: scenario("creates", rate("CREATE_RATE", 5), 2),
  },
  summaryTrendStats: ["med", "p(95)", "p(99)", "max"],
  thresholds: {
    // Named so the summary reports each scenario apart.
    "http_req_duration{scenario:reads}": ["p(99)<1000"],
    "http_req_duration{scenario:lists}": ["p(99)<2000"],
    "http_req_duration{scenario:creates}": ["p(99)<5000"],
    "http_req_failed{scenario:reads}": ["rate<0.01"],
    "http_req_failed{scenario:lists}": ["rate<0.01"],
    "http_req_failed{scenario:creates}": ["rate<0.01"],
  },
};

const task = JSON.stringify({
  name: "load-test",
  executors: [{ image: "busybox:1.36", command: ["true"] }],
  tags: { source: "k6" },
});
const json = { headers: { "Content-Type": "application/json" } };

export function setup() {
  const created = http.post(`${base}/tasks`, task, json);
  check(created, { "setup task created": (r) => r.status === 200 });
  return { id: created.json("id") };
}

export function reads(data) {
  check(http.get(`${base}/service-info`), { "service-info 200": (r) => r.status === 200 });
  check(http.get(`${base}/tasks/${data.id}?view=FULL`), {
    "get task 200": (r) => r.status === 200,
  });
}

export function lists() {
  check(http.get(`${base}/tasks?view=BASIC&page_size=50`), {
    "list tasks 200": (r) => r.status === 200,
  });
}

export function creates() {
  check(http.post(`${base}/tasks`, task, json), {
    "create task 200": (r) => r.status === 200,
  });
}
