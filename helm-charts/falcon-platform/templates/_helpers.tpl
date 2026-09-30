{{/* Expand the name of the chart */}}
{{- define "falcon-platform.name" -}}
{{- .Chart.Name }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "falcon-platform.fullname" -}}
{{- $name := .Chart.Name }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/* Create chart name and version as used by the chart label */}}
{{- define "falcon-platform.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Common labels */}}
{{- define "falcon-platform.labels" -}}
helm.sh/chart: {{ include "falcon-platform.chart" . }}
{{ include "falcon-platform.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
crowdstrike.com/provider: crowdstrike
{{- end }}

{{/* Selector labels */}}
{{- define "falcon-platform.selectorLabels" -}}
app.kubernetes.io/name: {{ include "falcon-platform.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* Component namespaces */}}
{{- define "falcon-platform.componentNamespaces" -}}
{{- $namespaces := list -}}
{{- if and (index .Values "falcon-clusterguard").enabled (index .Values "falcon-clusterguard").namespaceOverride -}}
{{- $namespaces = append $namespaces (index .Values "falcon-clusterguard").namespaceOverride -}}
{{- end -}}
{{- if and (index .Values "falcon-image-analyzer").enabled (index .Values "falcon-image-analyzer").namespaceOverride -}}
{{- $namespaces = append $namespaces (index .Values "falcon-image-analyzer").namespaceOverride -}}
{{- end -}}
{{- if and (index .Values "falcon-sensor").enabled (index .Values "falcon-sensor").namespaceOverride -}}
{{- $namespaces = append $namespaces (index .Values "falcon-sensor").namespaceOverride -}}
{{- end -}}
{{- $namespaces | uniq | join "," -}}
{{- end }}

{{/* Returns "true" when the clusterguard controller Deployment is disabled via the acknowledgement string */}}
{{- define "falcon-platform.clusterGuardDisabled" -}}
{{- $fcg := index .Values "falcon-clusterguard" -}}
{{- if eq (($fcg.cluster).disableClusterGuard | default "") "I understand this disables K8s metadata and degrades node sensor visibility" -}}
true
{{- else -}}
false
{{- end -}}
{{- end }}
