{{/*
nodeSelector / tolerations / affinity / imagePullSecrets resolution.
Per-component overrides win; if unset, falls through to chart-wide defaults.

Pass: (dict "component" .Values.api "root" .)
*/}}

{{- define "poiesis.nodeSelector" -}}
{{- $sel := .component.nodeSelector -}}
{{- if not $sel -}}{{- $sel = .root.Values.nodeSelector -}}{{- end -}}
{{- with $sel }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "poiesis.tolerations" -}}
{{- $tol := .component.tolerations -}}
{{- if not $tol -}}{{- $tol = .root.Values.tolerations -}}{{- end -}}
{{- with $tol }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "poiesis.affinity" -}}
{{- $aff := .component.affinity -}}
{{- if not $aff -}}{{- $aff = .root.Values.affinity -}}{{- end -}}
{{- with $aff }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "poiesis.imagePullSecrets" -}}
{{- with .root.Values.imagePullSecrets }}
{{ toYaml . }}
{{- end }}
{{- end -}}
