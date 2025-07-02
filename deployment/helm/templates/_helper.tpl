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
        "resources" (list "pods" "persistentvolumeclaims")
        "verbs" (list "create" "get" "list" "watch" "delete"))
    (dict "apiGroups" (list "")
        "resources" (list "pods/log")
        "verbs" (list "get"))
    (dict "apiGroups" (list "batch")
        "resources" (list "jobs")
        "verbs" (list "create" "get" "list" "watch" "delete"))
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

{{/*
Checks if authentication is enabled for the active MongoDB configuration.
*/}}
{{- define "poiesis.mongodb.authEnabled" -}}
{{- $externalAuthEnabled := and .Values.poiesis.externalDependencies.mongodb.enabled (default false .Values.poiesis.externalDependencies.mongodb.auth.enabled) -}}
{{- $subchartAuthEnabled := and .Values.mongodb.enabled (default false .Values.mongodb.auth.enabled) -}}
{{- or $externalAuthEnabled $subchartAuthEnabled -}}
{{- end }}

{{/*
Determines the MongoDB host for the Poiesis application.
*/}}
{{- define "poiesis.mongodb.host" -}}
{{- if .Values.poiesis.externalDependencies.mongodb.enabled -}}
{{- required (printf "MongoDB external host (.Values.poiesis.externalDependencies.mongodb.host) is required when external MongoDB is enabled, but it is currently not set or empty. Please provide a valid hostname. Current value: %q" .Values.poiesis.externalDependencies.mongodb.host) .Values.poiesis.externalDependencies.mongodb.host }}
{{- else if .Values.mongodb.enabled -}}
{{- if .Values.mongodb.fullnameOverride -}}
{{- .Values.mongodb.fullnameOverride }}
{{- else -}}
{{- $assumedSubchartAlias := "mongodb" -}}
{{- $assumedSubchartChartName := "mongodb" -}}
{{- printf "%s-%s-%s" .Release.Name $assumedSubchartAlias $assumedSubchartChartName -}}
{{- end }}
{{- else -}}
{{- fail "No MongoDB configuration is active. Please enable either external MongoDB (poiesis.externalDependencies.mongodb.enabled) or the MongoDB subchart (mongodb.enabled) in your values file." }}
{{- end }}
{{- end }}

{{/*
MongoDB port for the Poiesis application to connect to.
*/}}
{{- define "poiesis.mongodb.port" -}}
{{- if .Values.poiesis.externalDependencies.mongodb.enabled -}}
{{- required ".Values.poiesis.externalDependencies.mongodb.port is required for external MongoDB" .Values.poiesis.externalDependencies.mongodb.port | quote }}
{{- else if .Values.mongodb.enabled -}}
{{- required (printf ".Values.mongodb.service.ports.mongodb is required for subchart MongoDB. Current value: %q" (toString .Values.mongodb.service.ports.mongodb)) .Values.mongodb.service.ports.mongodb | quote }}
{{- else -}}
{{- fail "No MongoDB configuration is active. Enable external or subchart MongoDB." }}
{{- end }}
{{- end }}

{{/*
MongoDB username for the Poiesis application.
*/}}
{{- define "poiesis.mongodb.username" -}}
{{- if .Values.poiesis.externalDependencies.mongodb.enabled -}}
  {{- if .Values.poiesis.externalDependencies.mongodb.auth.enabled -}}
    {{- required ".Values.poiesis.externalDependencies.mongodb.auth.rootUser is required for external MongoDB with auth" .Values.poiesis.externalDependencies.mongodb.auth.rootUser }}
  {{- else -}}
    {{- "" -}}
  {{- end -}}
{{- else if .Values.mongodb.enabled -}}
  {{- if .Values.mongodb.auth.enabled -}}
    {{- required ".Values.mongodb.auth.rootUser is required for subchart MongoDB with auth" .Values.mongodb.auth.rootUser }}
  {{- else -}}
    {{- "" -}}
  {{- end -}}
{{- else -}}
  {{- "" -}}
{{- end }}
{{- end }}

{{/*
MongoDB password for the Poiesis application.
*/}}
{{- define "poiesis.mongodb.password" -}}
{{- if .Values.poiesis.externalDependencies.mongodb.enabled -}}
  {{- if .Values.poiesis.externalDependencies.mongodb.auth.enabled -}}
    {{- required ".Values.poiesis.externalDependencies.mongodb.auth.rootPassword is required for external MongoDB with auth" .Values.poiesis.externalDependencies.mongodb.auth.rootPassword }}
  {{- else -}}
    {{- "" -}}
  {{- end -}}
{{- else if .Values.mongodb.enabled -}}
  {{- if .Values.mongodb.auth.enabled -}}
    {{- required ".Values.mongodb.auth.rootPassword is required for subchart MongoDB with auth" .Values.mongodb.auth.rootPassword }}
  {{- else -}}
    {{- "" -}}
  {{- end -}}
{{- else -}}
  {{- "" -}}
{{- end }}
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

{{- define "poiesis.redis.fullname" -}}
{{- if .Values.redis.fullnameOverride }}
{{- .Values.redis.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-redis" .Release.Name | trunc 63 | trimSuffix "-" }} {{/* Assumes subchart alias 'redis' */}}
{{- end }}
{{- end }}

{{- define "poiesis.redis.authEnabled" -}}
{{- $externalAuthEnabled := and .Values.poiesis.externalDependencies.redis.enabled (default false .Values.poiesis.externalDependencies.redis.auth.enabled) -}}
{{- $subchartAuthEnabled := and .Values.redis.enabled (default false .Values.redis.auth.enabled) -}}
{{- or $externalAuthEnabled $subchartAuthEnabled -}}
{{- end }}

{{/*
Return the configured Redis host.
*/}}
{{- define "poiesis.redis.host" -}}
{{- if .Values.poiesis.externalDependencies.redis.enabled -}}
  {{- required ".Values.poiesis.externalDependencies.redis.host is required for external Redis" .Values.poiesis.externalDependencies.redis.host }}
{{- else if .Values.redis.enabled -}}
  {{- printf "%s-master" (include "poiesis.redis.fullname" .) -}} {{/* Bitnami Redis master service pattern */}}
{{- else -}}
  {{- fail "Redis is not configured. Enable external (poiesis.externalDependencies.redis.enabled) or subchart Redis (redis.enabled)." }}
{{- end }}
{{- end }}

{{/*
Return the configured Redis port.
*/}}
{{- define "poiesis.redis.port" -}}
{{- if .Values.poiesis.externalDependencies.redis.enabled -}}
  {{- required ".Values.poiesis.externalDependencies.redis.port is required for external Redis" .Values.poiesis.externalDependencies.redis.port | quote }}
{{- else if .Values.redis.enabled -}}
  {{- .Values.redis.service.ports.redis | default 6379 | quote }}
{{- else -}}
  {{- fail "Redis is not configured. Enable external or subchart Redis." }}
{{- end }}
{{- end }}

{{/*
Return the configured Redis password.
*/}}
{{- define "poiesis.redis.password" -}}
{{- if .Values.poiesis.externalDependencies.redis.enabled -}}
  {{- if .Values.poiesis.externalDependencies.redis.auth.enabled -}}
    {{- required ".Values.poiesis.externalDependencies.redis.auth.rootPassword is required for external Redis with auth" .Values.poiesis.externalDependencies.redis.auth.rootPassword }}
  {{- else -}}
    {{- "" -}}
  {{- end -}}
{{- else if .Values.redis.enabled -}}
  {{- if .Values.redis.auth.enabled -}}
    {{- required ".Values.redis.auth.password is required for subchart Redis with auth" .Values.redis.auth.password }}
  {{- else -}}
    {{- "" -}}
  {{- end -}}
{{- else -}}
  {{- "" -}}
{{- end }}
{{- end }}

{{/* -----------------------------  S3/Minio ----------------------------- */}}

{{/*
S3 Secret name (used for MinIO or other S3-compatible backends)
*/}}
{{- define "poiesis.s3.secretName" -}}
{{- printf "%s-s3-secret" (include "poiesis.fullname" .) -}}
{{- end }}

{{/*
Get the full name of the MinIO service
*/}}
{{- define "poiesis.minio.fullname" -}}
{{- if .Values.minio.fullnameOverride }}
{{- .Values.minio.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-minio" .Release.Name | trunc 63 | trimSuffix "-" }} {{/* Assumes subchart alias 'minio' */}}
{{- end }}
{{- end }}

{{- define "poiesis.minio.enabled" -}}
{{ or .Values.poiesis.externalDependencies.minio.enabled .Values.minio.enabled}}
{{- end }}

{{/*
Resolve the MinIO URL
*/}}
{{- define "poiesis.minio.url" -}}
{{- if .Values.poiesis.externalDependencies.minio.enabled -}}
  {{- required ".Values.poiesis.externalDependencies.minio.url is required for external MinIO" .Values.poiesis.externalDependencies.minio.url | quote }}
{{- else if .Values.minio.enabled -}}
  {{- if not .Values.minio.service.ports.api -}}
    {{- fail "MinIO subchart is enabled, but .Values.minio.service.ports.api is not defined." -}}
  {{- end -}}
  {{- printf "http://%s:%v" (include "poiesis.minio.fullname" .) .Values.minio.service.ports.api | quote }}
{{- else -}}
  {{- "" -}}
{{- end }}
{{- end }}

{{/*
Return the configured MinIO username.
*/}}
{{- define "poiesis.minio.username" -}}
{{- if .Values.poiesis.externalDependencies.minio.enabled -}}
  {{- required ".Values.poiesis.externalDependencies.minio.auth.rootUser is required for external MinIO" .Values.poiesis.externalDependencies.minio.auth.rootUser }}
{{- else if .Values.minio.enabled -}}
  {{- required ".Values.minio.auth.rootUser is required for MinIO subchart" .Values.minio.auth.rootUser }}
{{- else -}}
  {{- "" -}}
{{- end }}
{{- end }}

{{/*
Return the configured MinIO password.
*/}}
{{- define "poiesis.minio.password" -}}
{{- if .Values.poiesis.externalDependencies.minio.enabled -}}
  {{- required ".Values.poiesis.externalDependencies.minio.auth.rootPassword is required for external MinIO" .Values.poiesis.externalDependencies.minio.auth.rootPassword }}
{{- else if .Values.minio.enabled -}}
  {{- required ".Values.minio.auth.rootPassword is required for MinIO subchart" .Values.minio.auth.rootPassword }}
{{- else -}}
  {{- "" -}}
{{- end }}
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
