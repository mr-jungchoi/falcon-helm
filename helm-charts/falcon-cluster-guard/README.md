# Falcon Cluster Guard Helm Chart

Helm chart to deploy CrowdStrike Falcon Cluster Guard (FCG) — a unified Kubernetes security service that combines the Falcon node sensor and the Kubernetes admission controller into a single deployment.

## What is FCG?

FCG replaces the separate `falcon-sensor` (node-only) and `falcon-kac` (admission controller) charts with a unified installer built around a single container image. FCG provides:

- **Node-level protection**: eBPF/kernel-based sensor deployed as a DaemonSet on every cluster node
- **Admission control**: optional ValidatingWebhookConfiguration that inspects K8s API server requests
- **Cluster metadata service**: central gRPC service that supplies K8s context to node sensors — eliminates the scalability bottleneck of N sensors querying the K8s API server directly
- **Resource visibility**: periodic snapshots + event watchers for cluster-wide resource discovery

## Prerequisites

- Kubernetes 1.22+
- Helm 3.x
- Access to the CrowdStrike registry (or a local mirror)
- A CrowdStrike Customer ID (CID) or an existing Secret containing `FALCONCTL_OPT_CID`

## Quick Start

```bash
helm install falcon-cluster-guard \
  --create-namespace \
  --namespace falcon-system \
  --set falcon.cid=<YOUR-CID> \
  --set image.repository=<REGISTRY>/falcon-cluster-guard \
  --set image.tag=<VERSION> \
  ./falcon-cluster-guard
```

## Key Configuration Options

| Value                                         | Default                | Purpose                                                                      |
|-----------------------------------------------|------------------------|------------------------------------------------------------------------------|
| `image.repository`                            | `falcon-cluster-guard` | Unified FCG container image (used by both node sensor and admission control) |
| `image.tag`                                   | `latest`               | Image tag (prefer `image.digest` for immutability)                           |
| `node.enabled`                                | `true`                 | Deploy the node sensor DaemonSet                                             |
| `node.backend`                                | `bpf`                  | Sensor backend: `kernel` or `bpf`                                            |
| `admission.enabled`                           | `true`                 | Deploy admission controller + webhook                                        |
| `admission.webhook.failurePolicy`             | `Ignore`               | `Ignore` or `Fail` on webhook errors                                         |
| `clusterVisibility.resourceSnapshots.enabled` | `true`                 | Periodic K8s resource snapshots                                              |
| `clusterVisibility.resourceWatcher.enabled`   | `true`                 | Live K8s event stream                                                        |
| `falcon.cid`                                  | _(required)_           | CrowdStrike Customer ID                                                      |
| `falconSecret.enabled`                        | `false`                | Use existing Secret instead of inline `falcon.cid`                           |

See `values.yaml` for the complete list.

## Differences from Legacy Charts

FCG does **not** provide an in-place upgrade path from `falcon-sensor` or `falcon-kac`. Deploy FCG to a new namespace and uninstall the legacy charts once FCG is validated.

Notable differences:

- **Unified image**: single image for node + admission workloads (no separate `node.image` / `container.image`).
- **No container sidecar mode**: FCG is DaemonSet-based. If you need injected sidecars, keep using `falcon-sensor` container mode.
- **Optional admission control**: `admission.enabled: false` renders only the node DaemonSet.
- **Central metadata service**: node sensors no longer query the K8s API server directly.

## Uninstalling

```bash
helm uninstall falcon-cluster-guard --namespace falcon-system
```

The post-delete cleanup DaemonSet (enabled by default via `node.hooks.postDelete.enabled`) will run a final teardown before resources are removed.
