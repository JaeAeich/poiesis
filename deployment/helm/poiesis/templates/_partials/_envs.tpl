{{/*
Env / envFrom rendering. Top-level extras come first, per-component extras
append. The control-plane envFrom (chart ConfigMap, DATABASE_URL secret,
S3 secret) is the responsibility of the component template, not this
partial — partials only handle the operator-supplied extras.

Pass: (dict "component" .Values.api "root" .)
*/}}

{{- define "poiesis.extraEnv" -}}
{{- $merged := concat (default (list) .root.Values.extraEnv) (default (list) .component.extraEnv) -}}
{{- if $merged }}
{{- toYaml $merged }}
{{- end -}}
{{- end -}}

{{- define "poiesis.extraEnvFrom" -}}
{{- $merged := concat (default (list) .root.Values.extraEnvFrom) (default (list) .component.extraEnvFrom) -}}
{{- if $merged }}
{{- toYaml $merged }}
{{- end -}}
{{- end -}}
