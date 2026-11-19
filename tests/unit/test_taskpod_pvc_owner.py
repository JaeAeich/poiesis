"""The task PVC's ownerReference must not block the Job's deletion.

With ``blockOwnerDeletion: true``, clusters that enforce owner-reference
permissions (e.g. OpenShift) require ``update`` on ``jobs/finalizers`` to
create the PVC, which namespace admins can't grant.
"""

from __future__ import annotations

import pytest
from kubernetes.client import V1ObjectMeta, V1PersistentVolumeClaim

from poiesis.core.taskpod import attach_pvc_owner


@pytest.mark.parametrize(
    "metadata", [V1ObjectMeta(name="task-pvc"), None], ids=["metadata", "no-metadata"]
)
def test_pvc_is_owned_by_its_job(metadata: V1ObjectMeta | None) -> None:
    """The Job is the PVC's controlling owner, with or without metadata."""
    pvc = V1PersistentVolumeClaim(metadata=metadata)

    attach_pvc_owner(pvc, job_uid="uid-1", job_name="job-1")

    assert pvc.metadata is not None
    (ref,) = pvc.metadata.owner_references
    assert (ref.api_version, ref.kind, ref.name, ref.uid, ref.controller) == (
        "batch/v1",
        "Job",
        "job-1",
        "uid-1",
        True,
    )


def test_pvc_owner_reference_does_not_block_owner_deletion() -> None:
    """The ownerReference doesn't set blockOwnerDeletion."""
    pvc = V1PersistentVolumeClaim(metadata=V1ObjectMeta(name="task-pvc"))

    attach_pvc_owner(pvc, job_uid="uid-1", job_name="job-1")

    assert pvc.metadata is not None
    (ref,) = pvc.metadata.owner_references
    assert ref.block_owner_deletion is False
