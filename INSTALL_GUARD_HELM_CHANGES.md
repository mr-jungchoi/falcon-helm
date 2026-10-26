# Helm changes for FCG install guard (uninstall / tamper protection)

Review note for this branch; not meant to be merged into the charts.

Jira: CSPG-102165. Sensor-side change: k8sclient install guard (KAC), sensor PR 66173.
Node sensor side: CSPG-102140.

Base: `fcg-helm-chart` (after the cg-controller/ and node/ template split and the
cert-manager support). Supersedes `feature/CSPG-102165-clusterguard-install-guard`,
which was based on the chart before that refactor.

## Background

When the cloud enables uninstall protection, KAC creates (at runtime, not from the
chart) a second ValidatingWebhookConfiguration, `install-guard.falcon-clusterguard.crowdstrike.com`.
It blocks deletion/disruption of the KAC and sensor workloads and namespaces while
protection is armed, and is removed again when protection is disabled or temporarily
disarmed with a maintenance token. Its webhook entries call falcon-client through the
`webhook` Service, verified with the webhook TLS CA, and use `failurePolicy: Ignore`.

Install guard is controlled by the cloud, **not** by `admissionControl.enabled`
(falcon-clusterguard default: `false`). The chart therefore has to provide what the
install guard VWC needs regardless of admission control.

KAC takes the install guard caBundle only from the mounted `ca.crt` of the webhook
TLS Secret (`/run/secrets/tls/ca.crt`), read once at startup together with the
server certificate, and refuses to arm (reports "not applied" to the cloud) when it
is missing or invalid. When the install guard VWC already exists (KAC restart, or a
SetUninstallToken retransmission) KAC updates it to the desired spec (entries,
caBundle, owner reference).

## Commits on this branch (falcon-clusterguard)

### "webhook Service independent of admission control"

- `templates/cg-controller/service-webhook.yaml`: render the `webhook` Service
  whenever ClusterGuard is deployed (`falcon-clusterguard.clusterGuardDisabled ==
  "false"`, same condition as the controller), instead of only with admission control.

Without it, with admission control disabled the install guard VWC points to a
missing Service: every call fails, `failurePolicy: Ignore` admits the request, and
the cluster is not protected while KAC reports protection as active.

Impact: with admission control enabled, none. Disabled: one extra Service (`webhook`,
port 443 -> `webhook-port`, which the controller pod always exposes).

### "node sensor mounts the KAC install guard state ConfigMap"

KAC publishes the install guard state for node sensors as key `installguard.state`
(`armed`, `disarmed` or `disabled`; missing means `disabled`) of its own ConfigMap
`falcon-fcg-install-guard-state`, written at runtime in the ClusterGuard namespace.
While armed, KAC's install guard webhook denies updates of this ConfigMap by anyone
but KAC's service account. The node sensor (CSPG-102140) polls
`/opt/CrowdStrike/clusterguard-state/installguard.state` and accepts the uninstall
token only once KAC has armed install guard.

- `templates/node/daemonset.yaml`: `falcon-sensor` container mounts volume
  `clusterguard-state` (ConfigMap `falcon-fcg-install-guard-state`, `optional: true`)
  at `/opt/CrowdStrike/clusterguard-state`, read-only, when ClusterGuard is deployed
  (same condition as the TLS/CA mounts).
  - Directory mount, not `subPath`: kubelet does not propagate ConfigMap updates to
    `subPath` mounts.
  - `optional: true`: the sensor starts (install guard disabled) before KAC creates
    the ConfigMap.
  - Same namespace as the DaemonSet; no RBAC needed for the node sensor.
  - The ConfigMap name is set by KAC and the mount path by the node sensor; only the
    volume name is chart-local.

Impact: one extra read-only volume on the sensor pod; a DaemonSet rollout on upgrade.

### "KAC RBAC for the install guard VWC"

- `templates/cg-controller/clusterrole.yaml`:
  - `update` next to `delete` in the rule restricted to
    `resourceNames: install-guard.falcon-clusterguard.crowdstrike.com`, so KAC can
    restore an existing VWC to the desired spec. Without it KAC does not arm on that
    SetUninstallToken / restart and reports it to the cloud as not applied.
  - `get` on `installguardowners`, restricted to `resourceNames: falcon-clusterguard`
    (owner reference, next commit).

Impact: RBAC only, restricted to the objects KAC itself uses.

### "InstallGuardOwner, owner of the install guard VWC"

The install guard VWC is created by KAC at runtime, so Helm does not know it and
`helm uninstall` would leave it behind. KAC therefore sets an owner reference on it
to a cluster-scoped object of the release; when that object is deleted, Kubernetes
garbage-collects the VWC. (The main admission VWC is not a reliable owner: it only
exists with admission control enabled.)

- `crds/installguardowners.falcon.crowdstrike.com.yaml`: CRD `InstallGuardOwner`
  (`falcon.crowdstrike.com/v1alpha1`, cluster-scoped, no fields).
- `templates/cg-controller/installguardowner.yaml`: the instance `falcon-clusterguard`,
  when ClusterGuard is deployed. The name is fixed: KAC looks it up by this name.

Notes:
- `crds/`: Helm installs the CRD before the templates and never upgrades or deletes
  it. That is enough here: the owner is the instance, a regular template object
  deleted by `helm uninstall`.
- Without the CRD or the instance (e.g. older chart), KAC creates the VWC without an
  owner reference.
- The operator needs the same objects (CRD, instance, RBAC).
- Under discussion with the KAC team (sensor PR, comment 6435929): instead of a CRD,
  an empty dedicated ClusterRole as the owner. If chosen, this commit is replaced.

Impact: one CRD, one cluster-scoped object.

### "KAC Role: Secrets in its namespace"

- `templates/cg-controller/role.yaml`: Secrets `create`, `get`, `update`, `delete`
  in the ClusterGuard namespace. KAC stores the install guard credential in the
  Secret `falcon-fcg-install-guard`; without `create` it fails with "secrets is
  forbidden", does not arm, and reports the SetUninstallToken as not applied.

The rule was in the controller Role before the template split (808fa67, "move node
and cg-controller resources into separate directories") and was dropped there,
apparently by accident; this restores it unchanged. `create` cannot be restricted by
`resourceNames`, so the rule is namespace-wide as before.

Impact: RBAC only, namespaced.

No values changes in any commit.

## Already in fcg-helm-chart (no change needed)

- Webhook CA reuse: with `autoCertificateUpdate: false` the chart reuses `tls.crt`,
  `tls.key` and `ca.crt` together from `falcon-cg-controller-tls`, or regenerates all
  three, so `ca.crt` always matches the served certificate. (The previous branch had
  its own fix for this; dropped.)
- The webhook TLS Secret is mounted whole at `/run/secrets/tls` in falcon-client.
- Install guard VWC `create` and `delete` RBAC; Role for ConfigMaps (KAC creates and
  updates the install guard state ConfigMap).

## cert-manager (`certManager.enabled=true`)

No chart change needed for install guard:
- cert-manager writes `falcon-cg-controller-tls` with `tls.crt`, `tls.key` and
  `ca.crt`, mounted as before. The issuer must fill `ca.crt` (CA or SelfSigned
  issuer, as the README requires); without it KAC does not arm.
- cainjector fills `caBundle` only of the main VWC (`inject-ca-from` annotation). The
  install guard VWC is not annotated: KAC sets its caBundle itself; an annotation
  would make cainjector and KAC's reconcile compete for the field.
- Renewal with a CA issuer keeps the CA, so the install guard caBundle stays valid.
  With a SelfSigned issuer each renewal makes a new CA: KAC keeps serving the old
  certificate with the old caBundle (consistent) until it restarts. (Hot reload of
  the server certificate is a separate follow-up.)
- Install guard protection does not block cert-manager: renewing updates the Secret
  (allowed; UPDATE protection covers only the install guard Secret and state
  ConfigMap).

## Verification

`helm lint`; `helm template` with the defaults, with
`cluster.admissionControl.enabled=true`, with `certManager.enabled=true`, and with
ClusterGuard disabled:
- `Service webhook` rendered whenever ClusterGuard is deployed.
- DaemonSet: `clusterguard-state` volume and mount rendered, absent with
  ClusterGuard disabled.
- ClusterRole: `update` and `delete` on the install guard VWC; `get` on
  `installguardowners/falcon-clusterguard`.
- Role: Secrets `create`, `get`, `update`, `delete`.
- `InstallGuardOwner` `falcon-clusterguard` rendered, absent with ClusterGuard
  disabled; CRD rendered with `--include-crds`.
- With cert-manager: `falcon-cg-controller-tls` Certificate and the main VWC
  `inject-ca-from` annotation; install guard objects unchanged.
