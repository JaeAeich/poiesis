{{/* ----------------------------- Common Helpers ----------------------------- */}}

{{/*
Common labels used by all components
*/}}
{{- define "poiesis.labels" -}}
helm.sh/chart: {{ include "poiesis.chart" . }}
{{ include "poiesis.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels used for identifying components
*/}}
{{- define "poiesis.selectorLabels" -}}
app.kubernetes.io/name: {{ include "poiesis.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Defines the chart name and version (e.g., mychart-1.2.3)
*/}}
{{- define "poiesis.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{/*
Fully qualified name for any component (e.g., release-name-component)
*/}}
{{- define "poiesis.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end }}
{{- end }}
{{- end }}

{{/*
Service account name, conditionally uses override or fullname
*/}}
{{- define "poiesis.serviceAccountName" -}}
{{ include "poiesis.fullname" . }}-sa
{{- end }}

{{/*
Version-aware API selector for Deployments
*/}}
{{- define "poiesis.deployment.apiVersion" -}}
{{- if semverCompare ">=1.9-0" .Capabilities.KubeVersion.GitVersion -}}
apps/v1
{{- else -}}
apps/v1beta2
{{- end }}
{{- end }}

{{/*
Version-aware API selector for StatefulSets
*/}}
{{- define "poiesis.statefulset.apiVersion" -}}
{{- if semverCompare ">=1.9-0" .Capabilities.KubeVersion.GitVersion -}}
apps/v1
{{- else -}}
apps/v1beta2
{{- end }}
{{- end }}

{{/*
Version-aware API selector for RBAC
*/}}
{{- define "poiesis.rbac.apiVersion" -}}
{{- if semverCompare ">=1.17-0" .Capabilities.KubeVersion.GitVersion -}}
rbac.authorization.k8s.io/v1
{{- else -}}
rbac.authorization.k8s.io/v1beta1
{{- end }}
{{- end }}

{{/*
Namespaced RBAC rules (include Jobs - they are namespace-scoped, not cluster-scoped)
*/}}
{{- define "poiesis.rbac.namespacedRules" }}
{{- $namespacedRules := list
    (dict "apiGroups" (list "")
        "resources" (list "pods" "persistentvolumeclaims" "configmaps")
        "verbs" (list "create" "get" "list" "watch" "delete" "deletecollection" "patch"))
    (dict "apiGroups" (list "")
        "resources" (list "pods/log")
        "verbs" (list "get"))
    (dict "apiGroups" (list "batch")
        "resources" (list "jobs")
        "verbs" (list "create" "get" "list" "watch" "delete" "deletecollection"))
}}
{{ toYaml $namespacedRules | indent 2 }}
{{- end }}

{{/*
Common annotations block
*/}}
{{- define "poiesis.commonAnnotations" -}}
{{- range $key, $value := .Values.commonAnnotations }}
{{ $key }}: {{ $value | quote }}
{{- end }}
{{- end }}

{{/*
Get the app name (defaulting to chart name)
*/}}
{{- define "poiesis.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{/* ----------------------------- API Component ----------------------------- */}}

{{/*
API component name
*/}}
{{- define "poiesis.api.componentName" -}}
{{- printf "%s-api" (include "poiesis.name" .) }}
{{- end }}

{{/* ----------------------------- Auth Component -------------------------------- */}}

{{/*
Auth Secret name
*/}}
{{- define "poiesis.auth.secretName" -}}
{{- printf "%s-auth-secret" (include "poiesis.name" .) -}}
{{- end }}

{{/* ----------------------------- MongoDB Component ----------------------------- */}}

{{/*
MongoDB component name (Parent chart context)
*/}}
{{- define "poiesis.mongodb.componentName" -}}
{{- printf "%s-mongodb" (include "poiesis.name" .) -}}
{{- end }}

{{/*
MongoDB Secret name (Parent chart context)
*/}}
{{- define "poiesis.mongodb.secretName" -}}
{{- printf "%s-secret" (include "poiesis.mongodb.componentName" .) -}}
{{- end }}

{{/* ----------------------------- Redis Component ----------------------------- */}}

{{/*
Redis component name
*/}}
{{- define "poiesis.redis.componentName" -}}
{{- printf "%s-redis" (include "poiesis.name" .) }}
{{- end }}

{{/*
Redis Secret name
*/}}
{{- define "poiesis.redis.secretName" -}}
{{- printf "%s-secret" (include "poiesis.redis.componentName" .) -}}
{{- end }}


{{/* -----------------------------  S3/Minio ----------------------------- */}}

{{/*
S3 Secret name (used for MinIO or other S3-compatible backends)
*/}}
{{- define "poiesis.s3.secretName" -}}
{{- printf "%s-s3-secret" (include "poiesis.fullname" .) -}}
{{- end }}

{{/* -----------------------------  Config ----------------------------- */}}

{{/*
Core configmap name
*/}}
{{- define "poiesis.coreConfigMapName" -}}
{{- printf "%s-core-configmap" (include "poiesis.fullname" .) -}}
{{- end }}

{{/*
Security context configmap name
*/}}
{{- define "poiesis.securityConfigMapName" -}}
{{- printf "%s-security-context-configmap" (include "poiesis.fullname" .) -}}
{{- end }}
