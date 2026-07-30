{{/*
Expand the name of the chart.
*/}}
{{- define "falcon-clusterguard.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
gRPC API service name for the central metadata service.
Hardcoded — always api.<release-namespace>.svc, not user-configurable.
*/}}
{{- define "falcon-clusterguard.apiServiceName" -}}
{{- printf "api.%s.svc" (include "falcon-clusterguard.namespace" .) -}}
{{- end -}}

{{/*
Set the webhook name (used in ValidatingWebhookConfiguration)
*/}}
{{- define "falcon-clusterguard.webhookName" -}}
{{ printf "%s.crowdstrike.com" .Chart.Name }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "falcon-clusterguard.fullname" -}}
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
{{- define "falcon-clusterguard.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "falcon-clusterguard.labels" -}}
helm.sh/chart: {{ include "falcon-clusterguard.chart" . }}
{{ include "falcon-clusterguard.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
crowdstrike.com/provider: crowdstrike
{{- end }}

{{/*
Selector labels
*/}}
{{- define "falcon-clusterguard.selectorLabels" -}}
app.kubernetes.io/name: {{ include "falcon-clusterguard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Admission-specific selector labels (used by the admission Deployment/Service/Webhook)
*/}}
{{- define "falcon-clusterguard.admissionSelectorLabels" -}}
app: {{ include "falcon-clusterguard.name" . }}-admission
{{- end }}

{{/*
Node-sensor-specific selector labels (used by the node DaemonSet)
*/}}
{{- define "falcon-clusterguard.nodeSelectorLabels" -}}
app: {{ include "falcon-clusterguard.name" . }}-node
{{- end }}

{{/*
ServiceAccount name for the node sensor DaemonSet (privileged; bound to node SCC on OpenShift)
*/}}
{{- define "falcon-clusterguard.nodeServiceAccountName" -}}
{{- default (printf "%s-sensor-sa" (include "falcon-clusterguard.fullname" .)) .Values.node.serviceAccount.name }}
{{- end }}

{{/*
ServiceAccount name for the admission controller Deployment (restricted; no host access)
*/}}
{{- define "falcon-clusterguard.admissionServiceAccountName" -}}
{{- default (printf "%s-admission-sa" (include "falcon-clusterguard.fullname" .)) .Values.admission.serviceAccount.name }}
{{- end }}

{{/*
Build the unified FCG image reference. Digest takes precedence over tag.
*/}}
{{- define "falcon-clusterguard.image" -}}
{{- if .Values.image.digest -}}
{{- if contains "sha256:" .Values.image.digest -}}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest -}}
{{- else -}}
{{- printf "%s@%s:%s" .Values.image.repository "sha256" .Values.image.digest -}}
{{- end -}}
{{- else -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag -}}
{{- end -}}
{{- end -}}

{{/*
PriorityClass name for the node DaemonSet
*/}}
{{- define "falcon-clusterguard.priorityClassName" -}}
{{- printf "%s" .Values.node.daemonset.priorityClassName -}}
{{- if not .Values.node.daemonset.priorityClassName -}}
{{- printf "%s" "falcon-clusterguard-node-security-critical" -}}
{{- end -}}
{{- end -}}

{{/*
DaemonSet resource block (GKE Autopilot enforces minimum defaults)
*/}}
{{- define "falcon-clusterguard.daemonsetResources" -}}
{{- if .Values.node.gke.autopilot -}}
resources:
  {{- if (.Values.node.daemonset.resources | default dict).limits }}
  limits:
    cpu: {{ (.Values.node.daemonset.resources.limits | default dict).cpu | default "750m" }}
    memory: {{ (.Values.node.daemonset.resources.limits | default dict).memory | default "1.5Gi" }}
    ephemeral-storage: {{ (index (.Values.node.daemonset.resources.limits | default dict) "ephemeral-storage") | default "100Mi" }}
  {{- else }}
  limits:
    cpu: 750m
    memory: 1.5Gi
    ephemeral-storage: 100Mi
  {{- end }}
  {{- if (.Values.node.daemonset.resources | default dict).requests }}
  requests:
    cpu: {{ (.Values.node.daemonset.resources.requests | default dict).cpu | default "750m" }}
    ephemeral-storage: {{ (index (.Values.node.daemonset.resources.requests | default dict) "ephemeral-storage") | default "100Mi" }}
    memory: {{ (.Values.node.daemonset.resources.requests | default dict).memory | default "1.5Gi" }}
  {{- else }}
  requests:
    cpu: 750m
    memory: 1.5Gi
    ephemeral-storage: 100Mi
  {{- end }}
{{- else -}}
{{- if .Values.node.daemonset.resources -}}
resources:
{{- toYaml .Values.node.daemonset.resources | trim | nindent 2 -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Init container args for the node daemonset (falconstore setup + cluster-id configure)
*/}}
{{- define "falcon-clusterguard.initArgs" -}}
args:
  - '-c'
  - >-
      set -e;
      if [ ! -f /opt/CrowdStrike/falcon-daemonset-init ]; then
      echo "Error: This is not a falcon node sensor(DaemonSet) image";
      exit 1;
      fi;
      echo "Running /opt/CrowdStrike/falcon-daemonset-init -i";
      /opt/CrowdStrike/falcon-daemonset-init -i;
      if [ ! -f /opt/CrowdStrike/configure-cluster-id ]; then
      echo "/opt/CrowdStrike/configure-cluster-id not found. Skipping.";
      else
      echo "Running /opt/CrowdStrike/configure-cluster-id";
      /opt/CrowdStrike/configure-cluster-id;
      fi
{{- end -}}

{{/*
Config map name for FCG (GKE Autopilot requires an exact name for WorkloadAllowlist)
*/}}
{{- define "falcon-clusterguard.configMapName" -}}
{{- if .Values.node.gke.autopilot -}}
{{- printf "falcon-clusterguard-config" -}}
{{- else -}}
{{- printf "%s-config" (include "falcon-clusterguard.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
GKE WorkloadAllowlist label for the deploy DaemonSet
*/}}
{{- define "falcon-clusterguard.workloadDeployAllowlistLabel" -}}
{{- if and .Values.node.gke.autopilot .Values.node.enabled .Values.node.gke.deployAllowListVersion -}}
{{- printf "cloud.google.com/matching-allowlist: \"crowdstrike-falconsensor-deploy-allowlist-%s\"" .Values.node.gke.deployAllowListVersion -}}
{{- end -}}
{{- end -}}

{{/*
GKE WorkloadAllowlist label for the cleanup DaemonSet
*/}}
{{- define "falcon-clusterguard.workloadCleanupAllowlistLabel" -}}
{{- if and .Values.node.gke.autopilot .Values.node.enabled .Values.node.gke.cleanupAllowListVersion -}}
{{- printf "cloud.google.com/matching-allowlist: \"crowdstrike-falconsensor-cleanup-allowlist-%s\"" .Values.node.gke.cleanupAllowListVersion -}}
{{- end -}}
{{- end -}}

{{/*
Service account name used by the post-delete cleanup DaemonSet
*/}}
{{- define "falcon-clusterguard.cleanupServiceAccountName" -}}
{{- if not .Values.node.cleanupOnly -}}
{{- printf "%s-node-cleanup" (include "falcon-clusterguard.nodeServiceAccountName" .) -}}
{{- else -}}
{{- printf "%s-node-cleanup-standalone" (include "falcon-clusterguard.nodeServiceAccountName" .) -}}
{{- end -}}
{{- end -}}

{{/*
Return namespace based on .Values.namespaceOverride or Release.Namespace
namespaceOverride should only be used when installing falcon-clusterguard as a subchart.
*/}}
{{- define "falcon-clusterguard.namespace" -}}
{{- .Release.Namespace -}}
{{- end -}}

{{/*
On OpenShift lookup namespaces and emit namespaces prefixed with "openshift-"
(used by webhook namespaceSelector to exclude system namespaces).
*/}}
{{- define "falcon-clusterguard.openshiftNamespaces" -}}
{{- if .Capabilities.APIVersions.Has "security.openshift.io/v1" -}}
{{- range $index, $namespace := (lookup "v1" "Namespace" "" "").items -}}
{{- if hasPrefix "openshift" $namespace.metadata.name -}}
- {{ printf "%s\n" $namespace.metadata.name }}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Generate the __CS_* env vars for the watcher/metadata containers.
Reads .Values.clusterVisibility.* with safe defaults if values are missing.
*/}}
{{- define "falcon-clusterguard.generateWatcherEnvVars" -}}
{{- $snapshotsEnabled := true -}}
{{- $snapshotInterval := "22h" -}}
{{- $watcherEnabled := true -}}
{{- $configMapEnabled := true -}}
{{- if .Values.clusterVisibility -}}
{{- if .Values.clusterVisibility.resourceSnapshots -}}
  {{- if ne .Values.clusterVisibility.resourceSnapshots.enabled nil -}}
  {{ $snapshotsEnabled = .Values.clusterVisibility.resourceSnapshots.enabled -}}
  {{- end -}}
  {{- if .Values.clusterVisibility.resourceSnapshots.interval -}}
  {{ $snapshotInterval = .Values.clusterVisibility.resourceSnapshots.interval -}}
  {{- end -}}
{{- end -}}
{{- if .Values.clusterVisibility.resourceWatcher -}}
  {{- if ne .Values.clusterVisibility.resourceWatcher.enabled nil -}}
  {{ $watcherEnabled = .Values.clusterVisibility.resourceWatcher.enabled -}}
  {{- end -}}
{{- end -}}
{{- if .Values.clusterVisibility.resourceConfigMap -}}
  {{- if ne .Values.clusterVisibility.resourceConfigMap.enabled nil -}}
  {{ $configMapEnabled = .Values.clusterVisibility.resourceConfigMap.enabled -}}
  {{- end -}}
{{- end -}}
{{- end -}}
__CS_SNAPSHOTS_ENABLED: {{ $snapshotsEnabled | toString | quote }}
__CS_SNAPSHOT_INTERVAL: {{ $snapshotInterval | toString | quote }}
__CS_WATCH_EVENTS_ENABLED: {{ $watcherEnabled | toString | quote }}
__CS_VISIBILITY_CONFIGMAPS_ENABLED: {{ $configMapEnabled | toString | quote }}
{{- end -}}

{{/*
Admission control enabled? True iff .Values.admission.enabled is truthy.
*/}}
{{- define "falcon-clusterguard.admissionEnabled" -}}
{{- if .Values.admission.enabled -}}
true
{{- else -}}
false
{{- end -}}
{{- end -}}

{{/*
Visibility enabled? True if either snapshots or watcher is enabled.
*/}}
{{- define "falcon-clusterguard.visibilityEnabled" -}}
{{- if or .Values.clusterVisibility.resourceSnapshots.enabled .Values.clusterVisibility.resourceWatcher.enabled -}}
true
{{- else -}}
false
{{- end -}}
{{- end -}}

{{/*
At least one of admission control or visibility must be enabled.
*/}}
{{- define "falcon-clusterguard.validateValues" -}}
{{- if and (eq (include "falcon-clusterguard.admissionEnabled" .) "false") (eq (include "falcon-clusterguard.visibilityEnabled" .) "false") -}}
{{- fail "Error: at least one of admission.enabled, clusterVisibility.resourceSnapshots.enabled, or clusterVisibility.resourceWatcher.enabled must be true." -}}
{{- end -}}
{{- end -}}

{{/*
Get Falcon CID
*/}}
{{- define "falcon-clusterguard.falconCid" -}}
{{- .Values.falcon.cid | default "" -}}
{{- end -}}

{{/*
Check if Falcon secret is enabled
*/}}
{{- define "falcon-clusterguard.falconSecretEnabled" -}}
{{- .Values.falconSecret.enabled -}}
{{- end -}}

{{/*
Get Falcon secret name
*/}}
{{- define "falcon-clusterguard.falconSecretName" -}}
{{- .Values.falconSecret.secretName | default "" -}}
{{- end -}}

{{/*
Validate exactly one of falcon.cid or falconSecret is configured
*/}}
{{- define "falcon-clusterguard.validateOneOfFalconCidOrFalconSecret" -}}
{{- $hasCid := include "falcon-clusterguard.falconCid" . -}}
{{- $secretEnabled := (include "falcon-clusterguard.falconSecretEnabled" . | eq "true") -}}
{{- $hasSecret := include "falcon-clusterguard.falconSecretName" . -}}

{{- if and (not $hasCid) (or (not $secretEnabled) (not $hasSecret)) -}}
{{- fail "Must configure one of falcon.cid or falconSecret with FALCONCTL_OPT_CID data" }}
{{- end -}}

{{- if and ($hasCid) ($secretEnabled) -}}
{{- fail "Cannot use both falcon.cid and falconSecret" }}
{{- end -}}
{{- end -}}

{{/*
Get container registry pull secret name
*/}}
{{- define "falcon-clusterguard.imagePullSecret" -}}
{{- .Values.image.pullSecrets | default "" -}}
{{- end -}}

{{/*
Get container registry config JSON
*/}}
{{- define "falcon-clusterguard.registryConfigJson" -}}
{{- .Values.image.registryConfigJSON | default "" -}}
{{- end -}}

{{/*
OpenShift SCC name for the node sensor DaemonSet (privileged SCC)
*/}}
{{- define "falcon-clusterguard.nodeSccName" -}}
{{- if .Values.openshift.nodeSCCName -}}
{{- .Values.openshift.nodeSCCName -}}
{{- else -}}
{{- printf "%s-node-sensor" (include "falcon-clusterguard.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
OpenShift SCC name for the admission controller Deployment (hostNetwork SCC)
*/}}
{{- define "falcon-clusterguard.admissionSccName" -}}
{{- if .Values.openshift.admissionSCCName -}}
{{- .Values.openshift.admissionSCCName -}}
{{- else -}}
{{- printf "%s-admission" (include "falcon-clusterguard.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
OpenShift mode enabled
*/}}
{{- define "falcon-clusterguard.openshiftEnabled" -}}
{{- .Values.openshift.enabled -}}
{{- end -}}

{{/*
OpenShift node createSCC — true when openshift.enabled and openshift.createSCC
*/}}
{{- define "falcon-clusterguard.openshiftNodeCreateSCC" -}}
{{- and .Values.openshift.enabled .Values.openshift.createSCC -}}
{{- end -}}

{{/*
OpenShift admission createSCC — true when openshift.enabled, openshift.createSCC, and admission.hostNetwork
*/}}
{{- define "falcon-clusterguard.openshiftAdmissionCreateSCC" -}}
{{- and .Values.openshift.enabled .Values.openshift.createSCC .Values.admission.hostNetwork -}}
{{- end -}}

{{/*
Labels for test pods/resources
*/}}
{{- define "falcon-clusterguard.testLabels" -}}
{{ include "falcon-clusterguard.labels" . }}
helm.sh/hook: test-success
helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded
{{- end -}}
