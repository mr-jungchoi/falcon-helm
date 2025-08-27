{{/*
Expand the name of the chart.
*/}}
{{- define "falcon-platform.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "falcon-platform.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "falcon-platform.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "falcon-platform.labels" -}}
helm.sh/chart: {{ include "falcon-platform.chart" . }}
{{ include "falcon-platform.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Values.advanced.labels }}
{{ toYaml .Values.advanced.labels }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "falcon-platform.selectorLabels" -}}
app.kubernetes.io/name: {{ include "falcon-platform.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Global Falcon CID - use global value or individual chart value
*/}}
{{- define "falcon-platform.cid" -}}
{{- if .Values.global.falcon.cid }}
{{- .Values.global.falcon.cid }}
{{- end }}
{{- end }}

{{/*
Global Falcon Cloud Region - use global value or individual chart value  
*/}}
{{- define "falcon-platform.cloudRegion" -}}
{{- if .Values.global.falcon.cloud_region }}
{{- .Values.global.falcon.cloud_region }}
{{- end }}
{{- end }}

{{/*
Global Falcon Secret - use global value or individual chart value
*/}}
{{- define "falcon-platform.falconSecret" -}}
{{- if .Values.global.falconSecret }}
{{- toYaml .Values.global.falconSecret }}
{{- end }}
{{- end }}

{{/*
Global Registry Repository - use global value or individual chart value
*/}}
{{- define "falcon-platform.registry" -}}
{{- if .Values.global.registry.repository }}
{{- .Values.global.registry.repository }}
{{- end }}
{{- end }}

{{/*
Common annotations
*/}}
{{- define "falcon-platform.annotations" -}}
{{- if .Values.advanced.annotations }}
{{ toYaml .Values.advanced.annotations }}
{{- end }}
{{- end }}

{{/*
Determine if phased deployment is enabled
*/}}
{{- define "falcon-platform.phasedDeployment" -}}
{{- if .Values.deploymentConfig.phaseDeployment.enabled }}
{{- "true" }}
{{- else }}
{{- "false" }}
{{- end }}
{{- end }}

{{/*
Generate deployment order for components
*/}}
{{- define "falcon-platform.deploymentOrder" -}}
{{- if .Values.deploymentConfig.phaseDeployment.enabled }}
{{- $order := dict }}
{{- range $phase, $components := .Values.deploymentConfig.phaseDeployment }}
{{- if ne $phase "enabled" }}
{{- range $index, $component := $components }}
{{- $_ := set $order $component (printf "%s-%02d" $phase $index) }}
{{- end }}
{{- end }}
{{- end }}
{{ toYaml $order }}
{{- else }}
{{- dict }}
{{- end }}
{{- end }}

{{/*
Check if component is enabled
*/}}
{{- define "falcon-platform.componentEnabled" -}}
{{- $component := . }}
{{- $enabled := false }}
{{- if hasKey $.Values $component }}
{{- if hasKey (index $.Values $component) "enabled" }}
{{- $enabled = (index $.Values $component).enabled }}
{{- end }}
{{- end }}
{{- $enabled }}
{{- end }}

{{/*
Generate component-specific values with global overrides
*/}}
{{- define "falcon-platform.componentValues" -}}
{{- $component := .component }}
{{- $values := .values }}
{{- $global := .global }}

{{/* Merge global configuration into component values */}}
{{- $componentConfig := dict }}
{{- if hasKey $values $component }}
{{- $componentConfig = index $values $component }}
{{- end }}

{{/* Apply global CID if not set in component */}}
{{- if and $global.falcon.cid (not (hasKey $componentConfig "falcon")) }}
{{- $_ := set $componentConfig "falcon" (dict "cid" $global.falcon.cid) }}
{{- else if and $global.falcon.cid (hasKey $componentConfig "falcon") (not (hasKey $componentConfig.falcon "cid")) }}
{{- $_ := set $componentConfig.falcon "cid" $global.falcon.cid }}
{{- end }}

{{/* Apply global cloud region if not set in component */}}
{{- if and $global.falcon.cloud_region (hasKey $componentConfig "falcon") (not (hasKey $componentConfig.falcon "cloud_region")) }}
{{- $_ := set $componentConfig.falcon "cloud_region" $global.falcon.cloud_region }}
{{- end }}

{{/* Apply global falconSecret if not set in component and component supports it */}}
{{- $supportsFalconSecret := or (eq $component "falcon-sensor") (eq $component "falcon-kac") }}
{{- if and $supportsFalconSecret $global.falconSecret (not (hasKey $componentConfig "falconSecret")) }}
{{- $_ := set $componentConfig "falconSecret" $global.falconSecret }}
{{- else if and $supportsFalconSecret $global.falconSecret (hasKey $componentConfig "falconSecret") }}
{{/* Merge global falconSecret with component-specific overrides */}}
{{- if and $global.falconSecret.enabled (not (hasKey $componentConfig.falconSecret "enabled")) }}
{{- $_ := set $componentConfig.falconSecret "enabled" $global.falconSecret.enabled }}
{{- end }}
{{- if and $global.falconSecret.secretName (not (hasKey $componentConfig.falconSecret "secretName")) }}
{{- $_ := set $componentConfig.falconSecret "secretName" $global.falconSecret.secretName }}
{{- end }}
{{- end }}

{{ toYaml $componentConfig }}
{{- end }}