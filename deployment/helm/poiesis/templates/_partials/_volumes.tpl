{{/*
Volume / volumeMount rendering. Three layers stacked:

  1. Chart-managed volumes (writable /tmp for read-only-rootfs, optional
     postgres CA bundle when .Values.database.caConfigmap is set).
  2. Top-level extras (.Values.extraVolumes / extraVolumeMounts).
  3. Per-component extras (component.extraVolumes / extraVolumeMounts).

Each helper emits the full list ready to drop into a container's
`volumeMounts:` or a Pod's `volumes:`.

Pass: (dict "component" .Values.api "root" .)
*/}}

{{- define "poiesis.volumes" -}}
- name: tmp
  emptyDir: {}
{{- with .root.Values.database.caConfigmap }}
- name: postgres-ca
  configMap:
    name: {{ . }}
    defaultMode: 0444
{{- end }}
{{- with concat (default (list) .root.Values.extraVolumes) (default (list) .component.extraVolumes) }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "poiesis.volumeMounts" -}}
- name: tmp
  mountPath: /tmp
{{- with .root.Values.database.caConfigmap }}
- name: postgres-ca
  mountPath: /etc/ssl/poiesis
  readOnly: true
{{- end }}
{{- with concat (default (list) .root.Values.extraVolumeMounts) (default (list) .component.extraVolumeMounts) }}
{{ toYaml . }}
{{- end }}
{{- end -}}
