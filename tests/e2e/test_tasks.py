"""Tasks through the TES API on a real cluster: final states, logs, staging."""

import time
import uuid

import pytest
from e2e import IMAGE, Tes, kubectl, s3_get, s3_put


def executor(*command: str, **extra: object) -> dict[str, object]:
    """A busybox executor running ``command``."""
    return {"image": IMAGE, "command": list(command), **extra}


def test_success_records_stdout(tes: Tes) -> None:
    """A task that exits 0 is COMPLETE with the executor's stdout."""
    task = tes.run({"executors": [executor("echo", "hello e2e")]})

    assert task["state"] == "COMPLETE"
    log = task["logs"][-1]["logs"][0]
    assert log["exit_code"] == 0
    assert "hello e2e" in log["stdout"]


def test_failing_executor_records_exit_code(tes: Tes) -> None:
    """A non-zero exit is EXECUTOR_ERROR with that exit code.

    The container log mixes both streams into ``stdout`` (see the task
    logs section of concepts/tasks.md).
    """
    task = tes.run({"executors": [executor("sh", "-c", "echo oops >&2; exit 3")]})

    assert task["state"] == "EXECUTOR_ERROR"
    log = task["logs"][-1]["logs"][0]
    assert log["exit_code"] == 3
    assert "oops" in log["stdout"]


def test_cancel_running_task_deletes_job(tes: Tes) -> None:
    """Cancelling a RUNNING task ends it CANCELED and removes its Job."""
    task_id = tes.create({"executors": [executor("sleep", "300")]})
    tes.wait(task_id, {"RUNNING"})

    tes.cancel(task_id)
    task = tes.wait(task_id, {"CANCELED"}, timeout=60)

    assert task["state"] == "CANCELED"
    deadline = time.monotonic() + 60
    while (job := kubectl("get", "job", f"task-{task_id}")).returncode == 0:
        assert time.monotonic() < deadline, f"Job still there: {job.stdout}"
        time.sleep(1)
    assert "NotFound" in job.stderr


@pytest.mark.slow
def test_missing_image_is_system_error(tes: Tes) -> None:
    """An image that can't be pulled ends SYSTEM_ERROR at the pending timeout.

    The Pod sits Pending in ImagePullBackOff until TCtl's 5-minute
    pending timeout, so this is kept out of the default run.
    """
    image = f"docker.io/library/poiesis-e2e-missing:{uuid.uuid4().hex[:8]}"
    task = tes.run({"executors": [{"image": image, "command": ["true"]}]}, timeout=420)

    assert task["state"] == "SYSTEM_ERROR"
    system_logs = " ".join(task["logs"][-1].get("system_logs") or [])
    assert "pending timeout" in system_logs


def test_content_input_reaches_executor(tes: Tes) -> None:
    """An inline ``content`` input is a file the executor can read."""
    task = tes.run(
        {
            "inputs": [{"path": "/data/in.txt", "content": "inline content"}],
            "executors": [executor("cat", "/data/in.txt")],
        }
    )

    assert task["state"] == "COMPLETE"
    assert task["logs"][-1]["logs"][0]["stdout"] == "inline content"


def s3_round_trip(tes: Tes) -> tuple[dict[str, object], str, str]:
    """Run a task that upper-cases an s3:// input into an s3:// output."""
    prefix = f"round-trip/{uuid.uuid4().hex}"
    url_in = s3_put(f"{prefix}/in.txt", "from s3\n")
    url_out = url_in.replace("in.txt", "out.txt")
    task = tes.run(
        {
            "inputs": [{"url": url_in, "path": "/data/in.txt"}],
            "outputs": [{"url": url_out, "path": "/data/out.txt"}],
            "executors": [
                executor("sh", "-c", "tr a-z A-Z < /data/in.txt > /data/out.txt")
            ],
        }
    )
    return task, prefix, url_out


def test_s3_input_and_output_round_trip(tes: Tes) -> None:
    """An s3:// input is staged in and an s3:// output is uploaded."""
    task, prefix, _ = s3_round_trip(tes)

    assert task["state"] == "COMPLETE", task["logs"][-1].get("system_logs")
    assert s3_get(f"{prefix}/out.txt") == "FROM S3\n"


def test_output_log_lists_uploaded_files(tes: Tes) -> None:
    """The task log lists each uploaded output (TES OutputFileLog)."""
    task, _, url_out = s3_round_trip(tes)

    outputs = task["logs"][-1]["outputs"]
    assert [o["url"] for o in outputs] == [url_out]
    assert [(o["path"], o["size_bytes"]) for o in outputs] == [("/data/out.txt", "8")]


def test_list_paginates_and_filters_by_tag(tes: Tes) -> None:
    """A tag filter selects this run's tasks; page_size and the token page."""
    run = uuid.uuid4().hex
    created = {
        tes.create({"tags": {"e2e-run": run}, "executors": [executor("true")]})
        for _ in range(3)
    }
    tes.create({"tags": {"e2e-run": "other"}, "executors": [executor("true")]})

    first = tes.list(tag_key="e2e-run", tag_value=run, page_size=2)
    assert len(first["tasks"]) == 2
    assert first.get("next_page_token")
    second = tes.list(
        tag_key="e2e-run",
        tag_value=run,
        page_size=2,
        page_token=first["next_page_token"],
    )
    assert len(second["tasks"]) == 1
    assert not second.get("next_page_token")

    listed = {t["id"] for t in first["tasks"] + second["tasks"]}
    assert listed == created


def test_file_url_input_refused(tes: Tes) -> None:
    """``file://`` is off by default: such a task is refused with 400."""
    response = tes.http.post(
        "/tasks",
        json={
            "inputs": [{"url": "file:///etc/hostname", "path": "/data/in.txt"}],
            "executors": [executor("cat", "/data/in.txt")],
        },
    )

    assert response.status_code == 400, response.text
