# migrate-to-fcg.py

Migrates a `falcon-platform` values file from the legacy `falcon-sensor` + `falcon-kac` +
`falcon-image-analyzer` schema to the new `falcon-clusterguard` (FCG) schema.

## Requirements

Python 3.8+ and the `ruamel.yaml` library (0.17+):

```bash
pip3 install ruamel.yaml
```

`helm` must be in your PATH if using the interactive wizard or the `--interactive` flag.

> [!NOTE]
> There is no default FCG image repository, tag, or digest yet. Pass `--fcg-image-repo` and
> `--fcg-image-tag` (or `--fcg-image-digest`); otherwise the script prompts for them, or exits with
> an error when it isn't running in a terminal. Default values will be added once FCG is generally
> available.

## Usage

```bash
python3 scripts/migration/migrate-to-fcg.py [--interactive | --platform-values FILE | --sensor-values FILE ] [options]
```

### Input modes (mutually exclusive)

**Interactive wizard** — guided prompts discover your release and values automatically.
Activates when `--interactive` is passed, or when no values flags are given:

```bash
python3 scripts/migration/migrate-to-fcg.py --interactive
```

**Umbrella chart mode** — single `falcon-platform` values file:
```bash
python3 scripts/migration/migrate-to-fcg.py --platform-values my-platform-values.yaml --fcg-image-repo <fcg-repo> --fcg-image-tag <fcg-tag>
```

**Individual charts mode** — separate values files per chart:
```bash
python3 scripts/migration/migrate-to-fcg.py \
  --sensor-values my-sensor-values.yaml \
  --kac-values my-kac-values.yaml \
  [--iar-values my-iar-values.yaml] \
  --fcg-image-repo <fcg-repo> \
  --fcg-image-tag <fcg-tag>
```

`--kac-values` and `--iar-values` are optional in individual charts mode. Values files are
expected to use root-level keys (as in a standalone `helm install falcon-sensor -f ...`
invocation), not nested under subchart name prefixes.

### Options

| Flag                  | Description                                                                                                                                          |
|-----------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| `--interactive`       | Run the interactive migration wizard                                                                                                                 |
| `--platform-values`   | Path to `falcon-platform` umbrella values file                                                                                                       |
| `--sensor-values`     | Path to standalone `falcon-sensor` values file                                                                                                       |
| `--kac-values`        | Path to standalone `falcon-kac` values file                                                                                                          |
| `--iar-values`        | Path to standalone `falcon-image-analyzer` values file                                                                                               |
| `--fcg-image-repo`    | FCG image repository, without a tag. Prompted for when not set. No default until FCG is generally available                                          |
| `--fcg-image-tag`     | FCG image tag. If neither `--fcg-image-tag` nor `--fcg-image-digest` is set, the script prompts for one. No default until FCG is generally available |
| `--fcg-image-digest`  | FCG image digest (`sha256:` followed by 64 hex characters). FCG uses it in place of the tag                                                          |
| `--admission-control` | Override `falcon-clusterguard.clusterguardController.admissionControl.enabled` (`true`/`false`)                                                      |
| `--image-analyzer`    | Override `falcon-clusterguard.imageAnalyzer.enabled` (`true`/`false`)                                                                                |
| `--output`            | Path for migrated output file. Defaults to `<input>.fcg-migrated.yaml`                                                                               |
| `--dry-run`           | Print the migrated YAML to stdout without writing any file                                                                                           |
| `--validate [CHART]`  | Render the migrated `falcon-clusterguard` values with `helm template` to check them. `CHART` defaults to the chart in this repository. Requires helm |

## Interactive wizard

Running the wizard without any flags is the recommended path for most users. It handles
release discovery and values extraction automatically.

```
python3 scripts/migration/migrate-to-fcg.py
```

### Step 1 — Locate your existing release

The wizard runs `helm list -A -o json` to find releases matching `falcon-platform`,
`falcon-sensor`, or `falcon-kac`. You confirm the match or enter the release name and
namespace manually.

### Step 2 — FCG image

Enter the FCG image repository, for example
`registry.crowdstrike.com/falcon-clusterguard/release/falcon-clusterguard` or the path in your
mirror. Then enter the FCG image tag, or a digest (`sha256:...`). There are no defaults until FCG
is generally available, and the wizard asks again until each value is valid.

### Step 3 — Values source

Either provide a path to an existing values file, or press Enter to extract values from
the running Helm release:

```bash
helm get values <release> -n <namespace> -o yaml
```

This returns only the values you explicitly set — chart defaults are excluded, keeping
the migrated output clean.

### Step 4 — Admission control

The wizard reads the current `admissionControl.enabled` value from the loaded values
(falling back to the old `falcon-kac` default of `true` if not found) and uses it as
the prompt default. Press Enter to keep the current behavior, or type `true`/`false` to
change it.

> **Note:** The FCG default for `admissionControl.enabled` is `false`, whereas the old
> `falcon-kac` default was `true`. The script always writes this value explicitly so
> your intent is preserved regardless of chart defaults.

### Step 5 — Image Analyzer

The wizard checks whether `falcon-image-analyzer` is present in your values and whether
`falcon-image-analyzer.enabled` is set, then prompts accordingly. Your answer is written to
`falcon-clusterguard.imageAnalyzer.enabled` — the image analyzer now runs inside FCG.

### Overriding wizard prompts with CLI flags

`--fcg-image-repo`, `--fcg-image-tag`, `--fcg-image-digest`, `--admission-control`, and
`--image-analyzer` skip their corresponding wizard prompts when passed alongside `--interactive`. The flag
value is used directly and the step simply confirms it:

```bash
# Skip the admission control and image analyzer prompts entirely
python3 scripts/migration/migrate-to-fcg.py --interactive \
  --admission-control true \
  --image-analyzer false

# Skip the image tag prompt
python3 scripts/migration/migrate-to-fcg.py --interactive --fcg-image-tag "8.15.0-99999-1"
```

## Quickstart (non-interactive)

**1. Preview the migration without writing any files:**

```bash
# Umbrella chart mode
python3 scripts/migration/migrate-to-fcg.py --platform-values my-values.yaml --fcg-image-repo <fcg-repo> --fcg-image-tag <fcg-tag> --dry-run

# Individual charts mode
python3 scripts/migration/migrate-to-fcg.py \
  --sensor-values sensor-values.yaml \
  --kac-values kac-values.yaml \
  --fcg-image-repo <fcg-repo> \
  --fcg-image-tag <fcg-tag> \
  --dry-run
```

Review the output and any warnings printed to stderr before proceeding.

**2. Write the migrated file:**

```bash
# Umbrella chart mode (output: my-values.fcg-migrated.yaml)
python3 scripts/migration/migrate-to-fcg.py --platform-values my-values.yaml --fcg-image-repo <fcg-repo> --fcg-image-tag <fcg-tag>

# Individual charts mode (output: sensor-values.fcg-migrated.yaml)
python3 scripts/migration/migrate-to-fcg.py \
  --sensor-values sensor-values.yaml \
  --kac-values kac-values.yaml \
  --fcg-image-repo <fcg-repo> \
  --fcg-image-tag <fcg-tag>
```

Use `--admission-control` and `--image-analyzer` to override those settings without
editing the output file:

```bash
python3 scripts/migration/migrate-to-fcg.py \
  --platform-values my-values.yaml \
  --fcg-image-repo <fcg-repo> \
  --fcg-image-tag <fcg-tag> \
  --admission-control true \
  --image-analyzer false
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

> [!IMPORTANT]
> Helm won't install FCG over objects that belong to another Helm release. If you installed any of
> these charts as their own releases, rather than through `falcon-platform`, deal with them first:
>
> | Standalone release          | Objects shared with FCG                                                                                                                   | What to do                                 |
> |:----------------------------|:------------------------------------------------------------------------------------------------------------------------------------------|:-------------------------------------------|
> | `falcon-sensor` (node mode) | DaemonSet `falcon-sensor` and ConfigMap `falcon-sensor-config`, if it's in the FCG namespace                                              | Uninstall it. FCG runs the node sensor.    |
> | `falcon-kac`                | ValidatingWebhookConfiguration `validating.falcon-kac.crowdstrike.com` (cluster-wide), and Service `webhook` if it's in the FCG namespace | Uninstall it. FCG runs admission control.  |
> | `falcon-image-analyzer`     | Service `iar-agent-service`, if it's in the FCG namespace                                                                                 | Uninstall it. FCG runs the image analyzer. |
>
> Uninstall these even when nothing is shared, because a second node sensor, admission webhook, or
> image analyzer would run alongside FCG's. Their protection stops between the uninstall and the FCG
> install.
>
> To keep each node's agent ID (AID), so hosts keep their identity in the Falcon console, skip the
> `falcon-sensor` cleanup when you uninstall it. The cleanup DaemonSet removes the sensor from every
> node, including its AID:
>
> ```bash
> helm uninstall <falcon-sensor-release> -n <namespace> --no-hooks
> ```
>
> FCG's node sensor then reuses the AID stored on each node. If you let the cleanup run instead,
> wait until its `*-node-cleanup` pods are gone before you install FCG.
>
> Upgrading `falcon-platform` should not need this step: the FCG subchart replaces the old subcharts'
> objects in the same release. Namespaces labeled `falcon-kac.crowdstrike.com/admission-review=disabled`
> stay excluded from admission control.

## What the script does

### Moves

| Source                                                | Destination                                                                  | Notes                                                                                                                                               |
|-------------------------------------------------------|------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `falcon-sensor.node.*`                                | `falcon-clusterguard.nodeSensor.*`                                           | Copied verbatim, except `clusterName` and `gke.*`, which move to the top level (below)                                                              |
| `falcon-sensor.node.clusterName`                      | `falcon-clusterguard.clusterName`                                            | Moved to the chart root, shared by all FCG components; takes precedence over kac and image analyzer                                                 |
| `falcon-sensor.node.gke.*`                            | `falcon-clusterguard.gke.*`                                                  | `autopilot` and the WorkloadAllowlist versions; moved to the chart root                                                                             |
| `falcon-sensor.serviceAccount.*`                      | `falcon-clusterguard.nodeSensor.serviceAccount.*`                            | Moved under `nodeSensor.`; old name preserved                                                                                                       |
| `falcon-sensor.falcon.*`                              | `falcon-clusterguard.falcon.*`                                               | Identical structure                                                                                                                                 |
| `falcon-sensor.falconSecret.*`                        | `falcon-clusterguard.falconSecret.*`                                         | Identical structure                                                                                                                                 |
| `falcon-sensor.secretsStore.*`                        | `falcon-clusterguard.secretsStore.*`                                         | Sensor takes precedence over kac                                                                                                                    |
| `falcon-sensor.node.openshift.*`                      | `falcon-clusterguard.openshift.*`                                            | Moved to chart root                                                                                                                                 |
| `falcon-sensor.node.image.pullSecrets`                | `falcon-clusterguard.image.pullSecret`                                       | Pull auth comes from one chart: the sensor if it sets `pullSecrets` or `registryConfigJSON`, otherwise kac                                          |
| `falcon-sensor.node.image.registryConfigJSON`         | `falcon-clusterguard.image.registryConfigJSON`                               | Pull auth comes from one chart: the sensor if it sets `pullSecrets` or `registryConfigJSON`, otherwise kac                                          |
| `falcon-kac.admissionControl.enabled`                 | `falcon-clusterguard.clusterguardController.admissionControl.enabled`        | Controls VWC + webhook Service; **old default was `true`, new default is `false`** — always written explicitly                                      |
| `falcon-kac.enabled: false`                           | `falcon-clusterguard.clusterguardController.admissionControl.enabled: false` | KAC wasn't deployed, so the webhook stays off. The clusterguard controller still runs for cluster visibility                                        |
| `falcon-kac.clusterName`                              | `falcon-clusterguard.clusterName`                                            | Only if the sensor sets no cluster name; a conflict prints a warning                                                                                |
| `falcon-kac.tolerations`                              | `falcon-clusterguard.clusterguardController.tolerations`                     | Moved under `clusterguardController.`                                                                                                               |
| `falcon-kac.webhook.*`                                | `falcon-clusterguard.clusterguardController.webhook.*`                       | Moved under `clusterguardController.`                                                                                                               |
| `falcon-kac.clusterVisibility.*`                      | `falcon-clusterguard.clusterguardController.visibility.*`                    | Moved under `clusterguardController.`                                                                                                               |
| `falcon-kac.falconSecret.*`                           | `falcon-clusterguard.falconSecret.*`                                         | Sensor value takes precedence                                                                                                                       |
| `falcon-kac.falcon.*`                                 | `falcon-clusterguard.falcon.*`                                               | Sensor value takes precedence; `trace`, `feature`, and `tags` are handled separately (below)                                                        |
| `falcon-kac.falcon.trace`/`feature`/`tags`            | `falcon-clusterguard.clusterguardController.falcon.*`                        | Only values that differ from the sensor's (or FCG's default), so the controller keeps them and the node sensor doesn't change                       |
| `falcon-kac.openshift.*`                              | `falcon-clusterguard.openshift.*`                                            | Merged with sensor openshift; sensor takes precedence                                                                                               |
| `falcon-kac.image.pullSecrets`                        | `falcon-clusterguard.image.pullSecret`                                       | Only if the sensor sets no image pull auth                                                                                                          |
| `falcon-image-analyzer.enabled`                       | `falcon-clusterguard.imageAnalyzer.enabled`                                  | `true` unless the source sets `enabled: false`                                                                                                      |
| `falcon-image-analyzer.daemonset.enabled`             | `falcon-clusterguard.imageAnalyzer.mode`                                     | `daemonset` when `true`; otherwise omitted (FCG defaults to `deployment`)                                                                           |
| `falcon-image-analyzer.*`                             | `falcon-clusterguard.imageAnalyzer.*`                                        | Pod, scheduling, exclusion, registry, proxy, volume, and certificate settings copied verbatim                                                       |
| `falcon-image-analyzer.securityContext`               | `falcon-clusterguard.imageAnalyzer.securityContext`                          | DaemonSet mode only — the standalone chart ignores it in Deployment mode                                                                            |
| `falcon-image-analyzer.azure.*`                       | `falcon-clusterguard.azure.*`                                                | Moved to the chart root                                                                                                                             |
| `falcon-image-analyzer.gcp.enabled`                   | `falcon-clusterguard.gke.enabled`                                            | `true` only if `gcp.enabled` was `true`; Autopilot alone does not set it                                                                            |
| `falcon-image-analyzer.crowdstrikeConfig.*`           | `falcon-clusterguard.imageAnalyzer.crowdstrikeConfig.*`                      | `clientID`, `clientSecret`, `agentRegion`, `agentMaxConsumerThreads`, `enableKlogs`; `agentRuntime` and `agentRuntimeSocket` in DaemonSet mode only |
| `falcon-image-analyzer.crowdstrikeConfig.clusterName` | `falcon-clusterguard.clusterName`                                            | Only if sensor and kac set no cluster name; a conflict prints a warning                                                                             |
| `falcon-image-analyzer.crowdstrikeConfig.cid`         | `falcon-clusterguard.falcon.cid`                                             | Only if neither `falcon.cid` nor `global.falcon.cid` is set                                                                                         |
| `falcon-image-analyzer.image.pullSecret`              | `falcon-clusterguard.image.pullSecret`                                       | Only if sensor and kac set no image pull auth                                                                                                       |
| `falcon-image-analyzer.image.registryConfigJSON`      | `falcon-clusterguard.image.registryConfigJSON`                               | Only if sensor and kac set no image pull auth                                                                                                       |
| `falcon-image-analyzer.openshift.enabled`/`createSCC` | `falcon-clusterguard.openshift.*`                                            | Lowest precedence after sensor and kac                                                                                                              |
| `falcon-image-analyzer.openshift.sccName`             | `falcon-clusterguard.openshift.iarSCCName`                                   | Renamed                                                                                                                                             |
| `global.*`                                            | `global.*`                                                                   | Unchanged                                                                                                                                           |

### Renames

These `falcon-kac` resource keys are renamed under `falcon-clusterguard.clusterguardController.resources.*`:

| Old key                          | New key                                                |
|----------------------------------|--------------------------------------------------------|
| `falconClientResources`          | `clusterguardController.resources.client`              |
| `falconClientNoWebhookResources` | `clusterguardController.resources.clientNoWebhook`     |
| `falconWatcherResources`         | `clusterguardController.resources.watcher`             |
| `falconAcResources`              | `clusterguardController.resources.admissionController` |

The migrated file adds an inline comment next to each renamed key showing its original name,
e.g. `client:  # was: falconClientResources`.

### Service account names

Service account names are carried forward from the source values to avoid breaking external RBAC.
If the source had no custom name set, the script writes the old chart defaults explicitly:

| Source default                           | Written to output                                                |
|------------------------------------------|------------------------------------------------------------------|
| `falcon-sensor`: `crowdstrike-falcon-sa` | `falcon-clusterguard.nodeSensor.serviceAccount.name`             |
| `falcon-kac`: `falcon-kac-sa`            | `falcon-clusterguard.clusterguardController.serviceAccount.name` |

### Image

The script sets the FCG image repository and the tag or digest that you pass with
`--fcg-image-repo` and `--fcg-image-tag` or `--fcg-image-digest`, or enter at the prompt:

```yaml
falcon-clusterguard:
  image:
    repository: <fcg-repo>  # for example registry.crowdstrike.com/falcon-clusterguard/release/falcon-clusterguard
    tag: <fcg-tag>          # or digest: sha256:<64 hex characters>
```

There is no default repository, tag, or digest yet. The repository can't include a tag or digest. Default values will be added once FCG is generally
available. A digest without the `sha256:` prefix is written with it. If you pass both, both are
written and FCG uses the digest.

Image pull auth is taken from one chart, because FCG rejects `pullSecret` and `registryConfigJSON`
together: `falcon-sensor.node.image` if it sets `pullSecrets` or `registryConfigJSON`, otherwise
`falcon-kac.image`. `pullSecrets` is written as FCG's `pullSecret`. `pullPolicy` is carried over the
same way. An image `digest` is dropped with a warning, because it identifies the old image and FCG
would use it in place of the tag.

### Deprecated keys

Keys that have no FCG equivalent are dropped with a warning:

| Key                                                          | Behaviour                                                                                     |
|--------------------------------------------------------------|-----------------------------------------------------------------------------------------------|
| `falcon-sensor.node.backend`                                 | Dropped entirely — FCG auto-selects eBPF/kernel                                               |
| `falcon-kac.falconImageAnalyzerNamespace`                    | Dropped — the image analyzer runs in the FCG namespace                                        |
| `falcon-sensor.node.image.digest`, `falcon-kac.image.digest` | Dropped — the digest belongs to the old image; set the FCG image digest instead               |
| `falcon-image-analyzer.image.repository`/`tag`/`digest`      | Dropped — the image analyzer runs from the FCG image                                          |
| `falcon-image-analyzer.secretsStore.*`                       | Dropped — FCG uses one `falcon-clusterguard.secretsStore` for all components                  |
| `falcon-image-analyzer.crowdstrikeConfig.existingSecret`     | Dropped — add `AGENT_CLIENT_ID`, `AGENT_CLIENT_SECRET`, `AGENT_CID` to `falconSecret` instead |
| `falcon-kac.replicas`                                        | Dropped — FCG runs one clusterguard controller replica                                        |
| `falcon-image-analyzer.replicaCount`                         | Dropped — FCG runs one Image Analyzer Deployment replica                                      |
| `falcon-image-analyzer.crowdstrikeConfig.dockerAPIToken`     | Dropped — FCG has no equivalent                                                               |

### Comments

Comments in the source values are kept and moved with their keys:

- A comment at the end of a key's line stays at the end of that key's line.
- Full-line comments stay above the key or list item that follows them.
- Comments at the top of the file stay at the top of the output.
- A renamed key keeps its comment next to the rename note, for example
  `client:  # was: falconClientResources — sized for 2k pods`.

A comment isn't carried over when its key is dropped (such as `falcon-sensor.node.backend` or an
old image tag), or when the migration changed the key's value (such as `admissionControl.enabled`
when `falcon-kac.enabled` was `false`). Those comments are listed in a warning so you can copy any
you still need. Comments that mention old key names are copied as they are, so review them.

### falcon-sensor output

- **No container mode active** — `falcon-sensor` is removed from output entirely. `falcon-platform` defaults (`enabled: false`, `node.enabled: false`) handle it.
- **Container mode active** (`container.enabled: true`) — script retains the `container.*` block and shared top-level keys; drops all `node.*` values with a comment stating node mode is no longer supported.

### falcon-kac

Fully removed from output. A comment above `falcon-clusterguard` notes the removal.

### falcon-image-analyzer

Values are moved to `falcon-clusterguard.imageAnalyzer.*` (see [Moves](#moves)). The output has no
`falcon-image-analyzer` block, because `falcon-platform` no longer includes the image analyzer
subchart; a comment above `falcon-clusterguard` notes the move. `kac.namespace` and
`namespaceOverride` are dropped without a warning, since the image analyzer now runs in the FCG
namespace.

## Input checks

The script stops with `ERROR:` and exit status 1, before writing anything, when an input can't be
migrated:

| Problem                                                  | Example message                                                                                             |
|----------------------------------------------------------|-------------------------------------------------------------------------------------------------------------|
| Missing file, directory, or a file that isn't UTF-8 text | `my-values.yaml: file not found`                                                                            |
| Invalid YAML, including duplicate keys                   | `my-values.yaml, line 4, column 3: invalid YAML: found duplicate key "node" ...`                            |
| Empty file, or one with only comments                    | `my-values.yaml: no values found ...`                                                                       |
| Top level isn't a mapping                                | `my-values.yaml: expected a mapping of values at the top level, got a list`                                 |
| A block or value the script reads has the wrong type     | `falcon-kac.admissionControl must be a mapping, got a boolean (true)`                                       |
| A falcon-platform values file passed as a chart file     | `my-values.yaml looks like a falcon-platform values file ... Use --platform-values my-values.yaml instead.` |
| A standalone chart file passed as `--platform-values`    | `sensor.yaml looks like a standalone falcon-sensor values file, not a falcon-platform values file. ...`     |
| A chart file passed with the wrong flag                  | `kac.yaml looks like a falcon-kac values file, not a falcon-sensor values file. Pass it with --kac-values.` |
| Values that are already migrated                         | `my-values.yaml looks like falcon-clusterguard values ..., which are already migrated. ...`                 |

Every wrong type is listed in one error, so you can fix them all at once. A key set to null is
treated as unset.

Keys that the source charts don't define, which are usually typos, are reported as warnings:

```
  ⚠  falcon-sensor.node.daemonSet is not a falcon-sensor value, so it was omitted. Check it for a typo.
  ⚠  falcon-sensor.falcon.trase is not a falconctl option. It was copied to falcon-clusterguard.falcon as-is; check it for a typo.
```

### Validating the output

The input checks only cover the values the script reads. Values it copies as-is, such as
`daemonset.tolerations`, are checked by the `falcon-clusterguard` chart. Add `--validate` to render
the migrated values with `helm template` before you upgrade:

```bash
python3 scripts/migration/migrate-to-fcg.py --platform-values my-values.yaml \
  --fcg-image-repo <fcg-repo> --fcg-image-tag <fcg-tag> --validate
```

`--validate` uses the chart in this repository. To use another copy, pass its path or name, for
example `--validate ./falcon-clusterguard`. If helm can't render the values, the script prints
helm's error and exits with status 1. The migrated file is still written, so you can fix it.

The `falcon-clusterguard` block is rendered on its own, with `global.*` from the same file. Settings
you passed with `--set` when you installed aren't in the values file, so add them to the file
first; otherwise helm may report them missing, such as the Falcon CID.

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
# falcon-sensor.node is deprecated — replaced by falcon-clusterguard.nodeSensor.*
# falcon-kac is deprecated — replaced by falcon-clusterguard.clusterguardController.*
# falcon-image-analyzer is deprecated — replaced by falcon-clusterguard.imageAnalyzer.*

falcon-clusterguard:
```

## After migration

1. **Review the full diff** before applying to a production cluster.
2. **Confirm image analyzer credentials** — if `falcon-clusterguard.falconSecret` or `secretsStore`
   is enabled, the image analyzer reads its client ID and secret from there, so
   `imageAnalyzer.crowdstrikeConfig.clientID`/`clientSecret` must be removed.
3. **Review the warnings** — each one names a key that was dropped or needs manual review.

## Example

Input (`my-values.yaml`):
```yaml
global:
  falcon:
    cid: YOUR-CID-HERE

falcon-sensor:
  enabled: true
  node:
    clusterName: "my-cluster"  # must match the cluster name in the CMDB
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
python3 scripts/migration/migrate-to-fcg.py --platform-values my-values.yaml \
  --fcg-image-repo registry.crowdstrike.com/falcon-clusterguard/release/falcon-clusterguard \
  --fcg-image-tag 8.14.0-12345-1 --dry-run
```

Output:
```yaml
global:
  falcon:
    cid: YOUR-CID-HERE

# falcon-sensor.node is deprecated — replaced by falcon-clusterguard.nodeSensor.*
# falcon-kac is deprecated — replaced by falcon-clusterguard.clusterguardController.*
# falcon-image-analyzer is deprecated — replaced by falcon-clusterguard.imageAnalyzer.*

falcon-clusterguard:
  enabled: true
  namespaceOverride: falcon-system
  clusterName: "my-cluster"  # must match the cluster name in the CMDB
  image:
    repository: registry.crowdstrike.com/falcon-clusterguard/release/falcon-clusterguard
    tag: 8.14.0-12345-1
  nodeSensor:
    daemonset:
      tolerations:
        - key: "node-role.kubernetes.io/master"
          operator: "Exists"
          effect: "NoSchedule"
    serviceAccount:
      name: crowdstrike-falcon-sa

  clusterguardController:
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
    visibility:
      resourceWatcher:
        enabled: true

  imageAnalyzer:
    enabled: true
```

## Running the tests

The tests in `scripts/migration/tests/` cover every mapping, warning, and precedence rule, plus the CLI, the
interactive wizard, and the next-steps output. They also check the script against the chart:

- Every key the script writes must exist in the falcon-clusterguard `values.yaml` or
  `values.schema.json`.
- The migrated values must render with `helm template` (skipped when `helm` isn't installed).
- The [Example](#example) output above must match the script's output exactly, so update it when
  the output changes.

Run them from the repository root. They use only the standard library and `ruamel.yaml`:

```bash
python3 -m unittest discover -s scripts/migration/tests -v
```
