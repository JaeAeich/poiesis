"""Utility functions for the API."""

from poiesis.api.tes.models import TesTask


def task_to_minimal_task(task: TesTask) -> TesTask:
    """Convert a task to a minimal task.

    Note: The TES specification says that the task should only return the id, state.
        However, the openAPI spec has the executors as required fields, so we need to
        return a minimal task.
    """
    return TesTask(
        id=task.id,
        state=task.state,
        executors=task.executors,
    )


def task_to_basic_task(task: TesTask) -> TesTask:
    """Convert a task to a basic task.

    Task message will include all fields EXCEPT:
        - tesTask.ExecutorLog.stdout
        - tesTask.ExecutorLog.stderr
        - tesInput.content
        - tesTaskLog.system_logs
    """
    if task.logs:
        for log in task.logs:
            if log.logs:
                for logs in log.logs:
                    logs.stdout = None
                    logs.stderr = None
            log.system_logs = None
    if task.inputs:
        for tes_input in task.inputs:
            tes_input.content = None

    return task
