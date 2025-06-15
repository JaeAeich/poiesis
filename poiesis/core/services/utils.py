"""Utility functions."""

import os
from pathlib import Path


def split_path_for_mounting(path_str: str) -> tuple[str, str]:
    """Splits an absolute POSIX path into its first component and the rest.

    This function aids in preparing paths for a specific PVC mounting strategy used
    between a Filer pod and an Executor pod. The goal is to make data available at
    a precise `target_path` within the Executor pod using a shared PVC.

    Context & Mechanism:
    1.  **Goal:** Make data available at a specific `target_path` inside the Executor
        pod (e.g., `/data/f1/f2/file1`).
    2.  **Shared Storage:** A Persistent Volume Claim (PVC) is shared between the
        Filer and Executor pods.
    3.  **Path Splitting:** The `target_path` is split by this function into:
            - `first_component`: The initial directory (e.g., `/data`).
            - `rest_of_path`: The remainder of the path relative to the first
            component (e.g., `f1/f2/file1`).
    4.  **Filer Pod's Role:**
            - Mounts the PVC (e.g., at `/transfer`).
            - Downloads or generates the required data.
            - Places this data *inside its PVC mount point* at the location specified
                by `rest_of_path`. (e.g., writes to `/transfer/f1/f2/file1`).
            - This results in the data being stored within the PVC storage at the
                relative path `<pvc-root>/f1/f2/file1`.
    5.  **Executor Pod's Role:**
            - Mounts the second component of the path (e.g., `/data`) of the
                PVC storage.
            - Uses the `first_component` (e.g., `/data`) as the
                `volumeMounts.mountPath`.
    6.  **Result:** Using the PVC (which contains the data at the relative path
        `<pvc-root>/f1/f2/file1`) is mounted at `/data` in the Executor, the data
        becomes automatically accessible at the combined path `/data/f1/f2/file1`,
        matching the original `target_path`.

    Args:
        path_str (str): The absolute path string (e.g., '/data/f1/f2/file1').

    Returns:
        tuple[str, str]: A tuple containing (`first_component`, `rest_of_path`),
            e.g., ('/data', 'f1/f2/file1') for the path `/data/f1/f2/file1`.
            Returns ('/', '') for the root path '/'.
            Returns (path_str, '') if there's only one component (e.g., '/data').

    Raises:
        ValueError: If the path_str is None, or not nested at least once.
    """
    if not path_str:
        raise ValueError("Path is empty.")

    p = Path(path_str)

    path_parts = p.parts

    if len(path_parts) <= 2:  # noqa: PLR2004
        raise ValueError("Path needs to be nested at least once.")

    first_part = Path(p.anchor) / path_parts[1]
    rest_parts = path_parts[2:]
    rest_of_path = os.path.join(*rest_parts) if rest_parts else ""
    return str(first_part), rest_of_path
