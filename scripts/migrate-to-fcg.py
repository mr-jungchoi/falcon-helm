#!/usr/bin/env python3
"""
migrate-to-fcg.py — Migrate Falcon platform values to falcon-clusterguard (FCG).

Supports two input modes (mutually exclusive):

  Umbrella chart mode — one falcon-platform values file:
    python3 scripts/migrate-to-fcg.py --platform-values my-platform-values.yaml

  Individual charts mode — separate values files per chart:
    python3 scripts/migrate-to-fcg.py \\
      --sensor-values my-sensor-values.yaml \\
      --kac-values my-kac-values.yaml \\
      [--iar-values my-iar-values.yaml]

Common options:
    --fcg-image-repo  FCG image repository (default: registry.crowdstrike.com/falcon-clusterguard/release/falcon-clusterguard)
    --fcg-image-tag   FCG image tag (default: 8.14.0-12345-1)
    --output <file>   Write output to this path (default: <first-input>.fcg-migrated.yaml)
    --dry-run         Print migrated YAML to stdout without writing any file

Requirements:
    pip3 install ruamel.yaml
"""

import argparse
import os
import sys
from copy import deepcopy

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap
except ImportError:
    print("ERROR: ruamel.yaml is required. Install it with: pip3 install ruamel.yaml", file=sys.stderr)
    sys.exit(1)


FCG_DEFAULT_IMAGE_REPO = "registry.crowdstrike.com/falcon-clusterguard/release/falcon-clusterguard"
FCG_DEFAULT_IMAGE_TAG  = "8.14.0-12345-1"

# ---------------------------------------------------------------------------
# Keys that existed in falcon-sensor / falcon-kac but have no FCG equivalent.
# Each entry: (source_path_tuple, replacement_note)
# Used to annotate the deprecated stub blocks in the output.
# ---------------------------------------------------------------------------

DEPRECATED_SENSOR_KEYS = {
    # (key_in_node_block, comment)
    "backend": "DEPRECATED: removed in FCG. Sensor auto-selects eBPF/kernel.",
}

DEPRECATED_KAC_KEYS = {
    # (top-level key in falcon-kac, comment) — currently empty; kept for future use
}

# falcon-kac resource keys that were renamed — emit an EOL comment on the new key
# showing where it came from.
RESOURCE_RENAMES = {
    "falconClientResources":          ("client",              "# was: falconClientResources"),
    "falconClientNoWebhookResources": ("clientNoWebhook",     "# was: falconClientNoWebhookResources"),
    "falconWatcherResources":         ("watcher",             "# was: falconWatcherResources"),
    "falconAcResources":              ("admissionController", "# was: falconAcResources"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_nested(d, *keys):
    """Return d[k1][k2]... or None if any key is missing."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def set_nested(d, keys, value):
    """Set d[k1][k2]... = value, creating intermediate CommentedMaps as needed."""
    for k in keys[:-1]:
        if k not in d or not isinstance(d[k], dict):
            d[k] = CommentedMap()
        d = d[k]
    d[keys[-1]] = value


def annotate_deprecated(cm, key, comment):
    """Add a DEPRECATED comment before a key in a CommentedMap, if the key exists."""
    if key in cm:
        cm.yaml_set_comment_before_after_key(key, before=comment)


# ---------------------------------------------------------------------------
# Migration logic
# ---------------------------------------------------------------------------

def migrate(values: dict, warnings: list,
            fcg_image_repo: str = FCG_DEFAULT_IMAGE_REPO,
            fcg_image_tag: str = FCG_DEFAULT_IMAGE_TAG) -> dict:
    fcg = CommentedMap()
    fcg["enabled"] = True

    # ---- falcon-sensor → falcon-clusterguard.node -------------------------

    sensor = values.get("falcon-sensor", {}) or {}
    sensor_node = sensor.get("node", {}) or {}

    # namespaceOverride — pick falcon-sensor's if set, else default falcon-system
    ns_override = sensor.get("namespaceOverride") or "falcon-system"
    fcg["namespaceOverride"] = ns_override

    # image — set canonical FCG registry and tag, then carry over auth/digest from
    # falcon-sensor.node.image or falcon-kac.image (sensor takes precedence).
    fcg_image = CommentedMap()
    fcg_image["repository"] = fcg_image_repo
    fcg_image["tag"] = fcg_image_tag

    sensor_image = get_nested(sensor, "node", "image") or {}
    kac_image = get_nested(values.get("falcon-kac") or {}, "image") or {}
    # Prefer sensor value; fall back to kac for shared image auth fields
    for field in ("pullSecrets", "registryConfigJSON", "digest", "pullPolicy"):
        val = sensor_image.get(field) or kac_image.get(field)
        if val:
            fcg_image[field] = val

    fcg["image"] = fcg_image

    if sensor_node:
        node = CommentedMap()

        direct_node_keys = [
            "enabled", "clusterName", "gke", "daemonset", "podAnnotations", "podLabels",
            "terminationGracePeriod", "hooks", "cleanupOnly",
        ]
        for k in direct_node_keys:
            if k in sensor_node:
                node[k] = deepcopy(sensor_node[k])

        # backend is deprecated — omit it, add warning and comment
        if sensor_node.get("backend"):
            warnings.append(
                "falcon-sensor.node.backend is deprecated in FCG and has been omitted."
            )

        # serviceAccount lives at falcon-sensor top level, maps to node.serviceAccount.
        # Carry the old name forward explicitly to avoid breaking external RBAC.
        sensor_sa = deepcopy(sensor.get("serviceAccount") or {})
        if not sensor_sa.get("name"):
            sensor_sa["name"] = "crowdstrike-falcon-sa"
        node["serviceAccount"] = sensor_sa

        fcg["node"] = node
    else:
        warnings.append(
            "falcon-sensor.node block not found — falcon-clusterguard.node not populated. "
            "Add node configuration manually."
        )

    # ---- falcon-kac → falcon-clusterguard.cluster -------------------------

    kac = values.get("falcon-kac", {}) or {}

    if kac:
        cluster = CommentedMap()

        # Direct moves — key name unchanged, parent moves to cluster.*
        direct_cluster_keys = [
            "webhookPort", "watcherPort", "autoCertificateUpdate", "certExpiration",
            "domainName", "hostNetwork", "dnsPolicy", "tolerations", "affinity",
            "annotations", "labels", "podAnnotations", "podLabels",
            "autoDeploymentUpdate", "replicas", "tlsVersionMinimum",
        ]
        for k in direct_cluster_keys:
            if k in kac:
                cluster[k] = deepcopy(kac[k])

        # falcon-kac.enabled → cluster.enabled (controls the cluster sensor Deployment)
        # Always written explicitly — default changed from true (kac) to true (FCG).
        if kac.get("enabled") is not None:
            cluster["enabled"] = kac["enabled"]
        else:
            cluster["enabled"] = True

        # falcon-kac.admissionControl.enabled → cluster.admissionControl.enabled
        # Controls the ValidatingWebhookConfiguration + webhook Service.
        # Old default: true. New default: false. Always write explicitly to preserve behavior.
        kac_ac = kac.get("admissionControl", {}) or {}
        ac_enabled = kac_ac.get("enabled", True)  # old kac default was true
        if "admissionControl" not in cluster:
            cluster["admissionControl"] = CommentedMap()
        cluster["admissionControl"]["enabled"] = ac_enabled

        # webhook block
        kac_webhook = kac.get("webhook", {}) or {}
        if kac_webhook:
            cluster["webhook"] = deepcopy(kac_webhook)

        # resourceQuota
        if "resourceQuota" in kac:
            cluster["resourceQuota"] = deepcopy(kac["resourceQuota"])

        # certManager (newer kac versions)
        if "certManager" in kac:
            cluster["certManager"] = deepcopy(kac["certManager"])

        # Resource renames — add EOL comment showing the old key name
        resources = CommentedMap()
        for old_key, (new_key, eol_comment) in RESOURCE_RENAMES.items():
            if old_key in kac:
                resources[new_key] = deepcopy(kac[old_key])
                resources.yaml_add_eol_comment(eol_comment, key=new_key)
        if resources:
            cluster["resources"] = resources

        # serviceAccount → cluster.serviceAccount.
        # Carry the old name forward explicitly to avoid breaking external RBAC.
        kac_sa = deepcopy(kac.get("serviceAccount") or {})
        if not kac_sa.get("name"):
            kac_sa["name"] = "falcon-kac-sa"
        cluster["serviceAccount"] = kac_sa

        fcg["cluster"] = cluster

        # clusterName at kac top level → node.clusterName
        if "clusterName" in kac and kac["clusterName"]:
            if "node" not in fcg:
                fcg["node"] = CommentedMap()
            if "clusterName" not in fcg["node"]:
                fcg["node"]["clusterName"] = kac["clusterName"]
            else:
                warnings.append(
                    f"falcon-kac.clusterName='{kac['clusterName']}' conflicts with "
                    f"falcon-sensor.node.clusterName='{fcg['node']['clusterName']}'. "
                    "The falcon-sensor value has been kept. Review manually."
                )

        # clusterVisibility — identical structure, lives at fcg root
        if "clusterVisibility" in kac:
            fcg["clusterVisibility"] = deepcopy(kac["clusterVisibility"])

        # falconImageAnalyzerNamespace — lives at fcg root
        if "falconImageAnalyzerNamespace" in kac and kac["falconImageAnalyzerNamespace"]:
            fcg["falconImageAnalyzerNamespace"] = kac["falconImageAnalyzerNamespace"]

        # falconSecret — prefer sensor value if both present
        if "falconSecret" in kac:
            if "falconSecret" not in fcg:
                fcg["falconSecret"] = deepcopy(kac["falconSecret"])
            else:
                warnings.append(
                    "falconSecret found in both falcon-sensor and falcon-kac. "
                    "The falcon-sensor value has been used. Review manually."
                )

        # falcon.* (CID, cloud, trace, etc.)
        if "falcon" in kac:
            if "falcon" not in fcg:
                fcg["falcon"] = deepcopy(kac["falcon"])

    else:
        warnings.append(
            "falcon-kac block not found — falcon-clusterguard.cluster not populated. "
            "Add cluster configuration manually."
        )

    # falconSecret from falcon-sensor (if not already set)
    sensor_secret = get_nested(sensor, "falconSecret")
    if sensor_secret and "falconSecret" not in fcg:
        fcg["falconSecret"] = deepcopy(sensor_secret)

    # falcon.* from falcon-sensor (if not already set)
    sensor_falcon = sensor.get("falcon")
    if sensor_falcon and "falcon" not in fcg:
        fcg["falcon"] = deepcopy(sensor_falcon)

    # secretsStore — prefer sensor value; fall back to kac
    sensor_csi = sensor.get("secretsStore") or {}
    kac_csi = (values.get("falcon-kac") or {}).get("secretsStore") or {}
    merged_csi = deepcopy(kac_csi)
    merged_csi.update({k: v for k, v in sensor_csi.items() if v})
    if any(v for v in merged_csi.values() if v):
        fcg["secretsStore"] = merged_csi

    # openshift — prefer sensor value; fall back to kac (both map to fcg root)
    sensor_os = get_nested(sensor, "node", "openshift") or {}
    kac_os = (values.get("falcon-kac") or {}).get("openshift") or {}
    merged_os = deepcopy(kac_os)
    merged_os.update({k: v for k, v in sensor_os.items() if v is not None})
    if merged_os.get("enabled") or merged_os.get("createSCC") is False:
        fcg["openshift"] = merged_os

    # ---- Build output values -----------------------------------------------

    out = CommentedMap()

    # Preserve top-level keys that pass through unchanged
    preserved_top = ["global", "createComponentNamespaces"]
    for k in preserved_top:
        if k in values:
            out[k] = deepcopy(values[k])

    # falcon-sensor: retain only if container mode is active.
    # If container mode is falsy, remove the block entirely — falcon-platform
    # defaults falcon-sensor.enabled=false, so no stub needed.
    sensor_container = sensor.get("container", {}) or {}
    if sensor_container and sensor_container.get("enabled"):
        # Container mode active — keep only the container block, drop all node.* values.
        sensor_out = CommentedMap()
        sensor_out["container"] = deepcopy(sensor_container)
        # Preserve top-level falcon-sensor keys that apply to container mode
        for k in ("enabled", "namespaceOverride", "falcon", "falconSecret",
                  "serviceAccount", "secretsStore", "openshift"):
            if k in sensor:
                sensor_out[k] = deepcopy(sensor[k])
        out["falcon-sensor"] = sensor_out
        out.yaml_set_comment_before_after_key(
            "falcon-sensor",
            before=(
                "\nRetained for container sensor (container.enabled=true)."
                "\nfalcon-sensor.node is no longer supported — replaced by falcon-clusterguard.node.*"
            ),
        )
    # else: falcon-sensor omitted entirely — falcon-platform defaults handle it

    # Comments prepended to falcon-clusterguard noting both removals.
    sensor_node_deprecated_note = "falcon-sensor.node is deprecated — replaced by falcon-clusterguard.node.*\n"
    kac_deprecated_note = "falcon-kac is deprecated — replaced by falcon-clusterguard.cluster.*\n\n"

    # falcon-clusterguard: the new chart
    out["falcon-clusterguard"] = fcg
    out.yaml_set_comment_before_after_key(
        "falcon-clusterguard",
        before=sensor_node_deprecated_note + kac_deprecated_note,
    )

    # falcon-image-analyzer: pass through, but fix kac.namespace if it pointed to
    # the old falcon-kac namespace. Use falcon-sensor.namespaceOverride as the FCG
    # namespace, falling back to "falcon-system".
    if "falcon-image-analyzer" in values:
        iar = deepcopy(values["falcon-image-analyzer"])
        fcg_ns = sensor.get("namespaceOverride") or "falcon-system"
        kac_block = iar.get("kac", {}) or {}
        old_kac_ns = kac_block.get("namespace", "")
        if old_kac_ns and old_kac_ns != fcg_ns:
            iar["kac"]["namespace"] = fcg_ns
            iar["kac"].yaml_add_eol_comment(
                f"updated from '{old_kac_ns}' — FCG runs in {fcg_ns}",
                key="namespace",
            )
        out["falcon-image-analyzer"] = iar
        out.yaml_set_comment_before_after_key(
            "falcon-image-analyzer",
            before="\nDEPRECATED: falcon-image-analyzer will be bundled into FCG in a future version.",
        )

    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Migrate Falcon platform values to falcon-clusterguard (FCG).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Input modes (mutually exclusive):\n"
            "  --platform-values    Single falcon-platform umbrella values file\n"
            "  --sensor-values / --kac-values / --iar-values\n"
            "                       Individual chart values files\n"
        ),
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--platform-values",
        metavar="FILE",
        help="falcon-platform umbrella values file",
    )
    input_group.add_argument(
        "--sensor-values",
        metavar="FILE",
        help="falcon-sensor values file (individual chart mode)",
    )

    parser.add_argument(
        "--kac-values",
        metavar="FILE",
        help="falcon-kac values file (individual chart mode)",
    )
    parser.add_argument(
        "--iar-values",
        metavar="FILE",
        help="falcon-image-analyzer values file (individual chart mode)",
    )
    parser.add_argument(
        "--fcg-image-repo",
        metavar="REPO",
        default=FCG_DEFAULT_IMAGE_REPO,
        help=f"FCG image repository (default: {FCG_DEFAULT_IMAGE_REPO})",
    )
    parser.add_argument(
        "--fcg-image-tag",
        metavar="TAG",
        default=FCG_DEFAULT_IMAGE_TAG,
        help=f"FCG image tag (default: {FCG_DEFAULT_IMAGE_TAG})",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Path for migrated output file (default: <input>.fcg-migrated.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print migrated YAML to stdout instead of writing a file",
    )
    args = parser.parse_args()

    # Validate individual charts are not mixed with the platform chart
    if args.platform_values and (args.sensor_values or args.kac_values or args.iar_values):
        parser.error("--sensor-values, --kac-values, and --iar-values cannot be used with --platform-values")

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 120
    yaml.best_sequence_indent = 2
    yaml.best_map_flow_style = False

    def load(path):
        with open(path, "r") as f:
            return yaml.load(f) or {}

    if args.platform_values:
        # Umbrella mode — values already nested under subchart keys
        values = load(args.platform_values)
        primary_input = args.platform_values
    else:
        # Individual charts mode — synthesize the same nested structure
        sensor_vals = load(args.sensor_values)
        kac_vals    = load(args.kac_values) if args.kac_values else {}
        iar_vals    = load(args.iar_values) if args.iar_values else {}

        values = CommentedMap()
        if sensor_vals:
            values["falcon-sensor"] = sensor_vals
        if kac_vals:
            values["falcon-kac"] = kac_vals
        if iar_vals:
            values["falcon-image-analyzer"] = iar_vals
        primary_input = args.sensor_values

    warnings = []
    migrated = migrate(values, warnings,
                       fcg_image_repo=args.fcg_image_repo,
                       fcg_image_tag=args.fcg_image_tag)

    if warnings:
        print("\nMIGRATION WARNINGS — review these before applying:", file=sys.stderr)
        for w in warnings:
            print(f"  ⚠  {w}", file=sys.stderr)
        print(file=sys.stderr)

    if args.dry_run:
        yaml.dump(migrated, sys.stdout)
    else:
        base, _ = os.path.splitext(primary_input)
        output_path = args.output or f"{base}.fcg-migrated.yaml"
        if output_path == primary_input:
            print("ERROR: output path would overwrite input file; use --output to specify a different path", file=sys.stderr)
            sys.exit(1)
        with open(output_path, "w") as f:
            yaml.dump(migrated, f)
        print(f"Migrated values written to: {output_path}")
        print("Review the output and warnings before running helm upgrade.")


if __name__ == "__main__":
    main()
