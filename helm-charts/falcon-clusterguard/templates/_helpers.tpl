{{/*
Expand the name of the chart.
*/}}
{{- define "falcon-clusterguard.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
TODO: Make sure names when migrating are persisted as much as possible. Otherwise highlight the name changes in the output of the migration script
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
Cluster Guard controller Deployment name: <name>-controller.
Follows nameOverride; defaults to falcon-clusterguard-controller. The name is truncated before
the suffix is added so the result always ends in -controller and stays within 63 characters.
*/}}
{{- define "falcon-clusterguard.controllerName" -}}
{{- printf "%s-controller" (include "falcon-clusterguard.name" . | trunc 52 | trimSuffix "-") }}
{{- end }}

{{/*
Node sensor DaemonSet name. Configurable with node.daemonset.name; defaults to falcon-sensor.
*/}}
{{- define "falcon-clusterguard.nodeDaemonsetName" -}}
{{- if .Values.nameOverride }}
    {{- printf "%s-sensor" (.Values.nameOverride | trunc 56 | trimSuffix "-") }}
{{- else }}
    {{- "falcon-sensor" }}
{{- end }}
{{- end -}}

{{/*
gRPC API service name for the central metadata service.
Hardcoded — always api.<release-namespace>.svc, not user-configurable.
*/}}
{{- define "falcon-clusterguard.apiServiceName" -}}
{{- printf "api.%s.svc" (include "falcon-clusterguard.namespace" .) }}
{{- end -}}

{{/*
Set the webhook name (used in ValidatingWebhookConfiguration)
*/}}
{{- define "falcon-clusterguard.webhookName" -}}
{{ "falcon-clusterguard.crowdstrike.com" }}
{{- end }}

{{/*
DNS names for the admission webhook TLS certificate, as a YAML list (use with fromYamlArray).
The first entry is the certificate's common name. Shared by the Helm-generated certificate
(cg-controller/deployment.yaml) and the cert-manager Certificate (cg-controller/certificate.yaml).
*/}}
{{- define "falcon-clusterguard.webhookDNSNames" -}}
{{- $ns := include "falcon-clusterguard.namespace" . -}}
{{- $fullName := printf "webhook.%s.svc" $ns -}}
{{- if .Values.cluster.domainName -}}
{{- $fullName = printf "webhook.%s.svc.%s" $ns .Values.cluster.domainName -}}
{{- end -}}
{{- list $fullName (printf "%s.cluster.local" $fullName) (printf "webhook.%s" $ns) "webhook" | toYaml -}}
{{- end -}}

{{/*
Name of the chart-owned self-signed ClusterIssuer that issues the gRPC mTLS CA when
certManager.enabled=true (cg-controller/certificate.yaml).
*/}}
{{- define "falcon-clusterguard.grpcSelfSignedIssuerName" -}}
{{- printf "%s-grpc-selfsigned" (include "falcon-clusterguard.fullname" .) -}}
{{- end -}}

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
app.kubernetes.io/component: falcon-clusterguard
app.kubernetes.io/name: {{ include "falcon-clusterguard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
crowdstrike.com/provider: crowdstrike
{{- end }}

{{/*
Common Node labels
*/}}
{{- define "falcon-clusterguard.nodeLabels" -}}
helm.sh/chart: {{ include "falcon-clusterguard.chart" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{ include "falcon-clusterguard.nodeSelectorLabels" . }}
{{- end }}

{{/*
Node specific selector labels (used by the node sensor workloads)
*/}}
{{- define "falcon-clusterguard.nodeSelectorLabels" -}}
app.kubernetes.io/name: {{ include "falcon-clusterguard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: kernel_sensor
crowdstrike.com/provider: crowdstrike
{{- end }}

{{/*
Node sensor pod label used by the Guardian proxy Service selector.
*/}}
{{- define "falcon-clusterguard.falconSensorAppLabel" -}}
app: falcon-sensor
{{- end }}

{{/*
CG Controller labels without selector label
*/}}
{{- define "falcon-clusterguard.cgControllerLabelsWithoutSelector" -}}
helm.sh/chart: {{ include "falcon-clusterguard.chart" . }}
app.kubernetes.io/component: fcg-controller
app.kubernetes.io/name: {{ include "falcon-clusterguard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
crowdstrike.com/provider: crowdstrike
{{- end }}

{{/*
Common CG Controller labels
*/}}
{{- define "falcon-clusterguard.cgControllerLabels" -}}
{{ include "falcon-clusterguard.cgControllerSelectorLabels" . }}
{{ include "falcon-clusterguard.cgControllerLabelsWithoutSelector" . }}
{{- end }}

{{/*
CG Controller specific selector labels (used by the cg-controller workloads)
*/}}
{{- define "falcon-clusterguard.cgControllerSelectorLabels" -}}
app: falcon-clusterguard
{{- end }}

{{/*
ServiceAccount name for the node sensor DaemonSet (privileged; bound to node SCC on OpenShift)
*/}}
{{- define "falcon-clusterguard.nodeServiceAccountName" -}}
{{- default (printf "%s-node-sensor-sa" (include "falcon-clusterguard.fullname" .)) .Values.node.serviceAccount.name }}
{{- end }}

{{/*
ServiceAccount name for the clusterguard controller Deployment (restricted; no host access)
*/}}
{{- define "falcon-clusterguard.clusterServiceAccountName" -}}
{{- default (printf "%s-clusterguard-controller-sa" (include "falcon-clusterguard.fullname" .)) .Values.cluster.serviceAccount.name }}
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
{{- if .Values.gke.autopilot -}}
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
{{- define "falcon-clusterguard.nodeInitArgs" -}}
args:
  - '-c'
  - >-
      set -e;
      if [ ! -f /opt/CrowdStrike/falcon-daemonset-init ]; then
      echo "Error: This is not a falcon cluster guard image";
      exit 1;
      fi;
      echo "Running /opt/CrowdStrike/falcon-daemonset-init -i";
      /opt/CrowdStrike/falcon-daemonset-init -i;
      echo "Running /opt/CrowdStrike/configure-cluster-id";
      /opt/CrowdStrike/configure-cluster-id;
{{- end -}}

{{/*
ConfigMap name for the node sensor DaemonSet.
Fixed name — required by GKE Autopilot WorkloadAllowlist and matches the reference manifest.
*/}}
{{- define "falcon-clusterguard.nodeConfigMapName" -}}
{{- printf "falcon-sensor-config" -}}
{{- end -}}

{{/*
ConfigMap name for the clusterguard controller Deployment.
*/}}
{{- define "falcon-clusterguard.cgControllerConfigMapName" -}}
{{- printf "falcon-clusterguard-config" -}}
{{- end -}}

{{/*
GKE WorkloadAllowlist label for the deploy DaemonSet
*/}}
{{- define "falcon-clusterguard.workloadDeployAllowlistLabel" -}}
{{- if and .Values.gke.autopilot .Values.node.enabled .Values.gke.deployAllowListVersion -}}
{{- printf "cloud.google.com/matching-allowlist: \"crowdstrike-falconsensor-deploy-allowlist-%s\"" .Values.gke.deployAllowListVersion -}}
{{- end -}}
{{- end -}}

{{/*
GKE WorkloadAllowlist label for the cleanup DaemonSet
*/}}
{{- define "falcon-clusterguard.workloadCleanupAllowlistLabel" -}}
{{- if and .Values.gke.autopilot .Values.node.enabled .Values.gke.cleanupAllowListVersion -}}
{{- printf "cloud.google.com/matching-allowlist: \"crowdstrike-falconsensor-cleanup-allowlist-%s\"" .Values.gke.cleanupAllowListVersion -}}
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
{{- if .Values.namespaceOverride -}}
{{- .Values.namespaceOverride -}}
{{- else -}}
{{- .Release.Namespace -}}
{{- end -}}
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
Reads .Values.cluster.visibility.* with safe defaults if values are missing.
*/}}
{{- define "falcon-clusterguard.generateWatcherEnvVars" -}}
{{- $snapshotsEnabled := true -}}
{{- $snapshotInterval := "22h" -}}
{{- $watcherEnabled := true -}}
{{- $configMapEnabled := true -}}
{{- if .Values.cluster.visibility -}}
{{- if .Values.cluster.visibility.resourceSnapshots -}}
  {{- if ne .Values.cluster.visibility.resourceSnapshots.enabled nil -}}
  {{ $snapshotsEnabled = .Values.cluster.visibility.resourceSnapshots.enabled -}}
  {{- end -}}
  {{- if .Values.cluster.visibility.resourceSnapshots.interval -}}
  {{ $snapshotInterval = .Values.cluster.visibility.resourceSnapshots.interval -}}
  {{- end -}}
{{- end -}}
{{- if .Values.cluster.visibility.resourceWatcher -}}
  {{- if ne .Values.cluster.visibility.resourceWatcher.enabled nil -}}
  {{ $watcherEnabled = .Values.cluster.visibility.resourceWatcher.enabled -}}
  {{- end -}}
{{- end -}}
{{- if .Values.cluster.visibility.resourceConfigMap -}}
  {{- if ne .Values.cluster.visibility.resourceConfigMap.enabled nil -}}
  {{ $configMapEnabled = .Values.cluster.visibility.resourceConfigMap.enabled -}}
  {{- end -}}
{{- end -}}
{{- end -}}
__CS_SNAPSHOTS_ENABLED: {{ $snapshotsEnabled | toString | quote }}
__CS_SNAPSHOT_INTERVAL: {{ $snapshotInterval | toString | quote }}
__CS_WATCH_EVENTS_ENABLED: {{ $watcherEnabled | toString | quote }}
__CS_VISIBILITY_CONFIGMAPS_ENABLED: {{ $configMapEnabled | toString | quote }}
{{- end -}}

{{/*
Disable cluster guard, which disables K8s metadata and degrades node sensor visibility
*/}}
{{- define "falcon-clusterguard.clusterGuardDisabled" -}}
{{- if eq .Values.cluster.disableClusterGuard "I understand this disables K8s metadata and degrades node sensor visibility" -}}
true
{{- else -}}
false
{{- end -}}
{{- end -}}

{{/*
Admission control enabled? True if both cluster AND admissionControl are enabled.
*/}}
{{- define "falcon-clusterguard.admissionControlEnabled" -}}
{{- if and (eq (include "falcon-clusterguard.clusterGuardDisabled" .) "false") .Values.cluster.admissionControl.enabled -}}
true
{{- else -}}
false
{{- end -}}
{{- end -}}

{{/*
Validate high level FCG components are configured properly
*/}}
{{- define "falcon-clusterguard.validateValues" -}}
{{- if and (eq (include "falcon-clusterguard.clusterGuardDisabled" .) "true") (not .Values.node.enabled) }}
    {{ fail "Error: at least one of Node Sensor or Cluster Guard must be enabled." }}
{{- end }}

{{- if and (eq (include "falcon-clusterguard.clusterGuardDisabled" .) "true") .Values.cluster.admissionControl.enabled }}
    {{ fail "Error: cluster.admissionControl.enabled cannot be true when cluster guard is disabled. Cluster Guard is required for the admission controller." }}
{{- end }}

{{- if and (not .Values.image.tag) (not .Values.image.digest) }}
    {{ fail "Error: image.tag or image.digest must be set." }}
{{- end }}
{{- end -}}

{{/*
Get Falcon CID
*/}}
{{- define "falcon-clusterguard.falconCid" -}}
{{- if and .Values.global.falcon.cid (not .Values.falcon.cid) -}}
{{- .Values.global.falcon.cid -}}
{{- else -}}
{{- .Values.falcon.cid | default "" -}}
{{- end -}}
{{- end -}}

{{/*
Check if Falcon secret is enabled — true if either chart-level or global is true.
*/}}
{{- define "falcon-clusterguard.falconSecretEnabled" -}}
{{- or .Values.global.falconSecret.enabled .Values.falconSecret.enabled -}}
{{- end -}}

{{/*
Get Falcon secret name
*/}}
{{- define "falcon-clusterguard.falconSecretName" -}}
{{- if and .Values.global.falconSecret.secretName (not .Values.falconSecret.secretName) -}}
{{- .Values.global.falconSecret.secretName -}}
{{- else -}}
{{- .Values.falconSecret.secretName | default "" -}}
{{- end -}}
{{- end -}}

{{/*
Validate exactly one of falcon.cid, falconSecret, or secretsStore is configured.
*/}}
{{- define "falcon-clusterguard.validateOneOfFalconCidOrFalconSecret" -}}
{{- $hasCid := include "falcon-clusterguard.falconCid" . -}}
{{- $secretEnabled := (include "falcon-clusterguard.falconSecretEnabled" . | eq "true") -}}
{{- $hasSecret := include "falcon-clusterguard.falconSecretName" . -}}
{{- $csiEnabled := (include "falcon-clusterguard.csiEnabled" . | eq "true") -}}

{{- if and (not $hasCid) (or (not $secretEnabled) (not $hasSecret)) (not $csiEnabled) -}}
{{- fail "Must configure one of falcon.cid, falconSecret with FALCONCTL_OPT_CID data, or secretsStore" }}
{{- end -}}

{{- if and ($hasCid) ($secretEnabled) -}}
{{- fail "Cannot use both falcon.cid and falconSecret" }}
{{- end -}}
{{- end -}}

{{/*
Get container registry pull secret name
*/}}
{{- define "falcon-clusterguard.imagePullSecret" -}}
{{- if and .Values.global.containerRegistry.pullSecret (not .Values.image.pullSecret) -}}
{{- .Values.global.containerRegistry.pullSecret -}}
{{- else -}}
{{- .Values.image.pullSecret | default "" -}}
{{- end -}}
{{- end -}}

{{/*
Get container registry config JSON
*/}}
{{- define "falcon-clusterguard.registryConfigJson" -}}
{{- if and .Values.global.containerRegistry.configJSON (not .Values.image.registryConfigJSON) -}}
{{- .Values.global.containerRegistry.configJSON -}}
{{- else -}}
{{- .Values.image.registryConfigJSON | default "" -}}
{{- end -}}
{{- end -}}

{{/*
Name of the image pull Secret the chart creates from the registry config JSON.
Used by the Secret itself and by every workload that pulls the FCG image.
*/}}
{{- define "falcon-clusterguard.pullSecretName" -}}
{{- printf "%s-pull-secret" (include "falcon-clusterguard.fullname" .) -}}
{{- end -}}

{{/*
Name of the post-delete hook copy of the image pull Secret used by the node cleanup DaemonSet.
helm uninstall deletes the main pull Secret before post-delete hooks run, so the cleanup needs its own copy.
*/}}
{{- define "falcon-clusterguard.cleanupPullSecretName" -}}
{{- printf "%s-pull-secret-cleanup" (include "falcon-clusterguard.fullname" .) -}}
{{- end -}}

{{/*
Validate IAR workload mode settings.
*/}}
{{- define "falcon-clusterguard.validateIarMode" -}}
{{- $imageAnalyzer := .Values.imageAnalyzer }}
{{- $errors := list -}}

{{- if not (has $imageAnalyzer.mode (list "deployment" "daemonset")) -}}
    {{- $errors = append $errors (printf "imageAnalyzer.mode must be deployment or daemonset, got %q" (toString $imageAnalyzer.mode)) -}}
{{- else if eq (toString $imageAnalyzer.mode) "daemonset" -}}
    {{- if not (has $imageAnalyzer.crowdstrikeConfig.agentRuntime (list "docker" "containerd" "crio" "podman")) -}}
        {{- $errors = append $errors "imageAnalyzer.crowdstrikeConfig.agentRuntime must be docker, containerd, crio, or podman when imageAnalyzer.mode is daemonset" -}}
    {{- end -}}
{{- end -}}

{{- if $errors -}}
    {{- fail (printf "IAR mode validation failed:\n  - %s" (join "\n  - " $errors)) -}}
{{- end -}}
{{- end -}}

{{/*
Get the name of the Kubernetes secret created by the CSI driver.
*/}}
{{- define "falcon-clusterguard.csiSecretName" -}}
{{- $csiSecretName := .Values.secretsStore.secretName | default .Values.global.secretsStore.secretName -}}
{{- if $csiSecretName -}}
{{- $csiSecretName -}}
{{- else -}}
{{- printf "%s-csi" (include "falcon-clusterguard.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Returns true when Secrets Store CSI is enabled.
Component-level setting overrides global.
*/}}
{{- define "falcon-clusterguard.csiEnabled" -}}
{{- if eq .Values.secretsStore.enabled false -}}
{{- /* Explicitly disabled at chart level — don't check global */ -}}
{{- else if or .Values.secretsStore.enabled .Values.global.secretsStore.enabled -}}
true
{{- end -}}
{{- end -}}

{{/*
Returns the effective CSI provider (chart-level overrides global).
*/}}
{{- define "falcon-clusterguard.csiProvider" -}}
{{- .Values.secretsStore.provider | default .Values.global.secretsStore.provider -}}
{{- end -}}

{{/*
Container env entries that read FALCONCTL_OPT_* from the CSI-synced secret.
Used by every node sensor and clusterguard controller container when Secrets Store CSI is enabled.
*/}}
{{- define "falcon-clusterguard.csiEnvVars" -}}
- name: FALCONCTL_OPT_CID
  valueFrom:
    secretKeyRef:
      name: {{ include "falcon-clusterguard.csiSecretName" . }}
      key: FALCONCTL_OPT_CID
      optional: true
{{- if .Values.secretsStore.provisioningTokenSecretName }}
- name: FALCONCTL_OPT_PROVISIONING_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "falcon-clusterguard.csiSecretName" . }}
      key: FALCONCTL_OPT_PROVISIONING_TOKEN
      optional: true
{{- end }}
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
OpenShift SCC name for the clusterguard controller Deployment (hostNetwork SCC)
*/}}
{{- define "falcon-clusterguard.cgControllerSccName" -}}
{{- if .Values.openshift.cgControllerSCCName -}}
{{- .Values.openshift.cgControllerSCCName -}}
{{- else -}}
{{- printf "%s-cg-controller" (include "falcon-clusterguard.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
OpenShift mode enabled — true if either chart-level or global is true.
*/}}
{{- define "falcon-clusterguard.openshiftEnabled" -}}
{{- or .Values.openshift.enabled .Values.global.openshift.enabled -}}
{{- end -}}

{{/*
OpenShift node createSCC — false if either chart-level or global disables it.
*/}}
{{- define "falcon-clusterguard.openshiftNodeCreateSCC" -}}
{{- and (or .Values.openshift.enabled .Values.global.openshift.enabled) .Values.openshift.createSCC .Values.global.openshift.createSCC -}}
{{- end -}}

{{/*
OpenShift clusterguard controller createSCC — requires openshift enabled, createSCC, and cluster.hostNetwork.
*/}}
{{- define "falcon-clusterguard.openshiftCgControllerCreateSCC" -}}
{{- and (or .Values.openshift.enabled .Values.global.openshift.enabled) .Values.openshift.createSCC .Values.global.openshift.createSCC .Values.cluster.hostNetwork -}}
{{- end -}}

{{/*
HELM_CHART value
Use global.helmChart (set by a parent umbrella chart) when present so the value reflects the
top-level chart identity rather than this subchart.
*/}}
{{- define "falcon-clusterguard.helmChart" -}}
{{- if .Values.global.helmChart -}}
{{- .Values.global.helmChart -}}
{{- else -}}
{{- include "falcon-clusterguard.chart" . -}}
{{- end -}}
{{- end -}}

{{/*
Labels for test pods/resources
*/}}
{{- define "falcon-clusterguard.testLabels" -}}
helm.sh/chart: {{ include "falcon-clusterguard.chart" . }}
app.kubernetes.io/component: test
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
{{- end -}}
