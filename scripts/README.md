# migrate-to-fcg.py

Migrates a `falcon-platform` values file from the legacy `falcon-sensor` + `falcon-kac` schema
to the new `falcon-clusterguard` (FCG) schema.

## Requirements

Python 3.8+ and the `ruamel.yaml` library (0.17+):

```bash
pip3 install ruamel.yaml
```

## Usage

```bash
python3 scripts/migrate-to-fcg.py [--platform-values FILE | --sensor-values FILE] [options]
```

### Input modes (mutually exclusive)

**Umbrella chart mode** — single `falcon-platform` values file:
```bash
python3 scripts/migrate-to-fcg.py --platform-values my-platform-values.yaml
```

**Individual charts mode** — separate values files per chart:
```bash
python3 scripts/migrate-to-fcg.py \
  --sensor-values my-sensor-values.yaml \
  --kac-values my-kac-values.yaml \
  [--iar-values my-iar-values.yaml]
```

`--kac-values` and `--iar-values` are optional in individual charts mode. In individual charts
mode the values files are expected to use root-level keys (as they would be in a standalone
`helm install falcon-sensor -f my-sensor-values.yaml` invocation), not nested under subchart
name prefixes.

### Options

| Flag | Description |
|------|-------------|
| `--platform-values` | Path to `falcon-platform` umbrella values file |
| `--sensor-values` | Path to standalone `falcon-sensor` values file |
| `--kac-values` | Path to standalone `falcon-kac` values file |
| `--iar-values` | Path to standalone `falcon-image-analyzer` values file |
| `--fcg-image-repo` | FCG image repository (default: `registry.crowdstrike.com/falcon-clusterguard/release/falcon-clusterguard`) |
| `--fcg-image-tag` | FCG image tag (default: `8.14.0-12345-1`) |
| `--output` | Path for migrated output file. Defaults to `<input>.fcg-migrated.yaml` |
| `--dry-run` | Print the migrated YAML to stdout without writing any file |

## Quickstart

**1. Preview the migration without writing any files:**

```bash
# Umbrella chart mode
python3 scripts/migrate-to-fcg.py --platform-values my-values.yaml --dry-run

# Individual charts mode
python3 scripts/migrate-to-fcg.py \
  --sensor-values sensor-values.yaml \
  --kac-values kac-values.yaml \
  --dry-run
```

Review the output and any warnings printed to stderr before proceeding.

**2. Write the migrated file:**

```bash
# Umbrella chart mode (output: my-values.fcg-migrated.yaml)
python3 scripts/migrate-to-fcg.py --platform-values my-values.yaml

# Individual charts mode (output: sensor-values.fcg-migrated.yaml)
python3 scripts/migrate-to-fcg.py \
  --sensor-values sensor-values.yaml \
  --kac-values kac-values.yaml
```

**3. Diff the original against the migrated file:**

```bash
diff my-values.yaml my-values.fcg-migrated.yaml
```

**4. Apply to your cluster:**

```bash
helm upgrade falcon-platform helm-charts/falcon-platform \
  -f my-values.fcg-migrated.yaml \
  -n falcon-platform
```

## What the script does

### Moves

| Source | Destination | Notes |
|--------|-------------|-------|
| `falcon-sensor.node.*` | `falcon-clusterguard.node.*` | Copied verbatim |
| `falcon-sensor.serviceAccount.*` | `falcon-clusterguard.node.serviceAccount.*` | Moved under `node.`; old name preserved |
| `falcon-sensor.falcon.*` | `falcon-clusterguard.falcon.*` | Identical structure |
| `falcon-sensor.falconSecret.*` | `falcon-clusterguard.falconSecret.*` | Identical structure |
| `falcon-sensor.secretsStore.*` | `falcon-clusterguard.secretsStore.*` | Sensor takes precedence over kac |
| `falcon-sensor.node.openshift.*` | `falcon-clusterguard.openshift.*` | Moved to chart root |
| `falcon-sensor.node.image.pullSecrets` | `falcon-clusterguard.image.pullSecrets` | Sensor takes precedence over kac |
| `falcon-sensor.node.image.registryConfigJSON` | `falcon-clusterguard.image.registryConfigJSON` | Sensor takes precedence over kac |
| `falcon-sensor.node.image.digest` | `falcon-clusterguard.image.digest` | Sensor takes precedence over kac |
| `falcon-kac.enabled` | `falcon-clusterguard.cluster.enabled` | Controls cluster sensor Deployment |
| `falcon-kac.admissionControl.enabled` | `falcon-clusterguard.cluster.admissionControl.enabled` | Controls VWC + webhook Service; **old default was `true`, new default is `false`** — always written explicitly |
| `falcon-kac.clusterName` | `falcon-clusterguard.node.clusterName` | Moved to `node.` — shared with DaemonSet |
| `falcon-kac.tolerations` | `falcon-clusterguard.cluster.tolerations` | Moved under `cluster.` |
| `falcon-kac.webhook.*` | `falcon-clusterguard.cluster.webhook.*` | Moved under `cluster.` |
| `falcon-kac.clusterVisibility.*` | `falcon-clusterguard.clusterVisibility.*` | Identical structure |
| `falcon-kac.falconSecret.*` | `falcon-clusterguard.falconSecret.*` | Sensor value takes precedence |
| `falcon-kac.falcon.*` | `falcon-clusterguard.falcon.*` | Sensor value takes precedence |
| `falcon-kac.openshift.*` | `falcon-clusterguard.openshift.*` | Merged with sensor openshift; sensor takes precedence |
| `falcon-kac.image.pullSecrets` | `falcon-clusterguard.image.pullSecrets` | Only used if sensor image not set |
| `falcon-image-analyzer.kac.namespace` | `falcon-image-analyzer.kac.namespace` | Updated to FCG namespace automatically |
| `global.*` | `global.*` | Unchanged |

### Renames

These `falcon-kac` resource keys are renamed under `falcon-clusterguard.cluster.resources.*`:

| Old key | New key |
|---------|---------|
| `falconClientResources` | `cluster.resources.client` |
| `falconClientNoWebhookResources` | `cluster.resources.clientNoWebhook` |
| `falconWatcherResources` | `cluster.resources.watcher` |
| `falconAcResources` | `cluster.resources.admissionController` |

The migrated file adds an inline comment next to each renamed key showing its original name,
e.g. `client:  # was: falconClientResources`.

### Service account names

Service account names are carried forward from the source values to avoid breaking external RBAC.
If the source had no custom name set, the script writes the old chart defaults explicitly:

| Source default | Written to output |
|----------------|-------------------|
| `falcon-sensor`: `crowdstrike-falcon-sa` | `falcon-clusterguard.node.serviceAccount.name` |
| `falcon-kac`: `falcon-kac-sa` | `falcon-clusterguard.cluster.serviceAccount.name` |

### Image

The script always sets the canonical FCG image repository and tag:

```yaml
falcon-clusterguard:
  image:
    repository: registry.crowdstrike.com/falcon-clusterguard/release/falcon-clusterguard
    tag: "8.14.0-12345-1"
```

`pullSecrets`, `registryConfigJSON`, `digest`, and `pullPolicy` are carried over from
`falcon-sensor.node.image` (or `falcon-kac.image` if the sensor image had no value set).

### Deprecated keys

Keys that have no FCG equivalent are dropped with a warning:

| Key | Behaviour |
|-----|-----------|
| `falcon-sensor.node.backend` | Dropped entirely — FCG auto-selects eBPF/kernel |

### falcon-sensor output

- **No container mode active** — `falcon-sensor` is removed from output entirely. `falcon-platform` defaults (`enabled: false`, `node.enabled: false`) handle it.
- **Container mode active** (`container.enabled: true`) — script retains the `container.*` block and shared top-level keys; drops all `node.*` values with a comment stating node mode is no longer supported.

### falcon-kac

Fully removed from output. A comment above `falcon-clusterguard` notes the removal.

## Reading the output

**Warnings** are printed to stderr before the YAML output:

```
MIGRATION WARNINGS — review these before applying:
  ⚠  falcon-sensor.node.backend is deprecated in FCG and has been omitted. ...
```

**Inline comments** in the output file mark renamed keys:

```yaml
  resources:
    client:  # was: falconClientResources
      limits:
        memory: 384Mi
```

**Comments** above `falcon-clusterguard` note the deprecated subcharts:

```yaml
# falcon-sensor.node is deprecated — replaced by falcon-clusterguard.node.*
# falcon-kac is deprecated — replaced by falcon-clusterguard.cluster.*

falcon-clusterguard:
```

## After migration

1. **Review the full diff** before applying to a production cluster.
2. **Confirm `falcon-image-analyzer.kac.namespace`** — the script updates this automatically to match the FCG namespace.
3. **Remove deprecated keys** flagged with `DEPRECATED:` comments.

## Example

Input (`my-values.yaml`):
```yaml
global:
  falcon:
    cid: YOUR-CID-HERE

falcon-sensor:
  enabled: true
  node:
    clusterName: "my-cluster"
    daemonset:
      tolerations:
        - key: "node-role.kubernetes.io/master"
          operator: "Exists"
          effect: "NoSchedule"

falcon-kac:
  enabled: true
  clusterName: "my-cluster"
  admissionControl:
    enabled: true
  falconClientResources:
    limits:
      memory: 384Mi
    requests:
      cpu: 250m
      memory: 384Mi
  clusterVisibility:
    resourceWatcher:
      enabled: true

falcon-image-analyzer:
  enabled: true
```

Run:
```bash
python3 scripts/migrate-to-fcg.py --platform-values my-values.yaml --dry-run
```

Output (key sections):
```yaml
global:
  falcon:
    cid: YOUR-CID-HERE

# Node mode replaced by falcon-clusterguard. Enable container.enabled=true here for container sensor support.
falcon-sensor:
  enabled: false

# falcon-kac removed as a subchart dependency — replaced by falcon-clusterguard.cluster.*
falcon-clusterguard:
  enabled: true
  namespaceOverride: falcon-system
  image:
    repository: registry.crowdstrike.com/falcon-clusterguard/release/falcon-clusterguard
    tag: '8.14'
  node:
    clusterName: my-cluster
    daemonset:
      tolerations:
        - key: node-role.kubernetes.io/master
          operator: Exists
          effect: NoSchedule
    serviceAccount:
      name: crowdstrike-falcon-sa
  cluster:
    enabled: true
    admissionControl:
      enabled: true
    resources:
      client:  # was: falconClientResources
        limits:
          memory: 384Mi
        requests:
          cpu: 250m
          memory: 384Mi
    serviceAccount:
      name: falcon-kac-sa
  clusterVisibility:
    resourceWatcher:
      enabled: true

# DEPRECATED: falcon-image-analyzer will be bundled into FCG in a future version.
falcon-image-analyzer:
  enabled: true
```
