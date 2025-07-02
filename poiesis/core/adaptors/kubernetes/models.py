"""Models for the core services."""

from kubernetes.client.models.v1_capabilities import V1Capabilities
from kubernetes.client.models.v1_pod_security_context import V1PodSecurityContext
from kubernetes.client.models.v1_se_linux_options import V1SELinuxOptions
from kubernetes.client.models.v1_seccomp_profile import V1SeccompProfile
from kubernetes.client.models.v1_security_context import V1SecurityContext
from kubernetes.client.models.v1_sysctl import V1Sysctl
from kubernetes.client.models.v1_windows_security_context_options import (
    V1WindowsSecurityContextOptions,
)
from pydantic import BaseModel, Field


class V1SeccompProfilePydanticModel(BaseModel):
    """Seccomp profile."""

    localhost_profile: str | None = Field(default=None, alias="localhostProfile")
    type: str = "RuntimeDefault"

    def to_k8s_model(self) -> V1SeccompProfile:
        """Convert to Kubernetes model."""
        return V1SeccompProfile(
            localhost_profile=self.localhost_profile, type=self.type
        )


class V1SELinuxOptionsPydanticModel(BaseModel):
    """SELinux options."""

    level: str | None = None
    role: str | None = None
    type: str | None = None
    user: str | None = None

    def to_k8s_model(self) -> V1SELinuxOptions:
        """Convert to Kubernetes model."""
        return V1SELinuxOptions(
            level=self.level, role=self.role, type=self.type, user=self.user
        )


class V1SysctlPydanticModel(BaseModel):
    """Sysctl."""

    name: str
    value: str

    def to_k8s_model(self) -> V1Sysctl:
        """Convert to Kubernetes model."""
        return V1Sysctl(name=self.name, value=self.value)


class V1WindowsSecurityContextOptionsPydanticModel(BaseModel):
    """Windows security context options."""

    gmsa_credential_spec: str | None = Field(default=None, alias="gmsaCredentialSpec")
    gmsa_credential_spec_name: str | None = Field(
        default=None, alias="gmsaCredentialSpecName"
    )
    host_process: bool | None = Field(default=None, alias="hostProcess")
    run_as_user_name: str | None = Field(default=None, alias="runAsUserName")

    def to_k8s_model(self) -> V1WindowsSecurityContextOptions:
        """Convert to Kubernetes model."""
        return V1WindowsSecurityContextOptions(
            gmsa_credential_spec=self.gmsa_credential_spec,
            gmsa_credential_spec_name=self.gmsa_credential_spec_name,
            host_process=self.host_process,
            run_as_user_name=self.run_as_user_name,
        )


class V1PodSecurityContextPydanticModel(BaseModel):
    """Pod security context."""

    fs_group: int | None = Field(default=None, alias="fsGroup")
    fs_group_change_policy: str | None = Field(
        default=None, alias="fsGroupChangePolicy"
    )
    run_as_group: int | None = Field(default=None, alias="runAsGroup")
    run_as_non_root: bool | None = Field(default=None, alias="runAsNonRoot")
    run_as_user: int | None = Field(default=None, alias="runAsUser")
    se_linux_options: V1SELinuxOptionsPydanticModel | None = Field(
        default=None, alias="seLinuxOptions"
    )
    seccomp_profile: V1SeccompProfilePydanticModel | None = Field(
        default=None, alias="seccompProfile"
    )
    supplemental_groups: list[int] | None = Field(
        default=None, alias="supplementalGroups"
    )
    sysctls: list[V1SysctlPydanticModel] | None = Field(default=None)
    windows_options: V1WindowsSecurityContextOptionsPydanticModel | None = Field(
        default=None, alias="windowsOptions"
    )

    def to_k8s_model(self) -> V1PodSecurityContext:
        """Convert to Kubernetes model."""
        return V1PodSecurityContext(
            fs_group=self.fs_group,
            fs_group_change_policy=self.fs_group_change_policy,
            run_as_group=self.run_as_group,
            run_as_non_root=self.run_as_non_root,
            run_as_user=self.run_as_user,
            se_linux_options=self.se_linux_options.to_k8s_model()
            if self.se_linux_options
            else None,
            seccomp_profile=self.seccomp_profile.to_k8s_model()
            if self.seccomp_profile
            else None,
            supplemental_groups=self.supplemental_groups,
            sysctls=[sysctl.to_k8s_model() for sysctl in self.sysctls]
            if self.sysctls
            else None,
            windows_options=self.windows_options.to_k8s_model()
            if self.windows_options
            else None,
        )


class V1CapabilitiesPydanticModel(BaseModel):
    """Capabilities."""

    add: list[str] | None = Field(default=None, alias="add")
    drop: list[str] | None = Field(default=None, alias="drop")

    def to_k8s_model(self) -> V1Capabilities:
        """Convert to Kubernetes model."""
        return V1Capabilities(
            add=self.add,
            drop=self.drop,
        )


class V1SecurityContextPydanticModel(BaseModel):
    """Security context."""

    allow_privilege_escalation: bool | None = Field(
        default=None, alias="allowPrivilegeEscalation"
    )
    capabilities: V1CapabilitiesPydanticModel | None = Field(
        default=None, alias="capabilities"
    )
    privileged: bool | None = Field(default=None, alias="privileged")
    proc_mount: str | None = Field(default=None, alias="procMount")
    read_only_root_filesystem: bool | None = Field(
        default=None, alias="readOnlyRootFilesystem"
    )
    run_as_group: int | None = Field(default=None, alias="runAsGroup")
    run_as_non_root: bool | None = Field(default=None, alias="runAsNonRoot")
    run_as_user: int | None = Field(default=None, alias="runAsUser")
    se_linux_options: V1SELinuxOptionsPydanticModel | None = Field(
        default=None, alias="seLinuxOptions"
    )
    seccomp_profile: V1SeccompProfilePydanticModel | None = Field(
        default=None, alias="seccompProfile"
    )
    windows_options: V1WindowsSecurityContextOptionsPydanticModel | None = Field(
        default=None, alias="windowsOptions"
    )

    def to_k8s_model(self) -> V1SecurityContext:
        """Convert to Kubernetes model."""
        return V1SecurityContext(
            allow_privilege_escalation=self.allow_privilege_escalation,
            capabilities=self.capabilities.to_k8s_model()
            if self.capabilities
            else None,
            privileged=self.privileged,
            proc_mount=self.proc_mount,
            read_only_root_filesystem=self.read_only_root_filesystem,
            run_as_group=self.run_as_group,
            run_as_non_root=self.run_as_non_root,
            run_as_user=self.run_as_user,
            se_linux_options=self.se_linux_options.to_k8s_model()
            if self.se_linux_options
            else None,
            seccomp_profile=self.seccomp_profile.to_k8s_model()
            if self.seccomp_profile
            else None,
            windows_options=self.windows_options.to_k8s_model()
            if self.windows_options
            else None,
        )
