# CrowdStrike Falcon Cluster Guard Helm Chart

[Falcon](https://www.crowdstrike.com/) is the [CrowdStrike](https://www.crowdstrike.com/)
platform purpose-built to stop breaches via a unified set of cloud-delivered technologies
that prevent all types of attacks — including malware and much more.

Falcon Cluster Guard (FCG) is a unified Kubernetes security service that replaces the
separate `falcon-sensor` (node mode) and `falcon-kac` charts with a single deployment
built around a single container image.

## Table of Contents

- [What is FCG?](#what-is-fcg)
- [Migrating from falcon-sensor and falcon-kac](#migrating-from-falcon-sensor-and-falcon-kac)
- [Kubernetes Cluster Compatibility](#kubernetes-cluster-compatibility)
- [Dependencies](#dependencies)
  - [Helm Chart Support for FCG Versions](#helm-chart-support-for-fcg-versions)
- [Installation](#installation)
- [Image Configuration](#image-configuration)
- [Falcon Configuration Options](#falcon-configuration-options)
  - [Using Existing Kubernetes Secrets](#using-existing-kubernetes-secrets)
  - [Secrets Store CSI Driver Integration](#secrets-store-csi-driver-integration)
- [Node Sensor Configuration](#node-sensor-configuration)
  - [Deployment Considerations](#deployment-considerations)
  - [Sensor Uninstall and Maintenance Protection](#sensor-uninstall-and-maintenance-protection)
  - [Pod Security Standards](#pod-security-standards)
  - [Node Configuration](#node-configuration)
  - [GKE Autopilot Configuration](#gke-autopilot-configuration)
- [Cluster Sensor Configuration](#cluster-sensor-configuration)
  - [Cluster Sensor and Admission Control](#cluster-sensor-and-admission-control)
  - [Cluster Visibility](#cluster-visibility)
  - [Webhook Configuration](#webhook-configuration)
  - [Certificate Management](#certificate-management)
  - [Resource Limits](#resource-limits)
- [OpenShift Compatibility](#openshift-compatibility)
- [Uninstall Helm Chart](#uninstall-helm-chart)
- [Troubleshooting](#troubleshooting)

## What is FCG?

FCG replaces the separate `falcon-sensor` (node-only) and `falcon-kac` charts with a
unified installer built around a single container image. FCG provides:

- **Node-level protection**: eBPF/kernel-based sensor deployed as a DaemonSet on every cluster node
- **Cluster sensor**: central gRPC metadata service that supplies Kubernetes context to node sensors, eliminating the scalability bottleneck of each sensor querying the API server directly
- **Admission control**: optional ValidatingWebhookConfiguration that inspects Kubernetes API requests
- **Resource visibility**: periodic snapshots + live event watchers for cluster-wide resource discovery

> **Note:** FCG does not currently support container sidecar injection. If you need the
> Falcon Container sensor (sidecar mode), continue using the `falcon-sensor` chart with
> `container.enabled=true`.

## Migrating from falcon-sensor and falcon-kac

If you are currently using `falcon-sensor` (node mode) and/or `falcon-kac`, use the
migration script to generate a new values file:

```bash
# From individual chart values files
python3 scripts/migrate-to-fcg.py \
  --sensor-values my-sensor-values.yaml \
  --kac-values my-kac-values.yaml

# From a falcon-platform umbrella values file
python3 scripts/migrate-to-fcg.py --platform-values my-platform-values.yaml

# Interactive guided wizard
python3 scripts/migrate-to-fcg.py --interactive
```

See `scripts/README.md` for full documentation.

Key differences from the legacy charts:

| Behavior                           | falcon-sensor + falcon-kac           | falcon-clusterguard                  |
|:-----------------------------------|:-------------------------------------|:-------------------------------------|
| Container images                   | Separate per chart                   | Single unified image                 |
| Node sensor                        | `falcon-sensor` chart                | `node.*` values                      |
| Admission controller               | `falcon-kac` chart                   | `cluster.admissionControl.*` values  |
| `admissionControl.enabled` default | `true`                               | **`false`**                          |
| Container sidecar sensor           | Supported (`container.enabled=true`) | Not supported — use `falcon-sensor`  |
| gRPC metadata service              | Not available                        | Built-in (always enabled)            |

## Kubernetes Cluster Compatibility

FCG has been tested on the following Kubernetes distributions:

- Amazon Elastic Kubernetes Service (EKS)
- Azure Kubernetes Service (AKS)
- Google Kubernetes Engine (GKE), including GKE Autopilot
- Rancher K3s

> **OpenShift:** OpenShift is **not a recommended** configuration for this Helm chart. The
> [official Red Hat certified CrowdStrike Falcon Operator](https://catalog.redhat.com/en/software/container-stacks/detail/62f2d38f76d039249424703d)
> is the recommended installation method for OpenShift clusters. A best-effort
> compatibility mode is available (see [OpenShift Compatibility](#openshift-compatibility) below).

## Dependencies

1. Requires an x86_64 or ARM64 Kubernetes cluster
1. Must be a CrowdStrike customer with access to the Falcon Cluster Guard image from the CrowdStrike Container Registry
1. Kubernetes nodes must be Linux distributions supported by CrowdStrike
1. Before deploying, ensure the FCG image is available in a registry accessible to your cluster
1. Helm 3.x is installed and supported by your Kubernetes vendor

### Helm Chart Support for FCG Versions

| Helm Chart Version | FCG Sensor Version | Notes                                                    |
|:-------------------|:-------------------|:---------------------------------------------------------|
| `1.0.0`            | `>= 8.14`          | Initial release — unified node sensor and cluster sensor |

## Installation

### Add the CrowdStrike Falcon Helm repository

```bash
helm repo add crowdstrike https://crowdstrike.github.io/falcon-helm
helm repo update
```

### Minimal install (node sensor + cluster sensor)

```bash
helm upgrade --install falcon-clusterguard crowdstrike/falcon-clusterguard \
  -n falcon-system --create-namespace \
  --set falcon.cid="<CrowdStrike_CID>" \
  --set image.registryConfigJSON="<YOUR_BASE64_ENCODED_DOCKER_CONFIG_JSON>"
```

### Full install (node sensor + cluster sensor + admission control)

```yaml
# falcon-clusterguard-values.yaml
image:
  repository: registry.crowdstrike.com/falcon-clusterguard/release/falcon-clusterguard
  digest: sha256:ffdc91f66ef8570bd7612cf19145563a787f552656f5eec43cd80ef9caca0398
  pullSecrets: crowdstrike-pull-secret

falcon:
  cid: "<CrowdStrike_CID>"
  trace: info
  billing: default

node:
  enabled: true
  clusterName: "my-cluster"   # required for self-hosted K8s; auto-discovered on EKS/GKE/AKS
  daemonset:
    updateStrategy: RollingUpdate

cluster:
  admissionControl:
    enabled: true             # default is false — set true to enable the webhook
  webhook:
    failurePolicy: Ignore
  replicas: 1

clusterVisibility:
  resourceSnapshots:
    enabled: true
    interval: 22h
  resourceWatcher:
    enabled: true
```

```bash
helm upgrade --install falcon-clusterguard crowdstrike/falcon-clusterguard \
  -n falcon-system --create-namespace \
  -f falcon-clusterguard-values.yaml
```

For a complete listing of configurable parameters:

```bash
helm show values crowdstrike/falcon-clusterguard
```

## Image Configuration

A single FCG container image is used by both the node sensor DaemonSet and the cluster
sensor Deployment.

| Parameter                  | Description                                                                                                          |
|:---------------------------|:---------------------------------------------------------------------------------------------------------------------|
| `image.repository`         | FCG container image repository (Default: `registry.crowdstrike.com/falcon-clusterguard/release/falcon-clusterguard`) |
| `image.tag`                | Image tag. Prefer `image.digest` for immutability. (Default: `8.14.0-XXXXX-1`)                                       |
| `image.digest`             | Image digest (`sha256:...`). Overrides `image.tag` when set.                                                         |
| `image.pullPolicy`         | Kubernetes image pull policy (Default: `Always`)                                                                     |
| `image.pullSecrets`        | Name of an existing docker-registry Secret (comma-separated for multiple)                                            |
| `image.registryConfigJSON` | Base64-encoded Docker `config.json`. Conflicts with `image.pullSecrets`.                                             |

## Falcon Configuration Options

The following table lists the Falcon sensor options shared by both the node sensor and
the cluster sensor. These are passed to `falconctl` as `FALCONCTL_OPT_*` environment
variables in both the node and cluster sensor ConfigMaps.

> [!NOTE]
> `falcon.cid` and `falcon.provisioning_token` are handled separately via the
> `falconSecret` mechanism and are not written as plain `FALCONCTL_OPT_*` env vars
> when `falconSecret.enabled=true`.

| Parameter                   | Description                                                                       | Default |
|:----------------------------|:----------------------------------------------------------------------------------|:--------|
| `falcon.cid`                | CrowdStrike Customer ID (CID). Required unless `falconSecret.enabled=true`.       | None    |
| `falcon.cloud`              | CrowdStrike cloud region (`us-1`, `us-2`, `us-3`, `eu-1`, `us-gov-1`, `us-gov-2`) | None    |
| `falcon.apd`                | App Proxy Disable (APD)                                                           | None    |
| `falcon.aph`                | App Proxy Hostname (APH)                                                          | None    |
| `falcon.app`                | App Proxy Port (APP)                                                              | None    |
| `falcon.trace`              | Set trace level (`none`, `err`, `warn`, `info`, `debug`)                          | `none`  |
| `falcon.feature`            | Sensor feature options                                                            | None    |
| `falcon.billing`            | Billing mode (`default` or `metered`)                                             | None    |
| `falcon.tags`               | Comma-separated list of tags for sensor grouping                                  | None    |
| `falcon.provisioning_token` | Provisioning token value. Not supported when `falconSecret.enabled=true`.         | None    |

### Using Existing Kubernetes Secrets

Instead of specifying sensitive values directly in Helm values, you can use an existing
Kubernetes secret to supply the Falcon CID and provisioning token.

The secret must be in the same namespace as the FCG deployment and must contain:
- `FALCONCTL_OPT_CID`: Falcon Customer ID (CID) — required
- `FALCONCTL_OPT_PROVISIONING_TOKEN`: Falcon provisioning token — optional

> [!NOTE]
> `falcon.trace` and other `falcon.*` options are **not** sourced from `falconSecret` —
> they must still be set as Helm values. Only `cid` and `provisioning_token` are
> supplied via the secret.

Create the namespace and secret before installing:

```bash
kubectl create namespace falcon-system

kubectl create secret generic $FALCON_SECRET_NAME -n falcon-system \
  --from-literal=FALCONCTL_OPT_CID=$FALCON_CID \
  --from-literal=FALCONCTL_OPT_PROVISIONING_TOKEN=$FALCON_PROVISIONING_TOKEN
```

Then reference the secret during installation:

```bash
helm install falcon-clusterguard crowdstrike/falcon-clusterguard \
  -n falcon-system --create-namespace \
  --set falconSecret.enabled=true \
  --set falconSecret.secretName=$FALCON_SECRET_NAME \
  --set image.repository="<Your_Registry>/falcon-clusterguard"
```

| Parameter                 | Description                                                                                                 | Default |
|:--------------------------|:------------------------------------------------------------------------------------------------------------|:--------|
| `falconSecret.enabled`    | Use an existing Kubernetes secret for sensitive Falcon values. Must be `true` when `falcon.cid` is not set. | `false` |
| `falconSecret.secretName` | Name of the secret. Must be in the same namespace as FCG and must contain `FALCONCTL_OPT_CID`.              | None    |

> [!NOTE]
> When `falconSecret.enabled` is `true`, `falcon.cid` must not be set. These are mutually exclusive.

### Secrets Store CSI Driver Integration

The chart supports sourcing `FALCONCTL_OPT_CID` (and optionally
`FALCONCTL_OPT_PROVISIONING_TOKEN`) from external secret stores via the
[Secrets Store CSI Driver](https://secrets-store-csi-driver.sigs.k8s.io/). The supported
provider is:
- [Azure Key Vault](https://azure.microsoft.com/en-us/products/key-vault) via the [Azure Key Vault provider](https://azure.github.io/secrets-store-csi-driver-provider-azure/)

#### Configuration Parameters

| Parameter                      | Description                                                                                               | Default |
|:-------------------------------|:----------------------------------------------------------------------------------------------------------|:--------|
| `secretsStore.enabled`         | Enable Secrets Store CSI Driver integration.                                                              | `false` |
| `secretsStore.provider`        | Secrets Store CSI Driver provider (`azure`)                                                               | None    |
| `secretsStore.secretName`      | Name of the Kubernetes secret created by the CSI driver. Defaults to `<release-fullname>-csi` if empty.   | None    |
| `secretsStore.azure.vaultName` | Azure Key Vault name                                                                                      | None    |
| `secretsStore.azure.tenantID`  | Azure Tenant ID                                                                                           | None    |
| `secretsStore.azure.clientID`  | Azure Workload Identity client ID. Only required if multiple managed identities are assigned to the node. | None    |

> [!NOTE]
> `secretsStore.enabled` cannot be combined with `falcon.cid` or `falconSecret.enabled`. These are mutually exclusive secret sources.

#### Prerequisites

**For Azure Key Vault:**

The following must be installed and configured on your AKS cluster before enabling this feature:

- [Secrets Store CSI Driver](https://secrets-store-csi-driver.sigs.k8s.io/getting-started/installation)
- [Azure Key Vault Provider for Secrets Store CSI Driver](https://azure.github.io/secrets-store-csi-driver-provider-azure/docs/getting-started/installation/)
- [Azure Workload Identity](https://azure.github.io/azure-workload-identity/docs/installation.html) webhook installed on the cluster
- AKS cluster with OIDC issuer enabled (`az aks update --enable-oidc-issuer --name <cluster> --resource-group <rg>`)
- A user-assigned managed identity with `Key Vault Secrets User` role on the vault
- A federated credential binding the managed identity to the chart's ServiceAccount

#### Required secrets in Azure Key Vault

| Secret name (default)       | Required | Value                         |
|:----------------------------|:---------|:------------------------------|
| `falcon-cid`                | Yes      | CrowdStrike Customer ID (CID) |
| `falcon-provisioning-token` | No       | Provisioning token            |

#### Configuration

**Azure Key Vault example:**

```yaml
secretsStore:
  enabled: true
  provider: azure
  azure:
    vaultName: "my-keyvault"
    tenantID: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    # clientID is optional - only required if multiple managed identities are assigned
    clientID: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

node:
  serviceAccount:
    annotations:
      azure.workload.identity/client-id: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  podLabels:
    azure.workload.identity/use: "true"
```

## Node Sensor Configuration

### Deployment Considerations

To ensure a successful deployment:

1. The FCG node sensor runs as a privileged DaemonSet. Best practice is to use a dedicated namespace such as `falcon-system`.
1. You must be a cluster administrator to deploy Helm Charts to the cluster.
1. The Falcon Linux Sensor requires privileged access so that it can properly interact with the kernel. This is a requirement for any kernel module deployed to a container-optimized OS.
1. The FCG node sensor creates `/opt/CrowdStrike` on Kubernetes nodes. **Do not delete this directory.**
1. CrowdStrike's Helm Chart is a project, not a product, released to the community as a way to automate sensor deployment to Kubernetes clusters. The upstream repository is [https://github.com/CrowdStrike/falcon-helm](https://github.com/CrowdStrike/falcon-helm).

### Sensor Uninstall and Maintenance Protection

- **Falcon Node sensor for Linux with sensor version 7.33 and earlier:** We do not recommend enabling the **Uninstall and maintenance protection** policy setting for DaemonSet deployments. This setting can cause operational issues that require manual intervention.
- **Falcon Node sensor for Linux with sensor version 7.34 and later:** DaemonSet deployments do not support the **Uninstall and maintenance protection** policy setting and automatically ignore it.

### Pod Security Standards

Starting with Kubernetes 1.25, Pod Security Standards are enforced. Apply the required `privileged` labels to the install namespace:

```bash
kubectl label --overwrite ns falcon-system \
  pod-security.kubernetes.io/enforce=privileged

# Optionally silence warnings and adjust auditing:
kubectl label --overwrite ns falcon-system \
  pod-security.kubernetes.io/audit=privileged \
  pod-security.kubernetes.io/warn=privileged
```

In automated testing environments, set `testing.labelNamespace: true` to apply these labels automatically via a pre-install Job. This requires outbound access to `docker.io` and is not suitable for air-gapped or registry-restricted environments.

### Node Configuration

The following table lists the configurable parameters for the FCG node sensor DaemonSet.

| Parameter                            | Description                                                                                                                  | Default                                          |
|:-------------------------------------|:-----------------------------------------------------------------------------------------------------------------------------|:-------------------------------------------------|
| `node.enabled`                       | Enable the node sensor DaemonSet                                                                                             | `true`                                           |
| `node.clusterName`                   | Manually set cluster name. Usually auto-discovered on managed Kubernetes (EKS, GKE, AKS). Required for self-hosted clusters. | None (auto-discovery used)                       |
| `node.serviceAccount.name`           | Name of the Kubernetes ServiceAccount used by the node sensor DaemonSet and cleanup DaemonSet                                | `falcon-node-sensor-sa`                          |
| `node.serviceAccount.annotations`    | Annotations applied to the ServiceAccount (e.g., for IRSA or Workload Identity)                                              | `{}`                                             |
| `node.gke.autopilot`                 | Enable for GKE Autopilot clusters                                                                                            | `false`                                          |
| `node.daemonset.annotations`         | Annotations applied to the DaemonSet resource                                                                                | `{}`                                             |
| `node.daemonset.labels`              | Additional labels applied to the DaemonSet resource                                                                          | `{}`                                             |
| `node.daemonset.podAnnotationKey`    | Annotation key used to control per-pod/per-node sensor injection                                                             | `sensor.falcon-system.crowdstrike.com/injection` |
| `node.daemonset.priorityClassCreate` | Create a PriorityClass for the node sensor pods                                                                              | `false`                                          |
| `node.daemonset.priorityClassName`   | Assign an existing PriorityClass name to node sensor pods                                                                    | `""`                                             |
| `node.daemonset.priorityClassValue`  | Priority value when `priorityClassCreate` is true                                                                            | `1000000000`                                     |
| `node.daemonset.tolerations`         | Pod tolerations for node scheduling. Defaults include master, control-plane, and Azure spot nodes.                           | See `values.yaml`                                |
| `node.daemonset.nodeAffinity`        | Node affinity rules for the DaemonSet                                                                                        | `{}`                                             |
| `node.daemonset.resources`           | CPU and memory resource requests and limits. Minimum: 250m CPU, 500Mi memory. GKE Autopilot default: 750m CPU, 1.5Gi memory. | None                                             |
| `node.daemonset.updateStrategy`      | DaemonSet update strategy                                                                                                    | `RollingUpdate`                                  |
| `node.daemonset.maxUnavailable`      | Maximum number of unavailable nodes during a rolling update                                                                  | `1`                                              |
| `node.podAnnotations`                | Annotations applied to node sensor pods                                                                                      | `{}`                                             |
| `node.podLabels`                     | Additional labels applied to node sensor pods. Note: may affect WorkloadAllowlists on GKE Autopilot.                         | `{}`                                             |
| `node.terminationGracePeriod`        | Seconds to wait for node sensor pods to stop gracefully                                                                      | `60`                                             |
| `node.hooks.postDelete.enabled`      | Run a cleanup DaemonSet during `helm uninstall` to remove `/opt/CrowdStrike` from all nodes                                  | `true`                                           |
| `node.cleanupOnly`                   | Run the cleanup DaemonSet only (skip the main sensor DaemonSet). Requires `node.hooks.postDelete.enabled: true`.             | `false`                                          |

### GKE Autopilot Configuration

Running DaemonSet pods with privileged access on GKE Autopilot requires configuring an
AllowlistSynchronizer. This resource applies CrowdStrike-specific WorkloadAllowlists to
your cluster, which the GKE Autopilot validating webhook uses to approve pod deployments
based on their manifest spec and image digests.

1. Create a file named `allowlist-synchronizer.yaml`:

```yaml
apiVersion: auto.gke.io/v1
kind: AllowlistSynchronizer
metadata:
  name: crowdstrike-synchronizer
spec:
  allowlistPaths:
  - CrowdStrike/falcon-sensor/*
```

2. Apply it to your cluster:

```bash
kubectl apply -f allowlist-synchronizer.yaml
```

3. Confirm the AllowlistSynchronizer is running:

```bash
kubectl get allowlistsynchronizers
```

4. Confirm the WorkloadAllowlists have been fetched:

```bash
kubectl get workloadallowlists
```

Example output:

```
NAME                                                  AGE
crowdstrike-falconsensor-cleanup-allowlist-v1.0.0     7d
crowdstrike-falconsensor-deploy-allowlist-v1.0.1      7d
crowdstrike-falconsensor-falconctl-allowlist-v1.0.0   7d
```

#### WorkloadAllowlist definitions

- `crowdstrike-falconsensor-cleanup-allowlist-vX.X.X`: Authorizes the cleanup DaemonSet
- `crowdstrike-falconsensor-deploy-allowlist-vX.X.X`: Authorizes the sensor DaemonSet
- `crowdstrike-falconsensor-falconctl-allowlist-vX.X.X`: Authorizes the falconctl Job

> [!NOTE]
> Additional information: [https://cloud.google.com/kubernetes-engine/docs/reference/crds/allowlistsynchronizer](https://cloud.google.com/kubernetes-engine/docs/reference/crds/allowlistsynchronizer)

#### Obtaining an authorized image

WorkloadAllowlists validate container images by digest. To view approved digests:

```bash
kubectl get workloadallowlists <crowdstrike-falconsensor-XXXXXXX-allowlist-vX.X.X> \
  -o=jsonpath='{range .containerImageDigests[*].imageDigests[*]}{@}{"\n"}{end}'
```

To copy an image to a private registry while preserving its digest, use a tool like
[Skopeo](https://github.com/containers/skopeo):

```bash
skopeo copy \
  docker://registry.crowdstrike.com/falcon-clusterguard/release/falcon-clusterguard:<TAG> \
  docker://my-registry.company.com/falcon-clusterguard:<TAG>
```

#### Falcon Secret usage with GKE Autopilot

When using `falconSecret` with GKE Autopilot, `falconSecret.secretName` must be
`"falcon-node-sensor-secret"`. Any other secret name is disallowed by GKE Autopilot.

## Cluster Sensor Configuration

### Cluster Sensor and Admission Control

FCG has two independent feature gates for the cluster sensor:

- **`cluster.admissionControl.enabled`**: controls only the ValidatingWebhookConfiguration and webhook Service. The cluster sensor runs in visibility-only mode by default.
- **`cluster.imageAnalyzer.enabled`**: controls only Image Assessment with Image Analyzer. This is disabled by default.

> **Important:** The FCG default for `cluster.admissionControl.enabled` is `false`, whereas
> the old `falcon-kac` default was `true`. If you are migrating from `falcon-kac`, you must
> explicitly set `cluster.admissionControl.enabled=true` to preserve admission control behavior.

| Parameter                            | Description                                                                                                                             | Default                       |
|:-------------------------------------|:----------------------------------------------------------------------------------------------------------------------------------------|:------------------------------|
| `cluster.admissionControl.enabled`   | Enable the ValidatingWebhookConfiguration and webhook Service.                                                                          | `false`                       |
| `cluster.serviceAccount.name`        | Name of the Kubernetes ServiceAccount used by the cluster sensor Deployment                                                             | `falcon-cluster-sensor-sa`    |
| `cluster.serviceAccount.annotations` | Annotations applied to the cluster sensor ServiceAccount (e.g., for IRSA or Workload Identity)                                          | `{}`                          |
| `cluster.replicas`                   | Number of cluster sensor replicas. The metadata service is single-instance; keep at `1` unless you understand the implications.         | `1`                           |
| `cluster.resourceQuota.pods`         | Maximum pods allowed by the ResourceQuota scoped to the cluster sensor namespace                                                        | `2`                           |
| `cluster.hostNetwork`                | Run cluster sensor in host network mode. Required when a custom CNI prevents control plane nodes from communicating directly with pods. | `false`                       |
| `cluster.webhookPort`                | HTTPS port on which the validating webhook backend listens                                                                              | `4443`                        |
| `cluster.watcherPort`                | HTTP port on which the resource watcher listens (internal)                                                                              | `4080`                        |
| `cluster.dnsPolicy`                  | Pod DNS policy. Defaults to `ClusterFirstWithHostNet` when `hostNetwork=true`; otherwise follows cluster default.                       | None                          |
| `cluster.domainName`                 | Custom DNS domain suffix for in-cluster service resolution (e.g., `testing.io` if `svc.testing.io` is required).                        | None                          |
| `cluster.tlsVersionMinimum`          | Minimum TLS version accepted by the webhook (`TLS1.2` or `TLS1.3`)                                                                      | None                          |
| `cluster.autoDeploymentUpdate`       | Roll out a new Deployment automatically on `helm upgrade`                                                                               | `true`                        |
| `cluster.annotations`                | Annotations applied to the cluster sensor Deployment resource                                                                           | `{}`                          |
| `cluster.labels`                     | Additional labels applied to the cluster sensor Deployment resource                                                                     | `{}`                          |
| `cluster.podAnnotations`             | Annotations applied to cluster sensor pods                                                                                              | `{}`                          |
| `cluster.podLabels`                  | Additional labels applied to cluster sensor pods                                                                                        | `{}`                          |
| `cluster.tolerations`                | Pod tolerations for node scheduling                                                                                                     | `[]`                          |
| `cluster.affinity`                   | Pod affinity/anti-affinity rules. Defaults to require `amd64` or `arm64` node architecture.                                             | `nodeAffinity` (amd64, arm64) |

### Cluster Visibility

Controls how FCG monitors and reports Kubernetes cluster state to CrowdStrike cloud.

| Parameter                                      | Description                                                                                                                           | Default                 |
|:-----------------------------------------------|:--------------------------------------------------------------------------------------------------------------------------------------|:------------------------|
| `clusterVisibility.resourceSnapshots.enabled`  | Periodic snapshots of Kubernetes resources. Disabling may cause long-lived resources to disappear from Falcon UI after ~7 days.       | `true`                  |
| `clusterVisibility.resourceSnapshots.interval` | Interval between snapshots. Maximum `22h`, minimum `30m`. Format: `HHhMMm` (e.g., `12h`, `45m`, `1h30m`).                             | `22h`                   |
| `clusterVisibility.resourceWatcher.enabled`    | Continuously watch cluster for resource create/update/delete events. Disabling means Falcon UI reflects only the last snapshot state. | `true`                  |
| `clusterVisibility.resourceConfigMap.enabled`  | Watch ConfigMap events. FCG redacts known sensitive patterns before sending. Set to `false` to exclude ConfigMaps from visibility.    | `true`                  |
| `falconImageAnalyzerNamespace`                 | Namespace where Falcon Image Analyzer is deployed, used for cross-component communication.                                            | `falcon-image-analyzer` |

### Webhook Configuration

| Parameter                           | Description                                                                                              | Default  |
|:------------------------------------|:---------------------------------------------------------------------------------------------------------|:---------|
| `cluster.webhook.failurePolicy`     | Webhook failure policy (`Ignore` or `Fail`). `Ignore` allows workloads to proceed if FCG is unavailable. | `Ignore` |
| `cluster.webhook.disableNamespaces` | Comma-separated list of namespaces excluded from webhook validation (e.g., `test1,test2`)                | None     |

### Certificate Management

FCG uses mTLS between the node sensor and the cluster sensor gRPC API, and a separate TLS
certificate for the admission webhook. Certificates can be managed by Helm (default) or
by cert-manager.

| Parameter                       | Description                                                                                                                          | Default |
|:--------------------------------|:-------------------------------------------------------------------------------------------------------------------------------------|:--------|
| `cluster.autoCertificateUpdate` | Automatically rotate TLS certificates on each `helm upgrade`. Set to `false` to preserve existing certs across upgrades.             | `true`  |
| `cluster.certExpiration`        | Certificate validity period in days                                                                                                  | `3650`  |
| `cluster.certManager.enabled`   | Use cert-manager to issue gRPC mTLS certificates instead of Helm-generated self-signed certs. Requires cert-manager to be installed. | `false` |
| `cluster.certManager.issuerRef` | cert-manager `Issuer` or `ClusterIssuer` reference. Required when `certManager.enabled=true`.                                        | `{}`    |

**cert-manager example:**

```yaml
cluster:
  certManager:
    enabled: true
    issuerRef:
      name: selfsigned-cluster-issuer
      kind: ClusterIssuer
```

### Resource Limits

CPU and memory resource requests and limits for each cluster sensor container.

| Parameter                                               | Description                                                           | Default |
|:--------------------------------------------------------|:----------------------------------------------------------------------|:--------|
| `cluster.resources.client.requests.cpu`                 | CPU request for the `falcon-client` (webhook receiver) container      | `250m`  |
| `cluster.resources.client.requests.memory`              | Memory request for the `falcon-client` container                      | `384Mi` |
| `cluster.resources.client.limits.memory`                | Memory limit for the `falcon-client` container                        | `384Mi` |
| `cluster.resources.clientNoWebhook.requests.cpu`        | CPU request for `falcon-client` when admission control is disabled    | `100m`  |
| `cluster.resources.clientNoWebhook.requests.memory`     | Memory request for `falcon-client` when admission control is disabled | `128Mi` |
| `cluster.resources.clientNoWebhook.limits.memory`       | Memory limit for `falcon-client` when admission control is disabled   | `128Mi` |
| `cluster.resources.watcher.requests.cpu`                | CPU request for the `falcon-watcher` (K8s event streamer) container   | `250m`  |
| `cluster.resources.watcher.requests.memory`             | Memory request for the `falcon-watcher` container                     | `512Mi` |
| `cluster.resources.watcher.limits.memory`               | Memory limit for the `falcon-watcher` container                       | `512Mi` |
| `cluster.resources.admissionController.requests.cpu`    | CPU request for the `falcon-ac` (admission controller) container      | `100m`  |
| `cluster.resources.admissionController.requests.memory` | Memory request for the `falcon-ac` container                          | `256Mi` |
| `cluster.resources.admissionController.limits.memory`   | Memory limit for the `falcon-ac` container                            | `256Mi` |

## OpenShift Compatibility

> **Note:** OpenShift is **not a recommended** configuration for this Helm chart. The
> [official Red Hat certified CrowdStrike Falcon Operator](https://catalog.redhat.com/en/software/container-stacks/detail/62f2d38f76d039249424703d)
> is the recommended installation method for OpenShift clusters.

This chart provides a best-effort compatibility mode for deploying FCG on OpenShift clusters.

### Security Context Constraints

OpenShift uses Security Context Constraints (SCC) to control pod privileges. FCG requires
two separate SCCs:

- **Node sensor SCC**: grants privileged host access (`hostPID`, `hostIPC`, `hostNetwork`,
  and a privileged container) required by the node DaemonSet
- **Admission SCC**: grants host network access required by the cluster sensor when
  `cluster.hostNetwork=true`

When `openshift.enabled=true` and `openshift.createSCC=true`, the chart creates both SCCs
and binds them to the appropriate service accounts automatically.

**Helm User Permissions:** When `openshift.createSCC: true`, the user or service account
running Helm must have permission to create, update, and delete `SecurityContextConstraints`
resources at the cluster level.

To use existing SCCs instead, set `openshift.createSCC=false` and provide names via
`openshift.nodeSCCName` and `openshift.admissionSCCName`. The SCCs must be created and
bound to the service accounts before installing.

OpenShift runs Pod Security Admission in warn/audit mode alongside SCCs. To suppress PSA warnings:

```bash
kubectl label namespace falcon-system \
  pod-security.kubernetes.io/enforce=privileged \
  pod-security.kubernetes.io/warn=privileged \
  pod-security.kubernetes.io/audit=privileged
```

### OpenShift Values

| Parameter                    | Description                                                                                                                  | Default               |
|:-----------------------------|:-----------------------------------------------------------------------------------------------------------------------------|:----------------------|
| `openshift.enabled`          | Enable OpenShift compatibility mode                                                                                          | `false`               |
| `openshift.createSCC`        | Create SCCs for the node sensor and cluster sensor (when `cluster.hostNetwork=true`) and bind them to their service accounts | `true`                |
| `openshift.nodeSCCName`      | Name of the node sensor SCC. Defaults to `<release-fullname>-node-sensor`                                                    | `""` (auto-generated) |
| `openshift.admissionSCCName` | Name of the cluster sensor SCC. Defaults to `<release-fullname>-admission`                                                   | `""` (auto-generated) |

### Installing on OpenShift

```bash
helm upgrade --install falcon-clusterguard crowdstrike/falcon-clusterguard \
  -n falcon-system --create-namespace \
  --set falcon.cid="<CrowdStrike_CID>" \
  --set image.repository="<Your_Registry>/falcon-clusterguard" \
  --set image.tag="<FCG_VERSION>" \
  --set openshift.enabled=true
```

## Uninstall Helm Chart

```bash
helm uninstall falcon-clusterguard -n falcon-system
```

You may also want to delete the namespace:

```bash
kubectl delete ns falcon-system
```

## Troubleshooting

### Node Sensor Cleanup DaemonSet Fails

After uninstall, the cleanup DaemonSet removes `/opt/CrowdStrike` from all nodes. If it fails,
you can run the cleanup manually:

```bash
helm install falcon-clusterguard crowdstrike/falcon-clusterguard \
  -n falcon-system \
  --set image.repository="<Your_Registry>/falcon-clusterguard" \
  --set image.tag="<FCG_VERSION>" \
  --set node.enabled=true \
  --set node.cleanupOnly=true
```

Validate removal:

```bash
for node in $(kubectl get nodes -o name); do
  echo -n "$node: "
  kubectl debug $node -it --image=busybox -- /bin/sh -c \
    'if test -d /opt/CrowdStrike; then echo "CrowdStrike directory still exists"; else echo "CrowdStrike directory successfully deleted"; fi'
done
```

Then uninstall the cleanup release:

```bash
helm uninstall falcon-clusterguard -n falcon-system
```

### Admission Webhook Not Receiving Requests

Ensure `cluster.admissionControl.enabled=true`. The cluster sensor Deployment can run
without a webhook (visibility-only mode) — the webhook is disabled by default.

Check that the ValidatingWebhookConfiguration exists:

```bash
kubectl get validatingwebhookconfiguration | grep falcon
```

If it is missing, upgrade with `cluster.admissionControl.enabled=true`.
