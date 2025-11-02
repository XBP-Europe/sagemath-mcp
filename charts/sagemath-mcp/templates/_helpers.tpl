{{/*
Expand the name of the chart.
*/}}
{{- define "sagemath-mcp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "sagemath-mcp.fullname" -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/*
Common chart labels.
*/}}
{{- define "sagemath-mcp.labels" -}}
helm.sh/chart: {{ include "sagemath-mcp.chart" . }}
app.kubernetes.io/name: {{ include "sagemath-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Chart label string.
*/}}
{{- define "sagemath-mcp.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" -}}
{{- end -}}

{{/*
Selector labels.
*/}}
{{- define "sagemath-mcp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sagemath-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
