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
{{- end -}}

{{/*
Selector labels used for identifying components
*/}}
{{- define "poiesis.selectorLabels" -}}
app.kubernetes.io/name: {{ include "poiesis.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Defines the chart name and version (e.g., mychart-1.2.3)
*/}}
{{- define "poiesis.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

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
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Service account name, conditionally uses override or fullname
*/}}
{{- define "poiesis.serviceAccountName" -}}
	{{ include "poiesis.fullname" . }}-sa
{{- end -}}

{{/*
Version-aware API selector for Deployments
*/}}
{{- define "poiesis.deployment.apiVersion" -}}
{{- if semverCompare ">=1.9-0" .Capabilities.KubeVersion.GitVersion -}}
apps/v1
{{- else -}}
apps/v1beta2
{{- end -}}
{{- end -}}

{{/*
Version-aware API selector for StatefulSets
*/}}
{{- define "poiesis.statefulset.apiVersion" -}}
{{- if semverCompare ">=1.9-0" .Capabilities.KubeVersion.GitVersion -}}
apps/v1
{{- else -}}
apps/v1beta2
{{- end -}}
{{- end -}}

{{/*
Version-aware API selector for RBAC
*/}}
{{- define "poiesis.rbac.apiVersion" -}}
{{- if semverCompare ">=1.17-0" .Capabilities.KubeVersion.GitVersion -}}
rbac.authorization.k8s.io/v1
{{- else -}}
rbac.authorization.k8s.io/v1beta1
{{- end -}}
{{- end -}}

{{/*
Default RBAC rules
*/}}
{{- define "poiesis.rbac.rules" }}
- apiGroups: [""]
  resources: ["pods", "persistentvolumeclaims"]
  verbs: ["create", "get", "list", "watch", "delete"]
- apiGroups: [""]
  resources: ["pods/log"]
  verbs: ["get"]
- apiGroups: ["batch"]
  resources: ["jobs"]
  verbs: ["create", "get", "list", "watch", "delete"]
{{- end }}

{{/*
Common annotations block
*/}}
{{- define "poiesis.commonAnnotations" -}}
{{- range $key, $value := .Values.commonAnnotations }}
{{ $key }}: {{ $value | quote }}
{{- end }}
{{- end -}}

{{/*
Get the app name (defaulting to chart name)
*/}}
{{- define "poiesis.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* ----------------------------- API Component ----------------------------- */}}

{{/*
API component name
*/}}
{{- define "poiesis.api.componentName" -}}
{{- printf "%s-api" (include "poiesis.name" .) }}
{{- end -}}

{{/* ----------------------------- MongoDB Component ----------------------------- */}}

{{/*
MongoDB component name
*/}}
{{- define "poiesis.mongo.componentName" -}}
{{- printf "%s-mongo" (include "poiesis.name" .) }}
{{- end -}}

{{/*
MongoDB Secret name
*/}}
{{- define "poiesis.mongo.secretName" -}}
{{- printf "%s-secret" (include "poiesis.mongo.componentName" .) -}}
{{- end -}}

{{/*
MongoDB Persistent Volume Claim name
*/}}
{{- define "poiesis.customMongo.pvcName" -}}
{{- printf "%s-pvc" (include "poiesis.mongo.componentName" .) -}}
{{- end -}}

{{/*
MongoDB username
*/}}
{{- define "poiesis.mongo.username" -}}
  {{- if .Values.poiesis.externalDependencies.mongodb.enabled -}}
    {{ required "MongoDB external username (.Values.poiesis.externalDependencies.mongodb.username) or rootPassword (.Values.poiesis.externalDependencies.mongodb.rootPassword) is required when external MongoDB is enabled" .Values.poiesis.externalDependencies.mongodb.username }}
  {{- else if .Values.customMongo.enabled -}}
    {{ required "MongoDB custom username (.Values.customMongo.auth.rootUser) is required when custom MongoDB is enabled" .Values.customMongo.auth.rootUser }}
  {{- else -}}
    {{ required "MongoDB subchart/default username (.Values.mongodb.auth.rootUser) is required when neither external nor custom MongoDB is enabled" .Values.mongodb.auth.rootUser }}
  {{- end -}}
{{- end -}}

{{/*
MongoDB password
*/}}
{{- define "poiesis.mongo.password" -}}
  {{- if .Values.poiesis.externalDependencies.mongodb.enabled -}}
    {{ required "MongoDB external password (.Values.poiesis.externalDependencies.mongodb.password) is required when external MongoDB is enabled" .Values.poiesis.externalDependencies.mongodb.password }}
  {{- else if .Values.customMongo.enabled -}}
    {{ required "MongoDB custom password (.Values.customMongo.auth.rootPassword) is required when custom MongoDB is enabled" .Values.customMongo.auth.rootPassword }}
  {{- else -}}
    {{ required "MongoDB subchart/default password (.Values.mongodb.auth.rootPassword) is required when neither external nor custom MongoDB is enabled" .Values.mongodb.auth.rootPassword }}
  {{- end -}}
{{- end -}}
{{/* ----------------------------- Redis Component ----------------------------- */}}

{{/*
Redis component name
*/}}
{{- define "poiesis.redis.componentName" -}}
{{- printf "%s-redis" (include "poiesis.name" .) }}
{{- end -}}

{{/*
Redis Secret name
*/}}
{{- define "poiesis.redis.secretName" -}}
{{- printf "%s-secret" (include "poiesis.redis.componentName" .) -}}
{{- end -}}

{{- define "poiesis.redis.fullname" -}}
{{- if .Values.redis.fullnameOverride }}
{{- .Values.redis.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-redis" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Return the configured Redis host.
Checks poiesis.externalDependencies.redis.host first, then the Bitnami subchart redis.
Fails if neither host is found and one of them is enabled, with a specific error.
*/}}
{{- define "poiesis.redis.host" -}}
  {{- $externalRedisEnabled := .Values.poiesis.externalDependencies.redis.enabled -}}
  {{- $externalRedisHost := .Values.poiesis.externalDependencies.redis.host -}}
  {{- $subchartRedisEnabled := .Values.redis.enabled -}}
  {{- $subchartRedisHost := printf "%s-master" (include "poiesis.redis.fullname" .) -}}

  {{- if and $externalRedisEnabled (not $externalRedisHost) -}}
    {{- fail (printf "\n[poiesis.redis.host] External Redis (poiesis.externalDependencies.redis) is enabled but 'poiesis.externalDependencies.redis.host' is missing or empty.") -}}
  {{- else if and $externalRedisEnabled $externalRedisHost -}}
    {{- $externalRedisHost -}}
  {{- else if $subchartRedisEnabled -}}
    {{- $subchartRedisHost -}}
  {{- else -}}
    {{- fail (printf "\n[poiesis.redis.host] You forgot to set host for Redis.\n- If using a custom Redis under 'poiesis.externalDependencies.redis', ensure 'poiesis.externalDependencies.redis.enabled' is true and set:\n  poiesis.externalDependencies.redis.host: <your-host>\n- If using the Bitnami subchart 'redis', ensure 'redis.enabled' is true.") -}}
  {{- end -}}
{{- end -}}

{{/*
Return the configured Redis port.
Checks poiesis.externalDependencies.redis.port first, then defaults to .Values.redis.service.ports.redis or 6379.
*/}}
{{- define "poiesis.redis.port" -}}
  {{- $externalRedisEnabled := .Values.poiesis.externalDependencies.redis.enabled -}}
  {{- $externalRedisPort := .Values.poiesis.externalDependencies.redis.port -}}
  {{- $subchartRedisEnabled := .Values.redis.enabled -}}
  {{- $subchartRedisPort := .Values.redis.service.ports.redis | default 6379 -}}

  {{- if and $externalRedisEnabled (not $externalRedisPort) -}}
    {{- fail (printf "\n[poiesis.redis.port] External Redis (poiesis.externalDependencies.redis) is enabled but 'poiesis.externalDependencies.redis.port' is missing or empty.") -}}
  {{- else if and $externalRedisEnabled $externalRedisPort -}}
    {{- $externalRedisPort -}}
  {{- else if $subchartRedisEnabled -}}
    {{- quote $subchartRedisPort -}}
  {{- else -}}
    {{- fail (printf "\n[poiesis.redis.port] You forgot to set port for Redis.\n- If using a custom Redis under 'poiesis.externalDependencies.redis', ensure 'poiesis.externalDependencies.redis.enabled' is true and set:\n  poiesis.externalDependencies.redis.port: <your-port>\n- If using the Bitnami subchart 'redis', ensure 'redis.enabled' is true.") -}}
  {{- end -}}
{{- end -}}


{{/*
Return the configured Redis password.
If using external Redis (dependency.redis), skip setting password if present.
Else use Bitnami redis.auth.password.
*/}}
{{- define "poiesis.redis.password" -}}
  {{- $externalRedisEnabled := .Values.poiesis.externalDependencies.redis.enabled -}}
  {{- $externalRedisPassword := .Values.poiesis.externalDependencies.redis.rootPassword -}}
  {{- $subchartRedisEnabled := .Values.redis.enabled -}}
  {{- $subchartRedisAuthEnabled := .Values.redis.auth.enabled -}}
  {{- $subchartRedisPassword := .Values.redis.auth.password -}}

  {{- if and $externalRedisEnabled $externalRedisPassword -}}
    {{- $externalRedisPassword -}}
    {{- "" -}}
  {{- else if and $subchartRedisEnabled $subchartRedisAuthEnabled $subchartRedisPassword -}}
    {{- $subchartRedisPassword -}}
  {{- else -}}
    {{- fail (printf "\n[poiesis.redis.password] No usable Redis password was found.\n- If using external Redis, make sure:\n  poiesis.externalDependencies.redis.enabled: true\n  poiesis.externalDependencies.redis.rootPassword: <your-password>\n- If using Bitnami Redis, make sure:\n  redis.enabled: true\n  redis.auth.enabled: true\n  redis.auth.password: <your-password>") -}}
  {{- end -}}
{{- end -}}


{{/* ----------------------------- Keycloak Component ----------------------------- */}}

{{/*
Keycloak component name
*/}}
{{- define "poiesis.keycloak.componentName" -}}
{{- printf "%s-keycloak" (include "poiesis.name" .) }}
{{- end -}}

{{/*
Keycloak Secret name
*/}}
{{- define "poiesis.keycloak.secretName" -}}
{{- printf "%s-secret" (include "poiesis.keycloak.componentName" .) -}}
{{- end -}}

{{- define "poiesis.keycloak.fullname" -}}
{{- if .Values.keycloak.fullnameOverride }}
{{- .Values.keycloak.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-keycloak" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "poiesis.keycloak.url" -}}
  {{- $externalEnabled := .Values.poiesis.externalDependencies.keycloak.enabled -}}
  {{- $externalURL := .Values.poiesis.externalDependencies.keycloak.url -}}
  {{- $subchartEnabled := .Values.keycloak.enabled -}}
  {{- $subchartPort := .Values.keycloak.service.port | default 80 -}}
  {{- $authType := .Values.poiesis.auth.type | lower -}}

  {{- if and (not $externalEnabled) (not $subchartEnabled) (ne $authType "dummy") -}}
    {{- fail (printf "\n[poiesis.keycloak.url] Authentication type is '%s' but neither external nor internal Keycloak is enabled.\nTo fix:\n- Enable external Keycloak via 'poiesis.externalDependencies.keycloak.enabled: true'\n  and provide 'url', 'clientId', etc.\n- OR enable Bitnami Keycloak via 'keycloak.enabled: true'" $authType) -}}
  {{- else if and $externalEnabled $externalURL -}}
    {{- $externalURL | quote -}}
  {{- else if $subchartEnabled -}}
    {{- $svc := include "poiesis.keycloak.fullname" . -}}
    {{- printf "http://%s:%d" $svc $subchartPort | quote -}}
  {{- else -}}
    {{- "" -}} {{/* dummy auth type or both disabled */}}
  {{- end -}}
{{- end }}

{{- define "poiesis.keycloak.clientSecret" -}}
  {{- default "changeme" .Values.poiesis.config.keycloakClientSecret | quote -}}
{{- end }}

{{/* -----------------------------  S3/Minio ----------------------------- */}}

{{/*
S3 Secret name (used for MinIO or other S3-compatible backends)
*/}}
{{- define "poiesis.s3.secretName" -}}
{{- printf "%s-s3-secret" (include "poiesis.fullname" .) -}}
{{- end -}}

{{/*
Get the full name of the MinIO service
*/}}
{{- define "poiesis.minio.fullname" -}}
{{- if .Values.minio.fullnameOverride }}
{{- .Values.minio.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-minio" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}


{{/*
Resolve the MinIO URL:
- If external MinIO is configured via poiesis.externalDependencies.minio.enabled, use that URL.
- Otherwise, fallback to the MinIO service deployed via subchart.
*/}}
{{- define "poiesis.minio.url" -}}
  {{- $externalMinioEnabled := .Values.poiesis.externalDependencies.minio.enabled -}}
  {{- $externalMinioUrl := .Values.poiesis.externalDependencies.minio.url -}}
  {{- $subchartMinioEnabled := .Values.minio.enabled -}}
  {{- if $externalMinioEnabled -}}
    {{- if $externalMinioUrl -}}
      {{- $externalMinioUrl | quote -}}
    {{- else -}}
      {{- fail (printf "\n[poiesis.minio.url] External MinIO (poiesis.externalDependencies.minio) is enabled but 'poiesis.externalDependencies.minio.url' is missing or empty.") -}}
    {{- end -}}
  {{- else if $subchartMinioEnabled -}}
    {{- $minioServiceFullName := include "poiesis.minio.fullname" . -}}
    {{- $minioServicePort := .Values.minio.service.ports.api -}}
    "http://{{ $minioServiceFullName }}:{{ $minioServicePort }}"
  {{- else -}}
    ""
  {{- end -}}
{{- end -}}

{{/*
Return the configured MinIO username.
Checks poiesis.externalDependencies.username first, then the Bitnami subchart minio.
Fails if neither username is found and one of them is enabled, with specific
error for external MinIO password missing.
*/}}
{{- define "poiesis.minio.username" -}}
  {{- $externalMinioEnabled := .Values.poiesis.externalDependencies.minio.enabled -}}
  {{- $externalMinioUser := .Values.poiesis.externalDependencies.minio.rootUser -}}
  {{- $subchartMinioEnabled := .Values.minio.enabled -}}
  {{- $subchartMinioUser := .Values.minio.auth.rootUser -}}

  {{- if and $externalMinioEnabled (not $externalMinioUser) -}}
	{{- fail (printf "\n[poiesis.minio.password] External MinIO (poiesis.externalDependencies.minio) is enabled but 'poiesis.externalDependencies.minio.rootPassword' is missing or empty.") -}}
  {{- else if and $externalMinioEnabled $externalMinioUser -}}
	{{- $externalMinioUser -}}
  {{- else if and $subchartMinioEnabled $subchartMinioUser -}}
	{{- $subchartMinioUser -}}
  {{- else -}}
	{{- fail (printf "\n[poiesis.minio.password] You forgot to set rootPassword for MinIO.\n- If using a custom MinIO under 'poiesis.externalDependencies.minio', ensure 'poiesis.externalDependencies.minio.enabled' is true and set:\n  poiesis.externalDependencies.minio.rootPassword: <your-password>\n- If using the Bitnami subchart 'minio', ensure 'minio.enabled' is true and set:\n  minio.auth.rootPassword: <your-password>") -}}
  {{- end -}}
{{- end -}}

{{/*
Return the configured MinIO password.
Checks poiesis.externalDependencies.minio first, then the Bitnami subchart minio.
Fails if neither password is found and one of them is enabled, with specific error for external MinIO password missing.
*/}}
{{- define "poiesis.minio.password" -}}
  {{- $externalMinioEnabled := .Values.poiesis.externalDependencies.minio.enabled -}}
  {{- $externalMinioPassword := .Values.poiesis.externalDependencies.minio.rootPassword -}}
  {{- $subchartMinioEnabled := .Values.minio.enabled -}}
  {{- $subchartMinioPassword := .Values.minio.auth.rootPassword -}}

  {{- if and $externalMinioEnabled (not $externalMinioPassword) -}}
	{{- fail (printf "\n[poiesis.minio.password] External MinIO (poiesis.externalDependencies.minio) is enabled but 'poiesis.externalDependencies.minio.rootPassword' is missing or empty.") -}}
  {{- else if and $externalMinioEnabled $externalMinioPassword -}}
	{{- $externalMinioPassword -}}
  {{- else if and $subchartMinioEnabled $subchartMinioPassword -}}
	{{- $subchartMinioPassword -}}
  {{- else -}}
	{{- fail (printf "\n[poiesis.minio.password] You forgot to set rootPassword for MinIO.\n- If using a custom MinIO under 'poiesis.externalDependencies.minio', ensure 'poiesis.externalDependencies.minio.enabled' is true and set:\n  poiesis.externalDependencies.minio.rootPassword: <your-password>\n- If using the Bitnami subchart 'minio', ensure 'minio.enabled' is true and set:\n  minio.auth.rootPassword: <your-password>") -}}
  {{- end -}}
{{- end -}}

{{/* -----------------------------  Config ----------------------------- */}}

{{/*
Core configmap name
*/}}
{{- define "poiesis.coreConfigMapName" -}}
{{- printf "%s-core-configmap" (include "poiesis.fullname" .) -}}
{{- end -}}

