"""Models for TES API."""

import os
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pydantic import (
    AnyUrl,
    BaseModel,
    Field,
    field_serializer,
    field_validator,
)


class TesCancelTaskResponse(BaseModel):
    """CancelTaskResponse describes a response from the CancelTask endpoint."""

    pass


class TesCreateTaskResponse(BaseModel):
    """CreateTaskResponse describes a response from the CreateTask endpoint.

    It will include the task ID that can be used to look up the status of the job.

    Args:
        id: Task identifier assigned by the server.
            Example: "job-0012345"
    """

    id: str


class TesExecutor(BaseModel):
    """An executor is a command to be run in a container.

    Args:
        image: Name of the container image. The string will be passed as the image
            argument to the containerization run command. Examples:
            - `ubuntu`
            - `quay.io/aptible/ubuntu`
            - `gcr.io/my-org/my-image`
            - `myregistryhost:5000/fedora/httpd:version1.0`
            Example: "ubuntu:20.04"
        command: A sequence of program arguments to execute, where the first argument
            is the program to execute (i.e. argv). Example:
            ```
            {"command": ["/bin/md5", "/data/file1"]}
            ```
            Example: ["/bin/md5", "/data/file1"]
        workdir: The working directory that the command will be executed in.
            If not defined, the system will default to the directory set by
            the container image.
            Example: "/data/"
        stdin: Path inside the container to a file which will be piped
            to the executor's stdin. This must be an absolute path. This mechanism
            could be used in conjunction with the input declaration to process
            a data file using a tool that expects STDIN.

            For example, to get the MD5 sum of a file by reading it into the STDIN:
            ```
            {"command": ["/bin/md5"], "stdin": "/data/file1"}
            ```
            Example: "/data/file1"
        stdout: Path inside the container to a file where the executor's
            stdout will be written to. Must be an absolute path. Example:
            ```
            {"stdout": "/tmp/stdout.log"}
            ```
            Example: "/tmp/stdout.log"
        stderr: Path inside the container to a file where the executor's
            stderr will be written to. Must be an absolute path. Example:
            ```
            {"stderr": "/tmp/stderr.log"}
            ```
            Example: "/tmp/stderr.log"
        env: Environmental variables to set within the container. Example:
            ```
            {
                "env": {
                    "ENV_CONFIG_PATH": "/data/config.file",
                    "BLASTDB": "/data/GRC38",
                    "HMMERDB": "/data/hmmer",
                }
            }
            ```
            Example: {"BLASTDB": "/data/GRC38", "HMMERDB": "/data/hmmer"}
        ignore_error: Default behavior of running an array of executors is that
            execution stops on the first error. If `ignore_error` is `True`, then
            the runner will record error exit codes, but will continue on to the
            next tesExecutor.
    """

    image: str
    command: list[str]
    workdir: str | None = None
    stdin: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    env: dict[str, str] | None = None
    ignore_error: bool | None = None


class TesExecutorLog(BaseModel):
    """ExecutorLog describes logging information related to an Executor.

    Args:
        start_time: Time the executor started, in RFC 3339 format.
            Example: "2020-10-02T10:00:00-05:00"
        end_time: Time the executor ended, in RFC 3339 format.
            Example: "2020-10-02T11:00:00-05:00"
        stdout: Stdout content.
            This is meant for convenience. No guarantees are made about the content.
            Implementations may chose different approaches: only the head, only the
            tail, a URL reference only, etc.

            In order to capture the full stdout client should set Executor.stdout
            to a container file path, and use Task.outputs to upload that file
            to permanent storage.
        stderr: Stderr content.
            This is meant for convenience. No guarantees are made about the content.
            Implementations may chose different approaches: only the head, only the
            tail, a URL reference only, etc.

            In order to capture the full stderr client should set Executor.stderr
            to a container file path, and use Task.outputs to upload that file
            to permanent storage.
        exit_code: Exit code.
    """

    start_time: str | None = Field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S%z")
    )
    end_time: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int


class TesFileType(Enum):
    """Define if input/output element is a file or a directory.

    It is not required that the user provide this value, but it is required that
    the server fill in the value once the information is available at run time.
    """

    FILE = "FILE"
    DIRECTORY = "DIRECTORY"


class TesInput(BaseModel):
    """Input describes Task input files.

    Args:
        name: User-provided name of input file
        description: Optional users provided description field, can be used for
            documentation.
        url: REQUIRED, unless "content" is set.
            URL in long term storage, for example:
            - s3://my-object-store/file1
            - gs://my-bucket/file2
            - file:///path/to/my/file
            - /path/to/my/file
            Example: "s3://my-object-store/file1"
        path: Path of the file inside the container.
            Must be an absolute path.
            Example: "/data/file1"
            Note: The path can't be at root, needs to be nested at least once.
        type: File type (file or directory)
        content: File content literal.
            Implementations should support a minimum of 128 KiB in this field
            and may define their own maximum.
            UTF-8 encoded
            If content is not empty, "url" must be ignored.
        streamable: Indicate that a file resource could be accessed using a streaming
            interface, ie a FUSE mounted s3 object. This flag indicates that
            using a streaming mount, as opposed to downloading the whole file to
            the local scratch space, may be faster despite the latency and
            overhead. This does not mean that the backend will use a streaming
            interface, as it may not be provided by the vendor, but if the
            capacity is available it can be used without degrading the
            performance of the underlying program.
    """

    name: str | None = None
    description: str | None = None
    url: str | None = None
    path: str
    type: TesFileType | None = TesFileType.FILE
    content: str | None = None
    streamable: bool | None = None

    @field_serializer("type")
    def serialize_type(self, v: TesFileType) -> str:
        """Serialize the type to a string."""
        return v.value

    @field_validator("path")
    @classmethod
    def serialize_path(cls, path: str) -> str:
        """Serialize path so that its not at root."""
        if not path.startswith("/"):
            raise ValueError("Path must be an absolute path.")
        normalized_path = os.path.normpath(path)
        path_obj = Path(normalized_path)
        if len(path_obj.parts) < 3:  # noqa: PLR2004
            raise ValueError(
                "Path can't be at the root, it must be at least one level nested."
            )
        return normalized_path


class TesOutput(BaseModel):
    """Output describes Task output files.

    Args:
        name: User-provided name of output file
        description: Optional users provided description field, can be used for
            documentation.
        url: URL at which the TES server makes the output accessible after the task is
            complete. When tesOutput.path contains wildcards, it must be a directory;
            see `tesOutput.path_prefix` for details on how output URLs are constructed
            in this case.
            For Example:
            - `s3://my-object-store/file1`
            - `gs://my-bucket/file2`
            - `file:///path/to/my/file`
        path: Absolute path of the file inside the container.
            May contain pattern matching wildcards to select multiple outputs at once,
            but mind implications for `tesOutput.url` and `tesOutput.path_prefix`.
            Only wildcards defined in IEEE Std 1003.1-2017 (POSIX), 12.3 are supported;
            see https://pubs.opengroup.org/onlinepubs/9699919799/utilities/V3_chap02.html#tag_18_13
            Note: The path can't be at root, needs to be nested at least once.
        path_prefix: Prefix to be removed from matching outputs if `tesOutput.path`
            contains wildcards; output URLs are constructed by appending pruned paths
            to the directory specified in `tesOutput.url`.
            Required if `tesOutput.path` contains wildcards, ignored otherwise.
        type: File type (file or directory)
    """

    name: str | None = None
    description: str | None = None
    url: str
    path: str
    path_prefix: str | None = None
    type: TesFileType | None = TesFileType.FILE

    @field_serializer("type")
    def serialize_type(self, v: TesFileType) -> str:
        """Serialize the type to a string."""
        return v.value

    @field_validator("path")
    @classmethod
    def serialize_path(cls, path: str) -> str:
        """Serialize path so that its not at root."""
        if not path.startswith("/"):
            raise ValueError("Path must be an absolute path.")
        normalized_path = os.path.normpath(path)
        path_obj = Path(normalized_path)
        if len(path_obj.parts) < 3:  # noqa: PLR2004
            raise ValueError(
                "Path can't be at the root, it must be at least one level nested."
            )
        return normalized_path


class TesOutputFileLog(BaseModel):
    """OutputFileLog describes a single output file.

    This describes file details after the task has completed successfully, for logging
    purposes.

    Args:
        url: URL of the file in storage, e.g. s3://bucket/file.txt
        path: Path of the file inside the container. Must be an absolute path.
        size_bytes: Size of the file in bytes. Note, this is currently coded as a string
            because official JSON doesn't support int64 numbers.
            Example: "1024"
    """

    url: str
    path: str
    size_bytes: str


class TesResources(BaseModel):
    """Resources describes the resources requested by a task.

    Args:
        cpu_cores: Requested number of CPUs
            Example: 4
        preemptible: Define if the task is allowed to run on preemptible compute
            instances, for example, AWS Spot. This option may have no effect when
            utilized on some backends that don't have the concept of preemptible jobs.
            Example: False
        ram_gb: Requested RAM required in gigabytes (GB)
            Example: 8
        disk_gb: Requested disk size in gigabytes (GB)
            Example: 40
        zones: Request that the task be run in these compute zones. How this string
            is utilized will be dependent on the backend system. For example, a
            system based on a cluster queueing system may use this string to define
            priority queue to which the job is assigned.
            Example: "us-west-1"
        backend_parameters: Key/value pairs for backend configuration.
            ServiceInfo shall return a list of keys that a backend supports.
            Keys are case insensitive.
            It is expected that clients pass all runtime or hardware requirement
            key/values that are not mapped to existing tesResources properties to
            backend_parameters. Backends shall log system warnings if a key is passed
            that is unsupported. Backends shall not store or return unsupported keys if
            included in a task. If backend_parameters_strict equals true,
            backends should fail the task if any key/values are unsupported, otherwise,
            backends should attempt to run the task
            Intended uses include VM size selection, coprocessor configuration, etc.

    Example:
            ```
            {"backend_parameters": {"VmSize": "Standard_D64_v3"}}
            ```
            Example: {"VmSize": "Standard_D64_v3"}
        backend_parameters_strict: If set to true, backends should fail the task if any
            backend_parameters key/values are unsupported, otherwise, backends should
            attempt to run the task
            Example: False
    """

    cpu_cores: int | None = None
    preemptible: bool | None = None
    ram_gb: float | None = None
    disk_gb: float | None = None
    zones: list[str] | None = None
    backend_parameters: dict[str, str] | None = None
    backend_parameters_strict: bool | None = Field(False)


class Artifact(Enum):
    """Artifact type."""

    tes = "tes"


class ServiceType(BaseModel):
    """Type of a GA4GH service.

    Args:
        group: Namespace in reverse domain name format. Use `org.ga4gh` for
            implementations compliant with official GA4GH specifications. For services
            with custom APIs not standardized by GA4GH, or implementations diverging
            from official GA4GH specifications, use a different namespace (e.g. your
            organization's reverse domain name).
            Example: "org.ga4gh"
        artifact: Name of the API or GA4GH specification implemented. Official GA4GH
            types should be assigned as part of standards approval process. Custom
            artifacts are supported.
            Example: "beacon"
        version: Version of the API or specification. GA4GH specifications use
            semantic versioning.
            Example: "1.0.0"
    """

    group: str
    artifact: str
    version: str


class Organization(BaseModel):
    """Organization responsible for a GA4GH service.

    Args:
        name: Name of the organization responsible for the service
            Example: "My organization"
        url: URL of the website of the organization (RFC 3986 format)
            Example: "https://example.com"
    """

    name: str
    url: AnyUrl

    @field_serializer("url")
    def serialize_url(self, v: AnyUrl) -> str:
        """Serialize the URL to a string."""
        return str(v)


class Service(BaseModel):
    """GA4GH service.

    Args:
        id: Unique ID of this service. Reverse domain name notation is recommended,
            though not required. The identifier should attempt to be globally unique
            so it can be used in downstream aggregator services e.g. Service Registry.
            Example: "org.ga4gh.myservice"
        name: Name of this service. Should be human readable.
            Example: "My project"
        type: Type of service
        description: Description of the service. Should be human readable and provide
            information about the service.
            Example: "This service provides..."
        organization: Organization providing the service
        contactUrl: URL of the contact for the provider of this service, e.g. a link
            to a contact form (RFC 3986 format), or an email (RFC 2368 format).
            Example: "mailto:support@example.com"
        documentationUrl: URL of the documentation of this service (RFC 3986 format).
            This should help someone learn how to use your service, including any
            specifics required to access data, e.g. authentication.
            Example: "https://docs.myservice.example.com"
        createdAt: Timestamp describing when the service was first deployed and
            available (RFC 3339 format)
            Example: "2019-06-04T12:58:19Z"
        updatedAt: Timestamp describing when the service was last updated (RFC 3339
            format)
            Example: "2019-06-04T12:58:19Z"
        environment: Environment the service is running in. Use this to distinguish
            between production, development and testing/staging deployments. Suggested
            values are prod, test, dev, staging. However this is advised and not
            enforced.
            Example: "test"
        version: Version of the service being described. Semantic versioning is
            recommended, but other identifiers, such as dates or commit hashes, are
            also allowed. The version should be changed whenever the service is updated.
            Example: "1.0.0"
    """

    id: str
    name: str
    type: ServiceType
    description: str | None = None
    organization: Organization
    contactUrl: str | None = None
    documentationUrl: AnyUrl | None = None
    createdAt: datetime | None = Field(default_factory=lambda: datetime.now(UTC))
    updatedAt: datetime | None = Field(default_factory=lambda: datetime.now(UTC))
    environment: str | None = None
    version: str

    @field_serializer("documentationUrl")
    def serialize_documentationUrl(self, v: AnyUrl) -> str:
        """Serialize the documentation URL to a string."""
        return str(v)


class TesState(Enum):
    """Task state."""

    UNKNOWN = "UNKNOWN"
    QUEUED = "QUEUED"
    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETE = "COMPLETE"
    EXECUTOR_ERROR = "EXECUTOR_ERROR"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    CANCELED = "CANCELED"
    PREEMPTED = "PREEMPTED"
    CANCELING = "CANCELING"


class TesTaskLog(BaseModel):
    """TaskLog describes logging information related to a Task.

    Args:
        logs: Logs for each executor
        metadata: Arbitrary logging metadata included by the implementation.
            Example: {"host": "worker-001", "slurmm_id": 123456}
        start_time: When the task started, in RFC 3339 format.
            Example: "2020-10-02T10:00:00-05:00"
        end_time: When the task ended, in RFC 3339 format.
            Example: "2020-10-02T11:00:00-05:00"
        outputs: Information about all output files. Directory outputs are
            flattened into separate items.
        system_logs: System logs are any logs the system decides are relevant,
            which are not tied directly to an Executor process.
            Content is implementation specific: format, size, etc.

            System logs may be collected here to provide convenient access.

            For example, the system may include the name of the host
            where the task is executing, an error message that caused
            a SYSTEM_ERROR state (e.g. disk is full), etc.

            System logs are only included in the FULL task view.
    """

    logs: list[TesExecutorLog]
    metadata: dict[str, str] | None = None
    start_time: str | None = Field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S%z")
    )
    end_time: str | None = None
    outputs: list[TesOutputFileLog]
    system_logs: list[str] | None = None


class TesServiceType(ServiceType):
    """Type of a TES service."""

    artifact: Artifact  # type: ignore

    @field_serializer("artifact")
    def serialize_artifact(self, v: Artifact) -> str:
        """Serialize the artifact to a string."""
        return v.value


class TesServiceInfo(Service):
    """ServiceInfo describes the service that is running the TES API.

    Args:
        storage: lists some, but not necessarily all, storage locations supported
            by the service.
            Example: [
                "file:///path/to/local/funnel-storage",
                "s3://ohsu-compbio-funnel/storage",
            ]
        tesResources_backend_parameters: lists all tesResources.backend_parameters keys
            supported by the service
            Example: ["VmSize"]
        type: Type of service
    """

    storage: list[str] | None = None
    tesResources_backend_parameters: list[str] | None = None
    type: TesServiceType | None = None  # type: ignore


class TesTask(BaseModel):
    """Task describes a task to be run.

    Args:
        id: Task identifier assigned by the server.
            Example: "job-0012345"
        state: Task state
        name: User-provided task name.
        description: Optional user-provided description of task for documentation
            purposes.
        inputs: Input files that will be used by the task. Inputs will be downloaded
            and mounted into the executor container as defined by the task request
            document.
            Example: [{"url": "s3://my-object-store/file1", "path": "/data/file1"}]
        outputs: Output files.
            Outputs will be uploaded from the executor container to long-term storage.
            Example: [
                {
                    "path": "/data/outfile",
                    "url": "s3://my-object-store/outfile-1",
                    "type": "FILE",
                }
            ]
        resources: Resources requested by the task
        executors: An array of executors to be run. Each of the executors will run one
            at a time sequentially. Each executor is a different command that
            will be run, and each can utilize a different docker image. But each of
            the executors will see the same mapped inputs and volumes that are declared
            in the parent CreateTask message.

            Execution stops on the first error.
        volumes: Volumes are directories which may be used to share data between
            Executors. Volumes are initialized as empty directories by the
            system when the task starts and are mounted at the same path
            in each Executor.

            For example, given a volume defined at `/vol/A`,
            executor 1 may write a file to `/vol/A/exec1.out.txt`, then
            executor 2 may read from that file.

            (Essentially,this translates to a `docker run -v` flag where
            the container path is the same for each executor).
            Example: ["/vol/A/"]
        tags: A key-value map of arbitrary tags. These can be used to store
            meta-data and annotations about a task. Example:
            ```
            {"tags": {"WORKFLOW_ID": "cwl-01234", "PROJECT_GROUP": "alice-lab"}}
            ```
            Example: {"WORKFLOW_ID": "cwl-01234", "PROJECT_GROUP": "alice-lab"}
        logs: Task logging information.
            Normally, this will contain only one entry, but in the case where
            a task fails and is retried, an entry will be appended to this list.
        creation_time: Date + time the task was created, in RFC 3339 format.
            This is set by the system, not the client.
            Example: "2020-10-02T10:00:00-05:00"
    """

    id: str | None = None
    state: TesState | None = TesState.UNKNOWN
    name: str | None = None
    description: str | None = None
    inputs: list[TesInput] | None = None
    outputs: list[TesOutput] | None = None
    resources: TesResources | None = None
    executors: list[TesExecutor]
    volumes: list[str] | None = None
    tags: dict[str, str] | None = None
    logs: list[TesTaskLog] | None = None
    creation_time: str | None = Field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S%z"),
        frozen=True,
    )

    @field_serializer("state")
    def serialize_state(self, v: TesState) -> str:
        """Serialize the state to a string."""
        return v.value


class TesListTasksResponse(BaseModel):
    """listTasksResponse describes a response from the listTasks endpoint.

    Args:
        tasks: list of tasks. These tasks will be based on the original submitted
            task document, but with other fields, such as the job state and
            logging info, added/changed as the job progresses.
        next_page_token: Token used to return the next page of results. This value can
            be used in the `page_token` field of the next listTasks request.
    """

    tasks: list[TesTask]
    next_page_token: str | None = None
