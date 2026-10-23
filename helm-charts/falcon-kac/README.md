# CrowdStrike Falcon Kubernetes Admission Controller Helm Chart

The Falcon Kubernetes Admission Controller (KAC) is a custom plugin that you can deploy to your Kubernetes cluster to
monitor and review Kubernetes objects when they are created. It’s deployed to a worker node in a cluster, and when
enabled, it listens to post-authenticated API requests from the control plane.

Admission control policies tell the Falcon KAC what to do when it observes an Indicator of Misconfiguration (IOM) on a
Kubernetes object. You can customize policies to apply to different areas of the cluster by namespace or object label.
You can configure the action that the Falcon KAC takes when it encounters a misconfiguration. It can take no action,
generate an alert, or prevent the object from being deployed.

Together, the Falcon KAC and the admission control policies provide continuous visibility and protection across your
Kubernetes cluster.

## Table of Contents
- [Getting Started](#getting-started)
  - [Helm Chart Support for Falcon Admission Controller Versions](#helm-chart-support-for-falcon-admission-controller-versions)
- [Falcon Kubernetes Admission Controller Architecture Overview](#falcon-kubernetes-admission-controller-architecture-overview)
- [Install Falcon Kubernetes Admission Controller](#install-falcon-kubernetes-admission-controller)
  - [Install Falcon KAC Helm Chart](#install-falcon-kac-helm-chart)
  - [Update Falcon KAC](#update-falcon-kac)
  - [Uninstall Falcon KAC](#uninstall-falcon-kac)
- [Configuration Options](#configuration-options)
  - [Image Configuration](#image-configuration)
  - [Falcon Configuration Options](#falcon-configuration-options)
  - [Secret Management](#secret-management)
    - [Using Existing Kubernetes Secrets](#using-existing-kubernetes-secrets)
  - [Secrets Store CSI Driver Integration](#secrets-store-csi-driver-integration)
  - [Admission Control](#admission-control)
  - [Cluster Visibility](#cluster-visibility)
  - [Webhook Configuration](#webhook-configuration)
  - [Image Analyzer Integration](#image-analyzer-integration)
  - [Networking](#networking)
  - [Certificate Management](#certificate-management)
    - [Upgrading with `autoCertificateUpdate: false`](#upgrading-with-autocertificateupdate-false)
    - [Using cert-manager](#using-cert-manager)
      - [Creating an issuer](#creating-an-issuer)
      - [Turning off cert-manager](#turning-off-cert-manager)
    - [Using Argo CD with Helm-generated certificates](#using-argo-cd-with-helm-generated-certificates)
  - [Deployment Configuration](#deployment-configuration)
  - [Resource Limits](#resource-limits)
  - [OpenShift](#openshift)

# Getting Started

To install and deploy the Falcon Kubernetes Admission Controller, your cluster environment must meet these requirements:

- Helm 3.x is installed and available in PATH
- Helm 3.x is supported by your Kubernetes distribution
- Your cluster is running on a supported x86_64, ARM64, or mixed Kubernetes environment

The Falcon Kubernetes Admission Controller has been deployed and tested on these Kubernetes distributions:

- Amazon Elastic Kubernetes Service (EKS)
- Google Kubernetes Engine (GKE)
- Microsoft Azure Kubernetes Service (AKS)

## Helm Chart Support for Falcon Admission Controller Versions

| Helm Chart Version | Falcon KAC Version | Notes                                                                                                                                                                                   |
|:-------------------|:-------------------|:----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `1.7.0`            | `>= 7.33`          | Fixes missing endpointslices permissions                                                                                                                                                |
| `1.6.0`            | `>= 7.33`          | Added KAC extended resource monitoring capabilities which require additional RBAC permissions.<br/>falcon-kac images now use a non-regionalized unified image repo, starting with 7.33. |
| `1.5.2`            | `<= 7.32`          | Added `falconImageAnalyzerNamespace` param to support communication with Falcon Image Analyzer.                                                                                         |
| `1.5.1`            | `<= 7.32`          | —                                                                                                                                                                                       |

> [!IMPORTANT]
> Falcon KAC will have multi-arch images starting with version `7.26.x`. Falcon KAC helm chart versions 1.4.x+ adds
> `arm64` to the list of allowed architectures in node affinity to support KAC deployment to ARM64 clusters.

Depending on your network environment, you might need to allow TLS traffic on port 443 between your network and our
cloud's network addresses:

| CrowdStrike cloud | Network address                                                          |
|-------------------|--------------------------------------------------------------------------|
| US-1              | ts01-b.cloudsink.net<br/>lfodown01-b.cloudsink.net                       |
| US-2              | ts01-gyr-maverick.cloudsink.net<br/>lfodown01-gyr-maverick.cloudsink.net |
| US-3              | ts01.us-3.cloudsink.net<br/>lfodown01.us-3.cloudsink.net                   |
| EU-1              | ts01-lanner-lion.cloudsink.net<br/>lfodown01-lanner-lion.cloudsink.net   |
| US-GOV-1          | ts01-laggar-gcw.cloudsink.net<br/>lfodown01-laggar-gcw.cloudsink.net     |

# Falcon Kubernetes Admission Controller Architecture Overview

The Falcon KAC runs as a pair of containers in a pod on the worker node. It listens to the Kubernetes API to monitor
Kubernetes objects. When a new object is created, the Falcon KAC evaluates the new object against the admission control
policy to identify IOMs. The admission control policy tells the Falcon KAC how to respond to new objects: do nothing,
create an alert in the Falcon console, or prevent the object from being deployed.
The Falcon KAC comprises two containers:

- **Kubernetes Client (falcon-client)**
  This is the validating webhook that is responsible for listening to events from the Kubernetes API and forwarding them
  to the admission control process.
- **Admission controller (falcon-ac)**
  This is the controller process that is responsible for admission control policy management, cloud communication, and
  event handling.

The Falcon KAC does not monitor these namespaces:

- falcon-kac
- falcon-system
- kube-system
- kube-public

# Install Falcon Kubernetes Admission Controller

- Add the Crowdstrike Falcon Helm Repository:
  ```
  helm repo add crowdstrike https://crowdstrike.github.io/falcon-helm
  ```
- Update the Falcon Helm Repository Cache
   ```
   helm repo update
   ```
- Set a variable for the Falcon KAC image repository:
   ```
   export KAC_IMAGE_REPO=<registry_name>/falcon-kac
   ```
- Set a variable for the Falcon KAC image tag:
   ```
   export KAC_IMAGE_TAG=<KAC_version>.container.x86_64.Release.<cloud_region>
   ```
  Example: The Falcon KAC image tag has this format `7.01.0-103.container.x86_64.Release.US-1`

- Set a Falcon CID variable:
   ```
   export FALCON_CID=<your_CID_with_checksum>
   ```

**Tip**: To find your CID with checksum, go to the CrowdStrike Sensor download page. At the top of the page, locate your
CID checksum, and then click **Copy your Customer ID checksum to the clipboard**.

## Install Falcon KAC Helm chart

- Install the Falcon KAC Helm chart to a new namespace:
  ```
   helm install falcon-kac crowdstrike/falcon-kac \
    -n falcon-kac --create-namespace \
    --set falcon.cid=$FALCON_CID \
    --set image.repository=$KAC_IMAGE_REPO \
    --set image.tag=$KAC_IMAGE_TAG
  ```
  **Tip**: Use the --set flag to pass individual values to the values file when running helm install. For a complete
  list and description of configurable parameters, run
  ```
  helm show values crowdstrike/falcon-kac
  ```
- Optional: Install the Falcon KAC Helm from a private registry that requires authentication:If your registry requires
  authentication, you must create a Kubernetes secret that can fetch the image from the registry.
    - Log into your Docker registry.
    - Fetch the base64 encoded pull secret:
      ```
       cat ~/.docker/config.json | base64 -w 0
      ```
    - Save the base64 string as a variable for the pull secret:
      ```
       export IMAGE_PULL_TOKEN=<base64_encoded_string>
      ```

  ```
   helm install falcon-kac crowdstrike/falcon-kac \
      -n falcon-kac --create-namespace \
      --set falcon.cid=$FALCON_CID \
      --set image.repository=$KAC_IMAGE_REPO \
      --set image.tag=$KAC_IMAGE_TAG \
      --set image.registryConfigJSON=$IMAGE_PULL_TOKEN
    ```

## OpenShift Compatibility

> **Note:** OpenShift is **not a recommended** configuration for this Helm chart. The
> [official Red Hat certified CrowdStrike Falcon Operator](https://catalog.redhat.com/en/software/container-stacks/detail/62f2d38f76d039249424703d)
> is the recommended installation method for OpenShift clusters.

In the default configuration, all containers run as non-root with no privilege escalation and no host access, which
satisfies the built-in `restricted-v2` SCC without any additional configuration.

### Security Context Constraints

If `hostNetwork` must be enabled (required when a custom CNI prevents control plane nodes from communicating directly
with pods), a custom SCC that permits host network access is required. The chart can create this SCC automatically.

The SCC is managed as a standard Helm release resource and will be created on install and removed on uninstall.

**Helm User Permissions:** When `openshift.createSCC: true`, the user or service account running Helm must have
permission to create, update, and delete `SecurityContextConstraints` resources at the cluster level.

To use an existing SCC instead, set `openshift.createSCC=false`, define `openshift.sccName` with the name of your SCC,
and ensure the SCC is created prior to deployment. The SCC must be bound to the service account manually before
installing.

For a full list of OpenShift configuration parameters, see [OpenShift](#openshift) under Falcon Configuration Options.

## Update Falcon KAC

When a new container image is available, you can update your Falcon KAC by passing the new container image to the Helm
chart and then running a `helm upgrade` command. In general, Helm charts do not support auto-updating running resources.
Falcon KAC does not support auto-update. You must manually update the Falcon KAC on your cluster or update through a
GitOps or CI/CD pipeline per Kubernetes Best Operational and Security practices.

- Set a new variable for the Falcon KAC container image tag:
  ```
  export KAC_IMAGE_TAG=<KAC_version>.container.x86_64.Release.<cloud_region>
  ```

- Update your Helm chart with the new container image:
  ```
    helm upgrade --install falcon-kac $KAC_HELM_REPO \
       -n falcon-kac --create-namespace \
       --set falcon.cid=$FALCON_CID \
       --set image.repository=$KAC_IMAGE_REPO \
       --set image.tag=$KAC_IMAGE_TAG
  ```
  **Note**: Your deployment will update only when you change the inputs for helm upgrade, for example by changing the
  image reference.

### Adding clusterName to an Existing Deployment

If you are adding a `clusterName` value to an existing Falcon KAC deployment where it was not previously set, you must first delete the `falcon-kac-meta` ConfigMap before running `helm upgrade`:

```
kubectl delete configmap falcon-kac-meta -n falcon-kac
```

Then proceed with the helm upgrade command including the `--set clusterName=<your-cluster-name>` parameter. This is necessary because Helm cannot take ownership of resources that were not originally created by the Helm release.

- Verify that the new version of the Falcon KAC is running on the falcon-kac pods:
  ```
  kubectl get pods -n falcon-kac -o jsonpath='{range .items[*]}{"\n"}{.metadata.name}{":\t"}{range .spec.containers[*]}{.image}{", "}{end}{end}'
  ```

  The output looks similar to the example below and shows that version
  falcon-kac:7.01.0-103.container.x86_64.Release.US-1 is running on both Falcon KAC pods.
   ```
   falcon-kac-5bd6986f6f-x86vw: falcon-kac:7.01.0-103.container.x86_64.Release.US-1, falcon-kac:7.01.0-103.container.x86_64.Release.US-1,
   ```

## Uninstall Falcon KAC

- Uninstall the admission controller from the falcon-kac namespace:
  ```
  helm uninstall falcon-kac -n falcon-kac
  ```
  <br/>
- Delete the namespace:
  ```
  kubectl delete ns falcon-kac
  ```

# Configuration Options

The following sections list all configurable Falcon KAC parameters grouped by function.

## Image Configuration

Settings that control which container image is pulled and how it is authenticated.

| Parameter                  | Description                                                                                                  | Default       |
|:---------------------------|:-------------------------------------------------------------------------------------------------------------|:--------------|
| `image.repository`         | Container image repository                                                                                   | `falcon-kac`  |
| `image.tag`                | Image tag. Prefer `image.digest` for immutability; this field is provided for legacy compatibility.          | `latest`      |
| `image.digest`             | Image digest (`sha256:...`). Overrides `image.tag` when set.                                                 | None          |
| `image.pullPolicy`         | Kubernetes image pull policy                                                                                 | `Always`      |
| `image.pullSecrets`        | List of existing Kubernetes image pull secret names                                                          | None          |
| `image.registryConfigJSON` | Base64-encoded Docker `config.json` used to create an image pull secret. Conflicts with `image.pullSecrets`. | None          |

## Falcon Configuration Options

Core sensor identity and connectivity settings passed to `falconctl`.

| Parameter                   | Description                                          | Default                                            |
|:----------------------------|:-----------------------------------------------------|:---------------------------------------------------|
| `falcon.cid`                | CrowdStrike Customer ID (CID)                        | None (required if `falconSecret.enabled` is false) |
| `falcon.apd`                | App Proxy Disable (APD)                              | None                                               |
| `falcon.aph`                | App Proxy Hostname (APH)                             | None                                               |
| `falcon.app`                | App Proxy Port (APP)                                 | None                                               |
| `falcon.trace`              | Trace level (`none`, `err`, `warn`, `info`, `debug`) | `none`                                             |
| `falcon.feature`            | Sensor feature options                               | None                                               |
| `falcon.billing`            | Billing mode (`default` or `metered`)                | None                                               |
| `falcon.tags`               | Comma-separated list of tags for sensor grouping     | None                                               |
| `falcon.provisioning_token` | Provisioning token value                             | None                                               |
| `clusterName`               | Manually set cluster name when auto-discovery fails. | None (auto-discovery used)                         |

## Secret Management

Options for supplying sensitive Falcon values (CID, etc.) via a Kubernetes Secret instead of plain values.

| Parameter                 | Description                                                                                                            | Default |
|:--------------------------|:-----------------------------------------------------------------------------------------------------------------------|:--------|
| `falconSecret.enabled`    | Use an existing Kubernetes secret to supply sensitive Falcon values. Must be `true` when `falcon.cid` is not set.      | `false` |
| `falconSecret.secretName` | Name of the existing secret. Must be in the same namespace as the KAC deployment and must contain `FALCONCTL_OPT_CID`. | None    |

### Using Existing Kubernetes Secrets

Instead of specifying the CID directly in Helm values, you can use an existing Kubernetes secret.

The secret must be in the same namespace as the KAC deployment and must contain the following keys:
- `FALCONCTL_OPT_CID`: Falcon Customer ID (CID) — required
- `FALCONCTL_OPT_PROVISIONING_TOKEN`: Falcon provisioning token — optional

Create the namespace and secret before installing:

```bash
kubectl create namespace falcon-kac

kubectl create secret generic $FALCON_SECRET_NAME -n falcon-kac \
  --from-literal=FALCONCTL_OPT_CID=$FALCON_CID
```

Then reference the secret during installation:

```bash
helm install falcon-kac crowdstrike/falcon-kac \
  -n falcon-kac --create-namespace \
  --set falconSecret.enabled=true \
  --set falconSecret.secretName=$FALCON_SECRET_NAME \
  --set image.repository=$KAC_IMAGE_REPO \
  --set image.tag=$KAC_IMAGE_TAG
```

> [!NOTE]
> When `falconSecret.enabled` is `true`, `falcon.cid` must not be set. These are mutually exclusive.

## Secrets Store CSI Driver Integration

The chart supports sourcing `FALCONCTL_OPT_CID` (and optionally `FALCONCTL_OPT_PROVISIONING_TOKEN`) from external secret stores via the [Secrets Store CSI Driver](https://secrets-store-csi-driver.sigs.k8s.io/). Supported providers include:
- [Azure Key Vault](https://azure.microsoft.com/en-us/products/key-vault) via the [Azure Key Vault provider](https://azure.github.io/secrets-store-csi-driver-provider-azure/)

### Configuration Parameters

| Parameter                                       | Description                                                                                                                                                                                        | Default              |
|:------------------------------------------------|:---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:---------------------|
| `secretsStore.enabled`                          | Enable Secrets Store CSI Driver integration. Mutually exclusive with `falcon.cid` and `falconSecret.enabled`.                                                                                      | `false`              |
| `secretsStore.provider`                         | Secrets Store CSI Driver provider (`azure`)                                                                                                                                                        | None                 |
| `secretsStore.secretName`                       | Name of the Kubernetes secret created by the CSI driver to sync secrets into. Defaults to `<release-fullname>-csi` if empty.                                                                       | None                 |
| `secretsStore.azure.vaultName`                  | Azure Key Vault name                                                                                                                                                                               | None                 |
| `secretsStore.azure.tenantID`                   | Azure Tenant ID                                                                                                                                                                                    | None                 |
| `secretsStore.azure.clientID`                   | Azure Workload Identity client ID. Only required if multiple managed identities are assigned to the node.                                                                                          | None                 |
| `secretsStore.provisioningTokenSecretName`      | Name of the secrets store secret containing `FALCONCTL_OPT_PROVISIONING_TOKEN`. Leave empty to omit.                                                                                              | None                 |

### Prerequisites

**For Azure Key Vault:**

The following must be installed and configured on your AKS cluster before enabling this feature:

- [Secrets Store CSI Driver](https://secrets-store-csi-driver.sigs.k8s.io/getting-started/installation)
- [Azure Key Vault Provider for Secrets Store CSI Driver](https://azure.github.io/secrets-store-csi-driver-provider-azure/docs/getting-started/installation/)
- [Azure Workload Identity](https://azure.github.io/azure-workload-identity/docs/installation.html) webhook installed on the cluster
- AKS cluster with OIDC issuer enabled (`az aks update --enable-oidc-issuer --name <cluster> --resource-group <rg>`)
- A user-assigned managed identity with `Key Vault Secrets User` role on the vault
- A federated credential binding the managed identity to the chart's ServiceAccount in the KAC namespace

### Required secrets in Azure Key Vault

Create the following secrets in your Azure Key Vault before enabling the integration:

| Secret name (default)       | Required | Value                          |
|:----------------------------|:---------|:-------------------------------|
| `falcon-cid`                | Yes      | CrowdStrike Customer ID (CID)  |
| `falcon-provisioning-token` | No       | Provisioning token             |

The CID secret must be named `falcon-cid` in the secrets store. The provisioning token secret name is configurable via `secretsStore.provisioningTokenSecretName`.

### Configuration

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
  provisioningTokenSecretName: ""  # leave empty to omit

serviceAccount:
  annotations:
    azure.workload.identity/client-id: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# Add the Workload Identity label to KAC pods
labels:
  azure.workload.identity/use: "true"
```

> [!NOTE]
> `secretsStore.enabled` cannot be combined with `falcon.cid` or `falconSecret.enabled`. These are mutually exclusive secret sources.

## Admission Control

Controls whether the KAC operates as a validating admission webhook.

| Parameter                  | Description                                                                                        | Default |
|:---------------------------|:---------------------------------------------------------------------------------------------------|:--------|
| `admissionControl.enabled` | Enable admission control. When false, KAC does not validate workloads or detect misconfigurations. | `true`  |

## Webhook Configuration

Fine-grained controls for the Kubernetes ValidatingWebhookConfiguration.

| Parameter                   | Description                                                                                              | Default  |
|:----------------------------|:---------------------------------------------------------------------------------------------------------|:---------|
| `webhook.failurePolicy`     | Webhook failure policy (`Ignore` or `Fail`). `Ignore` allows workloads to proceed if KAC is unavailable. | `Ignore` |
| `webhook.disableNamespaces` | Comma-separated list of namespaces excluded from webhook validation (e.g., `test1,test2`)                | None     |

## Cluster Visibility

Configures how KAC monitors and reports Kubernetes cluster state to CrowdStrike cloud.

| Parameter                                      | Description                                                                                                     | Default |
|:-----------------------------------------------|:----------------------------------------------------------------------------------------------------------------|:--------|
| `clusterVisibility.resourceSnapshots.enabled`  | Create snapshots of Kubernetes resources. Disabling may cause long-lived resources to disappear from Falcon UI. | `true`  |
| `clusterVisibility.resourceSnapshots.interval` | Interval between snapshots. Maximum is `22h`; minimum is `30m`. Format: `HHhMMm` (e.g., `12h`, `45m`, `1h30m`). | `22h`   |
| `clusterVisibility.resourceWatcher.enabled`    | Watch the cluster for resource events. Disabling means Falcon UI reflects only the last snapshot state.         | `true`  |
| `clusterVisibility.resourceConfigMap.enabled`  | Watch ConfigMap events. KAC redacts sensitive data. Set to false to exclude ConfigMaps from cluster visibility. | `true`  |

## Image Analyzer Integration

Parameters for integrating KAC with other CrowdStrike components deployed in the same cluster.

| Parameter                      | Description                                                                                    | Default                 |
|:-------------------------------|:-----------------------------------------------------------------------------------------------|:------------------------|
| `falconImageAnalyzerNamespace` | Namespace where the Falcon Image Analyzer is deployed. Used for cross-component communication. | `falcon-image-analyzer` |

## Networking

Controls network identity and connectivity for the KAC pod.

| Parameter     | Description                                                                                                            | Default |
|:--------------|:-----------------------------------------------------------------------------------------------------------------------|:--------|
| `hostNetwork` | Run the KAC pod in host network mode. Required when a custom CNI prevents control-plane-to-pod communication.          | `false` |
| `dnsPolicy`   | Pod DNS policy. Defaults to `ClusterFirstWithHostNet` when `hostNetwork` is `true`; otherwise follows cluster default. | None    |
| `domainName`  | Custom DNS domain suffix for in-cluster service resolution (e.g., `testing.io` if `svc.testing.io` is required).       | None    |
| `webhookPort` | Port on which the validating webhook backend listens                                                                   | `4443`  |
| `watcherPort` | Port on which the resource watcher listens                                                                             | `4080`  |

## Certificate Management

Settings for the TLS certificate used by the validating webhook. The certificate is stored in the
Secret `<name>-tls` (`falcon-kac-tls` by default) and mounted into the `falcon-client` container.
It comes from one of two sources:

- **Helm-generated (default):** Helm creates a CA and a server certificate on every install and,
  when `autoCertificateUpdate` is `true`, on every upgrade.
- **cert-manager:** set `certManager.enabled=true` and `certManager.issuerRef`. cert-manager issues
  the certificate and renews it, and its cainjector fills the webhook `caBundle`.

| Parameter               | Description                                                                                                                                                                                     | Default |
|:------------------------|:------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:--------|
| `autoCertificateUpdate` | Regenerate the Helm-generated certificate on each Helm upgrade. When `false`, the existing certificate, key, and CA are reused together. Ignored with cert-manager. Has no effect with Argo CD. | `true`  |
| `certExpiration`        | Certificate validity period in days. Also sets the cert-manager `Certificate` duration.                                                                                                         | `3650`  |
| `certManager.enabled`   | Use cert-manager to issue the webhook certificate.                                                                                                                                              | `false` |
| `certManager.issuerRef` | cert-manager issuer for the certificate (`name`, `kind`, `group`). `name` is required when `certManager.enabled`.                                                                               | `{}`    |

### Upgrading with `autoCertificateUpdate: false`

Chart versions before cert-manager support regenerated the CA on every upgrade even when
`autoCertificateUpdate` was `false`, so the reused certificate no longer matched the webhook `caBundle`.
This version reuses the certificate, key, and CA together, which keeps an existing mismatch in place.
If you used `autoCertificateUpdate: false`, run one upgrade with `autoCertificateUpdate: true` (or delete
the `<name>-tls` Secret first) to generate a matching set, then set it back to `false`.

### Using cert-manager

Requires [cert-manager](https://cert-manager.io/), including its cainjector, and an issuer that can
issue certificates for in-cluster service names, such as a CA or self-signed `ClusterIssuer`. See
[Creating an issuer](#creating-an-issuer) for examples. Then set:

```yaml
certManager:
  enabled: true
  issuerRef:
    name: falcon-ca-issuer
    kind: ClusterIssuer
```

A namespaced `Issuer` must be in the KAC namespace. cert-manager renews the certificate after two-thirds
of `certExpiration` has passed, about 6.7 years with the default of `3650` days.

#### Creating an issuer

KAC loads its certificate at startup and doesn't reload it, so use a CA issuer. Its CA stays the same
when cert-manager issues a new certificate, so the webhook `caBundle` doesn't change and a running KAC
pod stays trusted until its certificate expires.

A CA `ClusterIssuer`, bootstrapped from a self-signed issuer. The CA `Certificate` must be in the
cert-manager namespace (`cert-manager` by default), where a `ClusterIssuer` reads its Secret:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: selfsigned-cluster-issuer
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: falcon-root-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: falcon-root-ca
  secretName: falcon-root-ca
  duration: 87600h
  issuerRef:
    name: selfsigned-cluster-issuer
    kind: ClusterIssuer
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: falcon-ca-issuer
spec:
  ca:
    secretName: falcon-root-ca
```

```bash
kubectl apply -f falcon-ca-issuer.yaml
kubectl wait --for=condition=Ready clusterissuer/falcon-ca-issuer --timeout=2m
```

A self-signed `ClusterIssuer` alone (`selfsigned-cluster-issuer` above, with
`certManager.issuerRef.name: selfsigned-cluster-issuer`) also works, but every certificate it issues is
its own CA. Each new certificate, whether from renewal or from changing `certManager.issuerRef`,
`certExpiration`, or `domainName`, changes the webhook `caBundle` right away. Until KAC is restarted
with `kubectl rollout restart deployment/falcon-kac -n falcon-kac`, the API server can't verify the
webhook, and with `webhook.failurePolicy: Ignore`, admission checks are skipped.

To keep the issuer in the KAC namespace instead, create the same resources as `kind: Issuer` in that
namespace, with the CA `Certificate` there too, and set `certManager.issuerRef.kind: Issuer`.

#### Turning off cert-manager

cert-manager does not delete the `<name>-tls` Secret when its `Certificate` is deleted, and Helm cannot
take ownership of a Secret that was not created by the Helm release. Upgrading with
`certManager.enabled=false` while that Secret exists fails with an error like:

```
Error: UPGRADE FAILED: Unable to continue with update: Secret "falcon-kac-tls" in namespace "falcon-kac" exists and cannot be imported into the current release: invalid ownership metadata
```

Delete the `Certificate` first, then the Secret, then upgrade with `certManager.enabled=false`:

```bash
kubectl delete certificate falcon-kac-tls -n falcon-kac
kubectl delete secret falcon-kac-tls -n falcon-kac
helm upgrade falcon-kac crowdstrike/falcon-kac -n falcon-kac -f config-values.yaml --set certManager.enabled=false
```

- Delete the `Certificate` before the Secret. If the Secret is deleted first, cert-manager issues a new
  one right away.
- If cert-manager runs with `--enable-certificate-owner-ref`, deleting the `Certificate` also deletes
  the Secret, and the second command reports that the Secret is not found.
- Run the commands together. Running KAC pods keep serving the certificate they already loaded, but a
  KAC pod that starts before the upgrade can't mount the Secret and stays in `ContainerCreating` until
  the upgrade creates it.
- The upgrade creates a Helm-generated certificate and sets the webhook `caBundle` to its CA. With
  `autoDeploymentUpdate: true` (the default), the upgrade also restarts KAC so it loads the new
  certificate. With `autoDeploymentUpdate: false`, restart it right after the upgrade with
  `kubectl rollout restart deployment/falcon-kac -n falcon-kac`; until then, the API server can't verify
  the webhook, and with `webhook.failurePolicy: Ignore`, admission checks are skipped.
- When installed through the `falcon-platform` chart, use the `falcon-kac.namespaceOverride` namespace
  and set `falcon-kac.certManager.enabled=false`.

### Using Argo CD with Helm-generated certificates

Argo CD renders the chart with `helm template` and applies the result; it does not run `helm install`
or `helm upgrade`. `helm template` can't read the cluster, so with Helm-generated certificates the chart
creates a new CA and certificate on every render, and `autoCertificateUpdate: false` has no effect
because the chart can't read the existing Secret. Without the settings below, the application shows
as `OutOfSync` on every refresh, and every sync replaces the certificate.

Ignore the certificate fields with `ignoreDifferences`, and set `RespectIgnoreDifferences=true` so a sync keeps the certificate
already in the cluster.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: falcon-kac
  namespace: argocd
spec:
  # source, destination, and project omitted
  ignoreDifferences:
    - kind: Secret
      name: falcon-kac-tls
      namespace: falcon-kac
      jsonPointers:
        - /data
    - group: admissionregistration.k8s.io
      kind: ValidatingWebhookConfiguration
      name: validating.falcon-kac.crowdstrike.com
      jqPathExpressions:
        - .webhooks[]?.clientConfig.caBundle
  syncPolicy:
    syncOptions:
      - RespectIgnoreDifferences=true
```

Also set `autoDeploymentUpdate: false`. When `true`, the chart adds a random pod annotation on every
render to restart the pods on `helm upgrade`, so Argo CD sees a change on every refresh and restarts KAC
on every sync. Configuration changes still restart the pods, through the `checksum/configmap`
annotation. If the Application also deploys IAR, add its entries too; see the [falcon-image-analyzer
README](../falcon-image-analyzer/README.md#using-argo-cd-with-helm-generated-certificates).

```yaml
autoDeploymentUpdate: false
```

- Ignore the Secret and the webhook `caBundle` together. If only one is kept, a sync pairs a new
  certificate with the old CA (or the reverse), the API server can't verify the webhook, and with
  `webhook.failurePolicy: Ignore`, admission checks are skipped.
- The Secret is `<name>-tls` (`falcon-kac-tls` by default) in the KAC namespace. The
  ValidatingWebhookConfiguration is always `validating.falcon-kac.crowdstrike.com`. When installing
  through the `falcon-platform` chart, use the `falcon-kac.namespaceOverride` namespace, set
  `autoDeploymentUpdate` under `falcon-kac`, and add these entries to the `falcon-platform` Application.
- The certificate from the first sync is kept and is not renewed; it's valid for `certExpiration` days.
  To replace it, delete the `<name>-tls` Secret and the ValidatingWebhookConfiguration together, then
  sync. Deleting only one leaves a certificate and `caBundle` that don't match.

cert-manager doesn't need `ignoreDifferences`: the chart renders the same manifests every time, and
cert-manager and its cainjector manage the Secret and the webhook `caBundle` outside Argo CD.

## Deployment Configuration

Controls pod scheduling, labeling, and overall deployment behavior.

| Parameter                    | Description                                                                                 | Default                       |
|:-----------------------------|:--------------------------------------------------------------------------------------------|:------------------------------|
| `replicas`                   | Number of KAC deployment replicas                                                           | `1`                           |
| `autoDeploymentUpdate`       | Roll out a new Deployment automatically on `helm upgrade`. Set to `false` with Argo CD.     | `true`                        |
| `annotations`                | Annotations applied to the Deployment resource                                              | `{}`                          |
| `labels`                     | Additional labels applied to the Deployment resource                                        | `{}`                          |
| `podAnnotations`             | Annotations applied to KAC pods                                                             | `{}`                          |
| `tolerations`                | Pod tolerations for node scheduling                                                         | `[]`                          |
| `affinity`                   | Pod affinity/anti-affinity rules. Defaults to require `amd64` or `arm64` node architecture. | `nodeAffinity` (amd64, arm64) |
| `serviceAccount.name`        | Name of the Kubernetes ServiceAccount used by the KAC pod                                   | `falcon-kac-sa`               |
| `serviceAccount.annotations` | Annotations applied to the ServiceAccount (e.g., for IRSA or Workload Identity)             | `{}`                          |
| `resourceQuota.pods`         | Maximum number of pods allowed by the ResourceQuota object created for the KAC namespace    | `2`                           |
| `nameOverride`               | Override the chart name component of generated resource names                               | `""`                          |
| `fullnameOverride`           | Override the full generated resource name prefix                                            | `""`                          |

## Resource Limits

CPU and memory resource requests and limits for each KAC container. Review actual consumption in your environment and adjust accordingly.

| Parameter                                        | Description                                                           | Default |
|:-------------------------------------------------|:----------------------------------------------------------------------|:--------|
| `falconClientResources.requests.cpu`             | CPU request for the `falcon-client` (webhook) container               | `250m`  |
| `falconClientResources.requests.memory`          | Memory request for the `falcon-client` (webhook) container            | `384Mi` |
| `falconClientResources.limits.memory`            | Memory limit for the `falcon-client` (webhook) container              | `384Mi` |
| `falconClientNoWebhookResources.requests.cpu`    | CPU request for `falcon-client` when admission control is disabled    | `100m`  |
| `falconClientNoWebhookResources.requests.memory` | Memory request for `falcon-client` when admission control is disabled | `128Mi` |
| `falconClientNoWebhookResources.limits.memory`   | Memory limit for `falcon-client` when admission control is disabled   | `128Mi` |
| `falconWatcherResources.requests.cpu`            | CPU request for the resource watcher container                        | `250m`  |
| `falconWatcherResources.requests.memory`         | Memory request for the resource watcher container                     | `512Mi` |
| `falconWatcherResources.limits.memory`           | Memory limit for the resource watcher container                       | `512Mi` |
| `falconAcResources.requests.cpu`                 | CPU request for the `falcon-ac` (admission controller) container      | `100m`  |
| `falconAcResources.requests.memory`              | Memory request for the `falcon-ac` (admission controller) container   | `256Mi` |
| `falconAcResources.limits.memory`                | Memory limit for the `falcon-ac` (admission controller) container     | `256Mi` |

## OpenShift

> **Note:** OpenShift is **not a recommended** configuration. The [official Red Hat certified CrowdStrike Falcon Operator](https://catalog.redhat.com/en/software/container-stacks/detail/62f2d38f76d039249424703d) is the recommended installation method for OpenShift clusters.

| Parameter             | Description                                                                                                 | Default               |
|:----------------------|:------------------------------------------------------------------------------------------------------------|:----------------------|
| `openshift.enabled`   | Enable OpenShift compatibility mode                                                                         | `false`               |
| `openshift.createSCC` | Create a `SecurityContextConstraints` resource granting the Deployment service account host network access. | `true`                |
| `openshift.sccName`   | Name of the SCC to create or bind. Set `createSCC: false` and provide a name to reference an existing SCC.  | `""` (auto-generated) |
