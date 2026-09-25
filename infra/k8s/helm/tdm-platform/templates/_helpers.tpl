{{/*
Shared name helpers, following the standard Helm chart-name/release-name
convention (`helm create`'s own generated chart uses the same pattern) so
this chart composes predictably with `helm install <release> ...`.
*/}}

{{- define "tdm-platform.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "tdm-platform.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "tdm-platform.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "tdm-platform.labels" -}}
app.kubernetes.io/name: {{ include "tdm-platform.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: tdm-platform
{{- end -}}
