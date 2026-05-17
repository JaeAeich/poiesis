{{/*
Naming, labels, and resolution helpers.

The image / env / volume helpers take a 2-tuple `(.Values.<component>) .`
where the first is the component dict and the second is the root context.
Top-level defaults are pulled from the root; per-component overrides win.
*/}}

{{- define "poiesis.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

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

{{- define "poiesis.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels carried by every chart-owned object. commonLabels merge in
last so operator overrides win.
*/}}
{{- define "poiesis.labels" -}}
helm.sh/chart: {{ include "poiesis.chart" . }}
{{ include "poiesis.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: poiesis
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "poiesis.selectorLabels" -}}
app.kubernetes.io/name: {{ include "poiesis.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "poiesis.componentSelectorLabels" -}}
{{ include "poiesis.selectorLabels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "poiesis.componentLabels" -}}
{{ include "poiesis.labels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/*
commonAnnotations rendered onto every object. Use with `nindent`.
*/}}
{{- define "poiesis.commonAnnotations" -}}
{{- with .Values.commonAnnotations }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/*
ServiceAccount name resolution. `.role` is api|tctl|taskpod.
*/}}
{{- define "poiesis.serviceAccountName" -}}
{{- $sa := index .root.Values.serviceAccount .role -}}
{{- if $sa.create -}}
{{ default (printf "%s-%s" (include "poiesis.fullname" .root) .role) $sa.name }}
{{- else -}}
{{ required (printf "serviceAccount.%s.name is required when create=false" .role) $sa.name }}
{{- end -}}
{{- end -}}

{{/*
Image resolution with per-component override. Pass `(dict "component" .Values.api "root" .)`.
The override block accepts any subset of {registry, repository, tag, pullPolicy};
omitted keys fall through to .Values.image. The migrations image uses its own
top-level block (`.Values.migrations.image`) — see `poiesis.migrations.image`.
*/}}
{{- define "poiesis.image" -}}
{{- $override := default (dict) .component.image -}}
{{- $registry := default .root.Values.image.registry $override.registry -}}
{{- $repo := default .root.Values.image.repository $override.repository -}}
{{- $tag := default .root.Values.image.tag $override.tag -}}
{{- if not $tag -}}{{- $tag = .root.Chart.AppVersion -}}{{- end -}}
{{ printf "%s/%s:%s" $registry $repo $tag }}
{{- end -}}

{{- define "poiesis.imagePullPolicy" -}}
{{- $override := default (dict) .component.image -}}
{{- default .root.Values.image.pullPolicy $override.pullPolicy -}}
{{- end -}}

{{- define "poiesis.migrations.image" -}}
{{- $img := .Values.migrations.image -}}
{{- $tag := default .Chart.AppVersion $img.tag -}}
{{ printf "%s/%s:%s" $img.registry $img.repository $tag }}
{{- end -}}

{{/*
Taskpod namespace: empty → release namespace; otherwise as set.
*/}}
{{- define "poiesis.taskpodNamespace" -}}
{{ default .Release.Namespace .Values.taskpods.namespace }}
{{- end -}}

{{/*
PodSecurity profile fragments. Render at the right indent with `nindent`.
podSecurityContext is at the Pod level; containerSecurityContext is
applied per container. Both honour podSecurityEnforce: restricted | baseline | off.
*/}}
{{- define "poiesis.podSecurityContext" -}}
{{- if eq .Values.podSecurityEnforce "off" -}}
{}
{{- else -}}
runAsNonRoot: true
runAsUser: 65532
runAsGroup: 65532
fsGroup: 65532
seccompProfile:
  type: RuntimeDefault
{{- end -}}
{{- with .Values.podSecurityContext }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "poiesis.containerSecurityContext" -}}
{{- if eq .Values.podSecurityEnforce "off" -}}
{}
{{- else if eq .Values.podSecurityEnforce "baseline" -}}
allowPrivilegeEscalation: false
capabilities:
  drop: [ALL]
{{- else -}}
runAsNonRoot: true
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
seccompProfile:
  type: RuntimeDefault
{{- end -}}
{{- with .Values.containerSecurityContext }}
{{ toYaml . }}
{{- end }}
{{- end -}}
