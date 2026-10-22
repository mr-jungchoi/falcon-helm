{{/* =========================================================================
     IAR (Image Analyzer) helpers — scoped to the .Values.imageAnalyzer sub-tree
     ========================================================================= */}}

{{/*
IAR-specific name
*/}}
{{- define "falcon-clusterguard.iarName" -}}
{{ printf "%s-iar" (include "falcon-clusterguard.name" . | trunc 59 | trimSuffix "-") }}
{{- end -}}

{{/*
IAR common labels
*/}}
{{- define "falcon-clusterguard.iarLabels" -}}
app.kubernetes.io/component: iar
crowdstrike.com/provider: crowdstrike
helm.sh/chart: {{ include "falcon-clusterguard.chart" . }}
{{ include "falcon-clusterguard.iarSelectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
IAR selector labels — matches the standalone falcon-image-analyzer chart for compatibility
*/}}
{{- define "falcon-clusterguard.iarSelectorLabels" -}}
app: falcon-image-analyzer
app.kubernetes.io/name: {{ include "falcon-clusterguard.iarName" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
IAR service name — hardcoded to match what the IAR binary expects
*/}}
{{- define "falcon-clusterguard.iarAgentService" -}}
{{- printf "iar-agent-service" -}}
{{- end -}}

{{/*
DNS names for the IAR agent service TLS certificate, as a YAML list (use with fromYamlArray).
The first entry is the certificate's common name. Same names as the standalone
falcon-image-analyzer chart. Shared by the Helm-generated certificate (image-analyzer/tls-secret.yaml)
and the cert-manager Certificate (image-analyzer/certificate.yaml).
*/}}
{{- define "falcon-clusterguard.iarDNSNames" -}}
{{- $ns := include "falcon-clusterguard.namespace" . -}}
{{- $svcName := include "falcon-clusterguard.iarAgentService" . -}}
{{- $fullSvcName := printf "%s.%s.svc" $svcName $ns -}}
{{- if .Values.imageAnalyzer.iarAgentService.domainName -}}
{{- $fullSvcName = printf "%s.%s.svc.%s" $svcName $ns .Values.imageAnalyzer.iarAgentService.domainName -}}
{{- end -}}
{{- list $fullSvcName (printf "%s.cluster.local" $fullSvcName) (printf "%s.%s" $fullSvcName $ns) | toYaml -}}
{{- end -}}

{{/*
IAR service account name
*/}}
{{- define "falcon-clusterguard.iarServiceAccountName" -}}
{{- default (include "falcon-clusterguard.iarName" .) .Values.imageAnalyzer.serviceAccount.name -}}
{{- end -}}

{{/*
Get the name of the Kubernetes secret created by the CSI driver for IAR.
Derived from secretsStore.secretName when set, so it never collides with the node/controller
secret (falcon-clusterguard.csiSecretName) in the shared namespace.
*/}}
{{- define "falcon-clusterguard.iarCsiSecretName" -}}
{{- $csiSecretName := .Values.secretsStore.secretName | default .Values.global.secretsStore.secretName -}}
{{- if $csiSecretName -}}
{{- printf "%s-iar" $csiSecretName -}}
{{- else -}}
{{- printf "%s-csi" (include "falcon-clusterguard.iarName" .) -}}
{{- end -}}
{{- end -}}

{{/*
Returns true when both IAR clientID and clientSecret are provided (chart creates the secret).
*/}}
{{- define "falcon-clusterguard.iarShouldCreateClientCredsInSecret" -}}
{{- $hasClientId := .Values.imageAnalyzer.crowdstrikeConfig.clientID | default "" | trim -}}
{{- $hasClientSecret := .Values.imageAnalyzer.crowdstrikeConfig.clientSecret | default "" | trim -}}
{{- if and $hasClientId $hasClientSecret -}}
true
{{- else -}}
false
{{- end -}}
{{- end -}}

{{/*
IAR tmp-volume size from volumes list
*/}}
{{- define "falcon-clusterguard.iarTempVolSize" -}}
{{- range $v := .Values.imageAnalyzer.volumes }}
{{- if eq $v.name "tmp-volume" }}
{{- printf $v.emptyDir.sizeLimit }}
{{- end }}
{{- end }}
{{- end -}}

{{/*
Returns true when IAR runs as a socket-mode DaemonSet instead of a watcher Deployment.
*/}}
{{- define "falcon-clusterguard.iarDaemonsetEnabled" -}}
{{- eq (toString .Values.imageAnalyzer.mode) "daemonset" -}}
{{- end -}}

{{/*
IAR container runtime socket (DaemonSet mode). Uses crowdstrikeConfig.agentRuntimeSocket if set,
otherwise the standard socket for crowdstrikeConfig.agentRuntime.
*/}}
{{- define "falcon-clusterguard.iarAgentRuntimeSocket" -}}
{{- $config := .Values.imageAnalyzer.crowdstrikeConfig -}}
{{- if $config.agentRuntimeSocket -}}
{{- $config.agentRuntimeSocket -}}
{{- else -}}
{{- get (dict
      "docker" "unix:///run/docker.sock"
      "containerd" "unix:///run/containerd/containerd.sock"
      "crio" "unix:///run/crio/crio.sock"
      "podman" "unix:///run/podman/podman.sock") ($config.agentRuntime | default "") -}}
{{- end -}}
{{- end -}}

{{/*
IAR host volume mounts for reading images from the container runtime (DaemonSet mode).
CRI-O also needs the node's container storage and configuration.
*/}}
{{- define "falcon-clusterguard.iarRuntimeVolumeMounts" -}}
- name: var-run
  mountPath: {{ include "falcon-clusterguard.iarAgentRuntimeSocket" . | trimPrefix "unix://" }}
{{- if eq .Values.imageAnalyzer.crowdstrikeConfig.agentRuntime "crio" }}
- name: storage
  mountPath: /run/containers/storage
- name: containers
  mountPath: /var/lib/containers
- name: fuse-overlay
  mountPath: /usr/bin/fuse-overlayfs
- name: crio-conf
  mountPath: /etc/containers
{{- end }}
{{- end -}}

{{/*
IAR host volumes backing iarRuntimeVolumeMounts (DaemonSet mode).
*/}}
{{- define "falcon-clusterguard.iarRuntimeVolumes" -}}
- name: var-run
  hostPath:
    path: {{ include "falcon-clusterguard.iarAgentRuntimeSocket" . | trimPrefix "unix://" }}
    type: Socket
{{- if eq .Values.imageAnalyzer.crowdstrikeConfig.agentRuntime "crio" }}
- name: storage
  hostPath:
    path: /run/containers/storage
    type: Directory
- name: containers
  hostPath:
    path: /var/lib/containers
    type: Directory
- name: crio-conf
  hostPath:
    path: /etc/containers
    type: Directory
- name: fuse-overlay
  hostPath:
    path: /usr/bin/fuse-overlayfs
    type: File
{{- end }}
{{- end -}}

{{/*
IAR container security context (DaemonSet mode). Same four keys as the standalone
falcon-image-analyzer chart, with the privileged defaults the runtime socket requires.
Unlike the standalone chart's `| default`, hasKey lets an explicit false take effect.
*/}}
{{- define "falcon-clusterguard.iarDaemonsetSecurityContext" -}}
{{- $securityContext := .Values.imageAnalyzer.securityContext | default dict -}}
privileged: {{ ternary $securityContext.privileged true (hasKey $securityContext "privileged") }}
allowPrivilegeEscalation: {{ ternary $securityContext.allowPrivilegeEscalation true (hasKey $securityContext "allowPrivilegeEscalation") }}
runAsUser: {{ ternary $securityContext.runAsUser 0 (hasKey $securityContext "runAsUser") }}
runAsGroup: {{ ternary $securityContext.runAsGroup 0 (hasKey $securityContext "runAsGroup") }}
{{- end -}}

{{/*
OpenShift createSCC for IAR — false if either chart-level or global disables it.
*/}}
{{- define "falcon-clusterguard.openshiftIARCreateSCC" -}}
{{- and .Values.openshift.createSCC .Values.global.openshift.createSCC -}}
{{- end -}}

{{/*
OpenShift SCC name for IAR. Uses openshift.iarSCCName if set, otherwise defaults to iarFullname.
*/}}
{{- define "falcon-clusterguard.iarSCCName" -}}
{{- if .Values.openshift.iarSCCName -}}
{{- .Values.openshift.iarSCCName -}}
{{- else -}}
{{- include "falcon-clusterguard.iarName" . -}}
{{- end -}}
{{- end -}}

{{/*
Validate IAR credential configuration.
The client ID, client secret, and CID must all come from the same source:
  - Helm values: imageAnalyzer.crowdstrikeConfig.clientID/clientSecret + falcon.cid
  - falconSecret: AGENT_CLIENT_ID, AGENT_CLIENT_SECRET, AGENT_CID keys in the existing secret
  - secretsStore: falcon-client-id, falcon-client-secret, falcon-cid secrets in the store
CID-in-values with falconSecret/secretsStore is rejected by validateOneOfFalconCidOrFalconSecret
and the SecretProviderClasses; this helper rejects client credentials in values with either.
*/}}
{{- define "falcon-clusterguard.validateIarCredentials" -}}
{{- $errors := list -}}

{{- /* Exactly one source supplies all IAR credentials: Helm values, falconSecret, or secretsStore. */ -}}
{{- $secretEnabled := include "falcon-clusterguard.falconSecretEnabled" . | eq "true" -}}
{{- $csiEnabled := include "falcon-clusterguard.csiEnabled" . | eq "true" -}}
{{- $hasClientId := ne (.Values.imageAnalyzer.crowdstrikeConfig.clientID | default "" | trim) "" -}}
{{- $hasClientSecret := ne (.Values.imageAnalyzer.crowdstrikeConfig.clientSecret | default "" | trim) "" -}}

{{- if or $secretEnabled $csiEnabled -}}
  {{- $source := ternary "secretsStore (falcon-client-id, falcon-client-secret, falcon-cid)" "falconSecret (AGENT_CLIENT_ID, AGENT_CLIENT_SECRET, AGENT_CID)" $csiEnabled -}}
  {{- if or $hasClientId $hasClientSecret -}}
    {{- $errors = append $errors (printf "imageAnalyzer.crowdstrikeConfig.clientID/clientSecret cannot be set when the IAR credentials come from %s" $source) -}}
  {{- end -}}
{{- else -}}
  {{- if not $hasClientId -}}
    {{- $errors = append $errors "imageAnalyzer.crowdstrikeConfig.clientID is required when falconSecret and secretsStore are not used" -}}
  {{- end -}}
  {{- if not $hasClientSecret -}}
    {{- $errors = append $errors "imageAnalyzer.crowdstrikeConfig.clientSecret is required when falconSecret and secretsStore are not used" -}}
  {{- end -}}
  {{- if not (include "falcon-clusterguard.falconCid" . | trim) -}}
    {{- $errors = append $errors "falcon.cid (or global.falcon.cid) is required when falconSecret and secretsStore are not used" -}}
  {{- end -}}
{{- end -}}

{{- if $errors -}}
{{- fail (printf "IAR credential validation failed:\n  - %s" (join "\n  - " $errors)) -}}
{{- end -}}
{{- end -}}
