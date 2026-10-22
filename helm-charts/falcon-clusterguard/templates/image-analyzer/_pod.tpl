{{/*
IAR pod template shared by the watcher Deployment and the socket-mode DaemonSet.
Mode differences: container securityContext, -runmode argument, and the container runtime
host volumes, which are only added in DaemonSet mode.
*/}}
{{- define "falcon-clusterguard.iarPodTemplate" -}}
{{- $imageAnalyzer := .Values.imageAnalyzer }}
{{- $isDaemonset := include "falcon-clusterguard.iarDaemonsetEnabled" . | eq "true" }}
{{- $imagePullSecret := include "falcon-clusterguard.imagePullSecret" . }}
{{- $registryConfigJson := include "falcon-clusterguard.registryConfigJson" . }}
metadata:
  annotations:
    sensor.falcon-system.crowdstrike.com/injection: disabled
    {{- if include "falcon-clusterguard.openshiftEnabled" . | eq "true" }}
    openshift.io/scc: {{ include "falcon-clusterguard.iarSCCName" . }}
    {{- end }}
    {{- with $imageAnalyzer.podAnnotations }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
    checksum/config: {{ include (print $.Template.BasePath "/image-analyzer/configmap.yaml") . | sha256sum }}
    checksum/secret: {{ include (print $.Template.BasePath "/image-analyzer/secret.yaml") . | sha256sum }}
  labels:
    {{- include "falcon-clusterguard.iarLabels" . | nindent 4 }}
    {{- with $imageAnalyzer.podLabels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  {{- if or $imagePullSecret $registryConfigJson }}
  imagePullSecrets:
    {{- if $imagePullSecret }}
    - name: {{ $imagePullSecret }}
    {{- end }}
    {{- if $registryConfigJson }}
    - name: {{ include "falcon-clusterguard.pullSecretName" . }}
    {{- end }}
  {{- end }}
  serviceAccountName: {{ include "falcon-clusterguard.iarServiceAccountName" . }}
  securityContext:
  {{- if $imageAnalyzer.podSecurityContext }}
  {{- toYaml $imageAnalyzer.podSecurityContext | nindent 4 }}
  {{- end }}
  {{- if .Values.gke.enabled }}
  initContainers:
    - name: {{ include "falcon-clusterguard.iarName" . }}-init-container
      image: "gcr.io/google.com/cloudsdktool/google-cloud-cli:alpine"
      imagePullPolicy: "Always"
      command:
        - '/bin/bash'
        - '-c'
        - |
          curl -sS -H 'Metadata-Flavor: Google' 'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token' --retry 30 --retry-connrefused --retry-max-time 60 --connect-timeout 3 --fail --retry-all-errors > /dev/null && exit 0 || echo 'Retry limit exceeded. Failed to wait for metadata server to be available. Check if the gke-metadata-server Pod in the kube-system namespace is healthy.' >&2; exit 1
      securityContext:
        runAsUser: 0
        runAsNonRoot: false
        privileged: false
      {{- if not $isDaemonset }}
        allowPrivilegeEscalation: false
        seccompProfile:
          type: RuntimeDefault
      {{- end }}
  {{- end }}
  containers:
    - name: {{ include "falcon-clusterguard.iarName" . }}
      securityContext:
      {{- if $isDaemonset }}
        {{- include "falcon-clusterguard.iarDaemonsetSecurityContext" . | nindent 8 }}
      {{- else }}
        runAsUser: 0
        privileged: false
        allowPrivilegeEscalation: false
        capabilities:
          drop:
            - ALL
        seccompProfile:
          type: RuntimeDefault
      {{- end }}
      resources:
      {{- if $imageAnalyzer.resources }}
        {{- toYaml $imageAnalyzer.resources | nindent 8 }}
      {{- end }}
      image: {{ include "falcon-clusterguard.image" . }}
      imagePullPolicy: {{ .Values.image.pullPolicy }}
      args: ["-runmode", {{ ternary "socket" "watcher" $isDaemonset | quote }}]
      ports:
      - containerPort: {{ $imageAnalyzer.iarAgentService.httpPort }}
        name: service-port
      env:
        - name: POD_NODE_NAME
          valueFrom:
            fieldRef:
              fieldPath: spec.nodeName
        - name: POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: POD_NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        - name: POD_IP
          valueFrom:
            fieldRef:
              fieldPath: status.podIP
        - name: POD_NODE_IP
          valueFrom:
            fieldRef:
              fieldPath: status.hostIP
        - name: HELM_CHART
          valueFrom:
            fieldRef:
              fieldPath: metadata.labels['helm.sh/chart']
      {{- if include "falcon-clusterguard.csiEnabled" . | eq "true" }}
        - name: AGENT_CLIENT_ID
          valueFrom:
            secretKeyRef:
              name: {{ include "falcon-clusterguard.iarCsiSecretName" . }}
              key: AGENT_CLIENT_ID
              optional: true
        - name: AGENT_CLIENT_SECRET
          valueFrom:
            secretKeyRef:
              name: {{ include "falcon-clusterguard.iarCsiSecretName" . }}
              key: AGENT_CLIENT_SECRET
              optional: true
        - name: AGENT_CID
          valueFrom:
            secretKeyRef:
              name: {{ include "falcon-clusterguard.iarCsiSecretName" . }}
              key: AGENT_CID
              optional: true
      {{- end }}
      envFrom:
        - configMapRef:
            name: {{ include "falcon-clusterguard.iarName" . }}
        {{- if include "falcon-clusterguard.iarShouldCreateClientCredsInSecret" . | trim | eq "true" }}
        - secretRef:
            name: {{ include "falcon-clusterguard.iarName" . }}
        {{- end }}
        {{- if and (include "falcon-clusterguard.falconSecretEnabled" . | eq "true") (not (include "falcon-clusterguard.csiEnabled" . | eq "true")) }}
        - secretRef:
            name: {{ include "falcon-clusterguard.falconSecretName" . }}
        {{- end }}
      volumeMounts:
      {{- toYaml $imageAnalyzer.volumeMounts | default "" | nindent 8 }}
      {{- if $isDaemonset }}
      {{- include "falcon-clusterguard.iarRuntimeVolumeMounts" . | nindent 8 }}
      {{- end }}
      {{- if .Values.azure.enabled }}
        - name: azure-config
          mountPath: /etc/kubernetes/azure.json
      {{- end }}
      {{- if include "falcon-clusterguard.csiEnabled" . | eq "true" }}
        - name: csi-secrets
          mountPath: /mnt/secrets-store
          readOnly: true
      {{- end }}
        - mountPath: /run/secrets/tls
          name: {{ include "falcon-clusterguard.iarName" . }}-tls-certs
          readOnly: true
  {{- with $imageAnalyzer.nodeSelector }}
  nodeSelector:
  {{- toYaml . | nindent 4 }}
  {{- end }}
  volumes:
    {{- toYaml $imageAnalyzer.volumes | default "" | nindent 4 }}
    {{- if $isDaemonset }}
    {{- include "falcon-clusterguard.iarRuntimeVolumes" . | nindent 4 }}
    {{- end }}
    {{- if .Values.azure.enabled }}
    - name: azure-config
      hostPath:
        path: {{ .Values.azure.azureConfig }}
        type: File
    {{- end }}
    {{- if include "falcon-clusterguard.csiEnabled" . | eq "true" }}
    - name: csi-secrets
      csi:
        driver: secrets-store.csi.k8s.io
        readOnly: true
        volumeAttributes:
          secretProviderClass: {{ include "falcon-clusterguard.iarName" . }}-csi
    {{- end }}
    - name: {{ include "falcon-clusterguard.iarName" . }}-tls-certs
      secret:
        secretName: {{ include "falcon-clusterguard.iarName" . }}-tls
  {{- with $imageAnalyzer.affinity }}
  affinity:
  {{- toYaml . | nindent 4 }}
  {{- end }}
  {{- with $imageAnalyzer.tolerations }}
  tolerations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  {{- if $imageAnalyzer.priorityClassName }}
  priorityClassName: {{ $imageAnalyzer.priorityClassName }}
  {{- end }}
  {{- if $imageAnalyzer.hostNetwork }}
  hostNetwork: true
  dnsPolicy: {{ default "ClusterFirstWithHostNet" $imageAnalyzer.dnsPolicy }}
  {{- else if $imageAnalyzer.dnsPolicy }}
  dnsPolicy: {{ $imageAnalyzer.dnsPolicy }}
  {{- end }}
{{- end -}}
