#!/usr/bin/env python3
"""
migrate-to-fcg.py — Migrate Falcon platform values to falcon-clusterguard (FCG).

Supports two input modes (mutually exclusive):

  Umbrella chart mode — one falcon-platform values file:
    python3 scripts/migration/migrate-to-fcg.py --platform-values my-platform-values.yaml

  Individual charts mode — separate values files per chart:
    python3 scripts/migration/migrate-to-fcg.py \\
      --sensor-values my-sensor-values.yaml \\
      --kac-values my-kac-values.yaml \\
      [--iar-values my-iar-values.yaml]

  Interactive mode — guided prompts discover your release and values:
    python3 scripts/migration/migrate-to-fcg.py --interactive

Common options:
    --fcg-image-repo        FCG image repository
    --fcg-image-tag         FCG image tag
    --fcg-image-digest      FCG image digest (sha256:<64 hex characters>); FCG uses it in place of the tag
    --admission-control     Override admission control enabled: true or false
    --image-analyzer        Override image analyzer enabled: true or false
    --output <file>         Write output to this path (default: <first-input>.fcg-migrated.yaml)
    --dry-run               Print migrated YAML to stdout without writing any file
    --validate [CHART]      Render the migrated values with helm template (default: this repository's chart)

An FCG image repository, and a tag or digest, are required. If they aren't passed, the script
prompts for them (or exits with an error when stdin is not a terminal). Default values will be
added once FCG is generally available.

Requirements:
    pip3 install ruamel.yaml
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap, CommentedSeq
    from ruamel.yaml.error import CommentMark, YAMLError
    from ruamel.yaml.tokens import CommentToken
except ImportError:
    print("ERROR: ruamel.yaml is required. Install it with: pip3 install ruamel.yaml", file=sys.stderr)
    sys.exit(1)


# There is no default FCG image repository, tag, or digest yet; the script asks for them instead.
# Default values will be added once FCG is generally available. The repository is expected to be
# registry.crowdstrike.com/falcon-clusterguard/release/falcon-clusterguard.

# An image repository without a tag or digest: an optional registry host (with an optional port),
# then lowercase path components. Also OCI tag syntax, and a sha256 digest with or without the
# "sha256:" prefix.
IMAGE_REPO_RE = re.compile(
    r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*(?::[0-9]+)?/)?"
    r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
    r"(?:/[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*)*$"
)
IMAGE_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
IMAGE_DIGEST_RE = re.compile(r"^(sha256:)?[a-f0-9]{64}$")

# falcon-kac resource keys that were renamed — emit an EOL comment on the new key
# showing where it came from.
RESOURCE_RENAMES = {
    "falconClientResources":          ("client",              "# was: falconClientResources"),
    "falconClientNoWebhookResources": ("clientNoWebhook",     "# was: falconClientNoWebhookResources"),
    "falconWatcherResources":         ("watcher",             "# was: falconWatcherResources"),
    "falconAcResources":              ("admissionController", "# was: falconAcResources"),
}

# falcon-image-analyzer keys copied to falcon-clusterguard.imageAnalyzer.*, in FCG values.yaml
# order. crowdstrikeConfig is filtered down to IAR_CROWDSTRIKE_CONFIG_KEYS.
IAR_KEYS = [
    "serviceAccount", "crowdstrikeConfig", "exclusions", "hostNetwork",
    "dnsPolicy", "podAnnotations", "podLabels", "podSecurityContext", "securityContext",
    "resources", "tolerations", "affinity", "priorityClassName", "nodeSelector", "watcher",
    "log", "iarAgentService", "privateRegistries", "volumes", "volumeMounts",
    "proxyConfig",
]

IAR_CROWDSTRIKE_CONFIG_KEYS = [
    "enableKlogs", "clientID", "clientSecret", "agentRegion",
    "agentMaxConsumerThreads", "agentRuntime", "agentRuntimeSocket",
]

# Keys the standalone chart only reads in DaemonSet mode. Copied only when migrating a DaemonSet,
# so Deployment-mode output doesn't carry settings that never took effect.
IAR_DAEMONSET_ONLY_KEYS = {"securityContext", "agentRuntime", "agentRuntimeSocket"}

# falcon-image-analyzer keys handled outside the IAR_KEYS copy, or that no longer apply
# once the image analyzer runs inside FCG (kac, namespaceOverride, global, testing).
IAR_HANDLED_KEYS = {
    "enabled", "deployment", "daemonset", "image", "openshift", "secretsStore", "azure", "gcp",
    "kac", "namespaceOverride", "global", "testing",
}
IAR_HANDLED_CROWDSTRIKE_CONFIG_KEYS = {"clusterName", "cid", "existingSecret"}

# falcon.* options FCG lets each component override in <component>.falcon, and the FCG
# defaults for them. falcon-kac values that differ from the node sensor's are written to
# clusterguardController.falcon.
COMPONENT_FALCON_KEYS = ("trace", "feature", "tags")
FCG_FALCON_DEFAULTS = {"trace": "none"}


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


def insert_before(cm, key, value, before):
    """Set cm[key] = value, placing a new key just before `before` when that key exists."""
    if key not in cm and before in cm:
        cm.insert(list(cm.keys()).index(before), key, value)
    else:
        cm[key] = value


def strip_comments(obj):
    """Recursively clear ruamel comment and blank-line metadata from a copied value.

    ruamel stores each comment on whatever token precedes it, often deep inside the previous
    block, so a copied block can carry blank lines or comments that belong elsewhere. Copies are
    stripped, and carry_comments() re-attaches source comments where their keys ended up.
    """
    if isinstance(obj, (CommentedMap, CommentedSeq)):
        obj.ca.items.clear()
        obj.ca.comment = None
        obj.ca.end = None
        for v in (obj.values() if isinstance(obj, CommentedMap) else obj):
            strip_comments(v)


def copy_value(value):
    """Deep copy a source value without its comment metadata (see strip_comments).

    A plain dict (such as an `or {}` default) becomes a CommentedMap so comments can be attached.
    """
    value = deepcopy(value)
    strip_comments(value)
    if isinstance(value, dict) and not isinstance(value, CommentedMap):
        value = CommentedMap(value)
    return value


def _parse_bool(value: str) -> bool:
    """Parse 'true'/'false' string from CLI into bool. Raises ValueError on bad input."""
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no"):
        return False
    raise ValueError(f"Expected true/false, got: {value!r}")


def validate_image_repo(value: str) -> str:
    """Return value if it is a valid image repository (no tag or digest). Raises ValueError on bad input."""
    if not IMAGE_REPO_RE.match(value or ""):
        raise ValueError(
            f"invalid image repository {value!r}: expected a path such as registry.example.com/falcon-clusterguard, "
            "in lowercase, without a tag or digest"
        )
    return value


def prompt_image_repo(out=None):
    """Ask for an FCG image repository until a valid one is entered.

    Prompts go to stderr by default so --dry-run output on stdout stays valid YAML.
    """
    out = out or sys.stderr
    print("An FCG image repository is required. Default values will be added once FCG is generally "
          "available.", file=out)
    while True:
        print("FCG image repository (for example registry.example.com/falcon-clusterguard): ", end="", file=out,
              flush=True)
        answer = sys.stdin.readline()
        if not answer:
            raise SystemExit("ERROR: no FCG image repository was entered.")
        try:
            return validate_image_repo(answer.strip())
        except ValueError as e:
            print(f"  {e}", file=out)


def validate_image_tag(value: str) -> str:
    """Return value if it is a valid image tag. Raises ValueError on bad input."""
    if not IMAGE_TAG_RE.match(value or ""):
        raise ValueError(f"invalid image tag {value!r}: use letters, digits, '_', '.', or '-' (up to 128 characters)")
    return value


def normalize_image_digest(value: str) -> str:
    """Return value as sha256:<hex>, adding the prefix if missing. Raises ValueError on bad input."""
    if not IMAGE_DIGEST_RE.match(value or ""):
        raise ValueError(f"invalid image digest {value!r}: expected sha256: followed by 64 lowercase hex characters")
    return value if value.startswith("sha256:") else f"sha256:{value}"


def parse_image_ref(value: str):
    """Classify a prompt answer as a tag or a digest. Returns (tag, digest), one of them None."""
    value = (value or "").strip()
    if value.startswith("sha256:") or IMAGE_DIGEST_RE.match(value):
        return None, normalize_image_digest(value)
    return validate_image_tag(value), None


def prompt_image_ref(out=None):
    """Ask for an FCG image tag or digest until a valid one is entered. Returns (tag, digest).

    Prompts go to stderr by default so --dry-run output on stdout stays valid YAML.
    """
    out = out or sys.stderr
    print("An FCG image tag or digest is required. Default values will be added once FCG is "
          "generally available.", file=out)
    while True:
        print("FCG image tag, or digest (sha256:...): ", end="", file=out, flush=True)
        answer = sys.stdin.readline()
        if not answer:
            raise SystemExit("ERROR: no FCG image tag or digest was entered.")
        try:
            return parse_image_ref(answer)
        except ValueError as e:
            print(f"  {e}", file=out)


def apply_overrides(migrated: dict, admission_control_override, image_analyzer_override):
    """Apply --admission-control and --image-analyzer CLI overrides to the migrated values."""
    if admission_control_override is not None:
        fcg = migrated.get("falcon-clusterguard")
        if fcg is not None:
            if "clusterguardController" not in fcg or not isinstance(fcg.get("clusterguardController"), dict):
                fcg["clusterguardController"] = CommentedMap()
            if "admissionControl" not in fcg["clusterguardController"] or not isinstance(fcg["clusterguardController"].get("admissionControl"), dict):
                fcg["clusterguardController"]["admissionControl"] = CommentedMap()
            fcg["clusterguardController"]["admissionControl"]["enabled"] = admission_control_override

    if image_analyzer_override is not None:
        fcg = migrated.get("falcon-clusterguard")
        if fcg is not None:
            if "imageAnalyzer" not in fcg or not isinstance(fcg.get("imageAnalyzer"), dict):
                fcg["imageAnalyzer"] = CommentedMap()
                fcg.yaml_set_comment_before_after_key("imageAnalyzer", before="\n")
            fcg["imageAnalyzer"]["enabled"] = image_analyzer_override


# ---------------------------------------------------------------------------
# Input checks
# ---------------------------------------------------------------------------

class InputError(Exception):
    """A values file can't be migrated. The script prints the message and exits with status 1."""


CHART_KEYS = ("falcon-sensor", "falcon-kac", "falcon-image-analyzer")
CHART_FLAGS = {"falcon-sensor": "--sensor-values", "falcon-kac": "--kac-values", "falcon-image-analyzer": "--iar-values"}

# Top-level keys that only one standalone chart has, used to tell which chart a values file is for.
DISTINCTIVE_KEYS = {
    "falcon-sensor": {"node", "container"},
    "falcon-kac": {
        "admissionControl", "clusterVisibility", "webhookPort", "watcherPort", "webhook", "replicas",
        "falconClientResources", "falconClientNoWebhookResources", "falconWatcherResources", "falconAcResources",
        "falconImageAnalyzerNamespace", "resourceQuota", "autoCertificateUpdate", "autoDeploymentUpdate",
        "certExpiration", "domainName", "clusterName",
    },
    "falcon-image-analyzer": {
        "crowdstrikeConfig", "deployment", "daemonset", "watcher", "replicaCount", "exclusions",
        "privateRegistries", "iarAgentService", "kac", "proxyConfig", "log", "gcp", "azure",
    },
}
# Top-level keys of a falcon-clusterguard values file, which is already migrated.
FCG_KEYS = {"falcon-clusterguard", "nodeSensor", "clusterguardController", "imageAnalyzer"}

FALCON_OPTION_KEYS = {
    "cid", "cloud", "apd", "aph", "app", "trace", "feature", "billing", "tags", "provisioning_token", "backend",
}
# Keys each block can have in the source charts (falcon-platform 1.x and the standalone chart
# values and schemas). Other keys are reported as possible typos. falcon-image-analyzer keys are
# checked in migrate_image_analyzer().
KNOWN_KEYS = {
    (): {"global", "createComponentNamespaces", *CHART_KEYS},
    ("falcon-sensor",): {
        "enabled", "namespaceOverride", "node", "container", "serviceAccount", "testing", "falcon",
        "falconSecret", "secretsStore", "nameOverride", "fullnameOverride", "global",
    },
    ("falcon-sensor", "node"): {
        "enabled", "backend", "clusterName", "gke", "daemonset", "image", "podAnnotations", "podLabels",
        "terminationGracePeriod", "hooks", "cleanupOnly", "openshift",
    },
    ("falcon-sensor", "falcon"): FALCON_OPTION_KEYS,
    ("falcon-kac",): {
        "enabled", "namespaceOverride", "image", "replicas", "webhookPort", "watcherPort", "autoCertificateUpdate",
        "certExpiration", "domainName", "serviceAccount", "falcon", "admissionControl", "falconSecret",
        "secretsStore", "clusterVisibility", "clusterName", "falconImageAnalyzerNamespace", "annotations",
        "labels", "podAnnotations", "podLabels", "tolerations", "affinity", "falconClientResources",
        "falconClientNoWebhookResources", "falconWatcherResources", "falconAcResources", "autoDeploymentUpdate",
        "nameOverride", "fullnameOverride", "webhook", "hostNetwork", "openshift", "dnsPolicy", "resourceQuota",
        "tlsVersionMinimum", "global", "testing",
    },
    ("falcon-kac", "falcon"): FALCON_OPTION_KEYS,
}

# Blocks the script reads keys from, as paths in a falcon-platform values file. Each must be a
# mapping or null.
MAPPING_PATHS = [
    ("global",), ("global", "falcon"),
    ("falcon-sensor",), ("falcon-sensor", "node"), ("falcon-sensor", "node", "image"),
    ("falcon-sensor", "node", "gke"), ("falcon-sensor", "node", "openshift"), ("falcon-sensor", "node", "daemonset"),
    ("falcon-sensor", "container"), ("falcon-sensor", "falcon"), ("falcon-sensor", "falconSecret"),
    ("falcon-sensor", "secretsStore"), ("falcon-sensor", "serviceAccount"),
    ("falcon-kac",), ("falcon-kac", "image"), ("falcon-kac", "admissionControl"), ("falcon-kac", "webhook"),
    ("falcon-kac", "falcon"), ("falcon-kac", "falconSecret"), ("falcon-kac", "secretsStore"),
    ("falcon-kac", "openshift"), ("falcon-kac", "clusterVisibility"), ("falcon-kac", "serviceAccount"),
    ("falcon-image-analyzer",), ("falcon-image-analyzer", "crowdstrikeConfig"), ("falcon-image-analyzer", "image"),
    ("falcon-image-analyzer", "deployment"), ("falcon-image-analyzer", "daemonset"),
    ("falcon-image-analyzer", "openshift"), ("falcon-image-analyzer", "azure"), ("falcon-image-analyzer", "gcp"),
    ("falcon-image-analyzer", "secretsStore"), ("falcon-image-analyzer", "serviceAccount"),
]
# Values the script reads as true/false to decide what to migrate. Each must be a boolean or null.
BOOL_PATHS = [
    ("falcon-sensor", "enabled"), ("falcon-sensor", "node", "enabled"), ("falcon-sensor", "container", "enabled"),
    ("falcon-sensor", "falconSecret", "enabled"), ("falcon-sensor", "secretsStore", "enabled"),
    ("falcon-sensor", "node", "openshift", "enabled"), ("falcon-sensor", "node", "openshift", "createSCC"),
    ("falcon-kac", "enabled"), ("falcon-kac", "admissionControl", "enabled"), ("falcon-kac", "falconSecret", "enabled"),
    ("falcon-kac", "secretsStore", "enabled"), ("falcon-kac", "openshift", "enabled"),
    ("falcon-kac", "openshift", "createSCC"),
    ("falcon-image-analyzer", "enabled"), ("falcon-image-analyzer", "deployment", "enabled"),
    ("falcon-image-analyzer", "daemonset", "enabled"), ("falcon-image-analyzer", "gcp", "enabled"),
    ("falcon-image-analyzer", "secretsStore", "enabled"), ("falcon-image-analyzer", "openshift", "enabled"),
    ("falcon-image-analyzer", "openshift", "createSCC"),
]
# Values the script compares or reads as text. Each must be a string or null.
STRING_PATHS = [
    ("falcon-sensor", "namespaceOverride"), ("falcon-sensor", "node", "clusterName"), ("falcon-kac", "clusterName"),
    ("falcon-image-analyzer", "crowdstrikeConfig", "clusterName"),
    ("falcon-sensor", "node", "image", "pullSecrets"), ("falcon-kac", "image", "pullSecrets"),
    ("falcon-sensor", "serviceAccount", "name"), ("falcon-kac", "serviceAccount", "name"),
    ("falcon-sensor", "falconSecret", "secretName"), ("falcon-kac", "falconSecret", "secretName"),
]


def _describe(value):
    """A short description of a value's type for error messages, such as "a boolean (true)"."""
    if isinstance(value, bool):
        return f"a boolean ({str(value).lower()})"
    if isinstance(value, (int, float)):
        return f"a number ({value})"
    if isinstance(value, str):
        return f"a string ({value!r})"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "a mapping"
    return type(value).__name__


def parse_values(yaml_instance, stream, source):
    """Parse a values document and return its top-level mapping. Raises InputError if it isn't one."""
    try:
        data = yaml_instance.load(stream)
    except YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f", line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        problem = getattr(e, "problem", None) or str(e).strip().splitlines()[0]
        raise InputError(f"{source}{where}: invalid YAML: {problem}") from None
    if data is None:
        raise InputError(
            f"{source}: no values found (the file is empty or only has comments). If the release uses only "
            "chart defaults, export them with: helm get values <release> -n <namespace> --all -o yaml"
        )
    if not isinstance(data, dict):
        raise InputError(f"{source}: expected a mapping of values at the top level, got {_describe(data)}")
    return data


def load_values(yaml_instance, path):
    """Load a values file. Raises InputError if it can't be read or isn't a mapping of values."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return parse_values(yaml_instance, f, path)
    except FileNotFoundError:
        raise InputError(f"{path}: file not found") from None
    except IsADirectoryError:
        raise InputError(f"{path}: is a directory, not a values file") from None
    except PermissionError:
        raise InputError(f"{path}: permission denied") from None
    except UnicodeDecodeError:
        raise InputError(f"{path}: not a UTF-8 text file") from None


def _looks_like(doc):
    """Standalone charts whose distinctive top-level keys appear in doc."""
    return [chart for chart, keys in DISTINCTIVE_KEYS.items() if keys & set(doc)]


def _check_not_migrated(doc, source):
    fcg_keys = sorted(FCG_KEYS & set(doc))
    if fcg_keys:
        raise InputError(
            f"{source} looks like falcon-clusterguard values (it has a top-level {fcg_keys[0]} key), which are "
            "already migrated. Pass the values file from before the migration."
        )


def check_platform_file(doc, source):
    """Raise InputError if doc isn't a falcon-platform values file."""
    _check_not_migrated(doc, source)
    if not any(k in doc for k in CHART_KEYS):
        charts = _looks_like(doc)
        if charts:
            raise InputError(
                f"{source} looks like a standalone {charts[0]} values file, not a falcon-platform values file. "
                f"Use individual chart mode instead: --sensor-values <falcon-sensor values file>, plus "
                "--kac-values and --iar-values for the other charts."
            )


def check_chart_file(doc, source, chart):
    """Raise InputError if doc isn't a standalone values file for chart."""
    _check_not_migrated(doc, source)
    platform_keys = [k for k in CHART_KEYS if k in doc]
    if platform_keys:
        raise InputError(
            f"{source} looks like a falcon-platform values file (it has a top-level {platform_keys[0]} key). "
            f"Use --platform-values {source} instead."
        )
    if not DISTINCTIVE_KEYS[chart] & set(doc):
        others = [c for c in _looks_like(doc) if c != chart]
        if others:
            raise InputError(
                f"{source} looks like a {others[0]} values file, not a {chart} values file. "
                f"Pass it with {CHART_FLAGS[others[0]]}."
            )


def check_structure(values):
    """Raise InputError listing every block or value whose type the migration can't use."""
    problems = []

    def check(paths, ok, expected):
        for path in paths:
            try:
                value = _lookup(values, path)
            except KeyError:
                continue
            if value is not None and not ok(value):
                problems.append(f"{'.'.join(path)} must be {expected}, got {_describe(value)}")

    check(MAPPING_PATHS, lambda v: isinstance(v, dict), "a mapping")
    check(BOOL_PATHS, lambda v: isinstance(v, bool), "true or false")
    check(STRING_PATHS, lambda v: isinstance(v, str), "a string")
    if problems:
        raise InputError("these values can't be migrated:\n" + "\n".join(f"  - {p}" for p in problems))


def unknown_key_warnings(values):
    """Warnings for keys that the source charts don't define, which are usually typos."""
    warnings = []
    for path, known in KNOWN_KEYS.items():
        try:
            block = _lookup(values, path)
        except KeyError:
            continue
        if not isinstance(block, dict):
            continue
        for key in block:
            if key in known:
                continue
            dotted = ".".join(path + (key,))
            if path and path[-1] == "falcon":
                warnings.append(
                    f"{dotted} is not a falconctl option. It was copied to falcon-clusterguard.falcon as-is; "
                    "check it for a typo."
                )
            else:
                chart = path[0] if path else "falcon-platform"
                warnings.append(f"{dotted} is not a {chart} value, so it was omitted. Check it for a typo.")
    return warnings


def default_fcg_chart():
    """The falcon-clusterguard chart in this repository, or None when the script runs elsewhere."""
    chart = Path(__file__).resolve().parents[2] / "helm-charts" / "falcon-clusterguard"
    return str(chart) if (chart / "Chart.yaml").is_file() else None


def validate_with_helm(migrated, chart, yaml_instance):
    """Render the migrated falcon-clusterguard values with helm template.

    Returns None if they render, or helm's error output if they don't. The falcon-clusterguard block is
    rendered on its own, with global.* from the migrated file.
    """
    fcg = migrated.get("falcon-clusterguard") or {}
    values = CommentedMap()
    if migrated.get("global"):
        values["global"] = migrated["global"]
    for k, v in fcg.items():
        if k != "enabled":
            values[k] = v
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml_instance.dump(values, f)
    try:
        result = subprocess.run(
            ["helm", "template", "fcg-validate", chart, "-n", fcg.get("namespaceOverride") or "falcon-system",
             "-f", f.name],
            capture_output=True, text=True,
        )
    finally:
        os.unlink(f.name)
    if result.returncode == 0:
        return None
    output = result.stderr.strip() or result.stdout.strip()
    return "\n".join(l for l in output.splitlines() if l.strip() and "Use --debug flag" not in l)


# ---------------------------------------------------------------------------
# Migration logic
# ---------------------------------------------------------------------------

def migrate_image_analyzer(iar: dict, fcg: CommentedMap, global_cid, warnings: list) -> CommentedMap:
    """Map standalone falcon-image-analyzer values to falcon-clusterguard.imageAnalyzer.*.

    Settings that FCG keeps outside imageAnalyzer (CID, image pull auth, OpenShift) are
    folded into fcg with the lowest precedence, after sensor and kac. The cluster name is
    handled in migrate().
    """
    ia = CommentedMap()
    # falcon-platform defaults falcon-image-analyzer.enabled=true, so a block without
    # an explicit enabled: false was deployed.
    ia["enabled"] = iar.get("enabled") is not False
    # The standalone chart's schema requires exactly one of deployment/daemonset. FCG defaults
    # to deployment, so mode is only written for DaemonSet installs.
    daemonset = bool(get_nested(iar, "daemonset", "enabled"))
    if daemonset:
        ia["mode"] = "daemonset"

    def copied(key, source):
        return key in source and (daemonset or key not in IAR_DAEMONSET_ONLY_KEYS)

    cs_config = iar.get("crowdstrikeConfig") or {}
    for k in IAR_KEYS:
        if k == "crowdstrikeConfig":
            ia_cs = CommentedMap(
                (ck, copy_value(cs_config[ck])) for ck in IAR_CROWDSTRIKE_CONFIG_KEYS if copied(ck, cs_config)
            )
            if ia_cs:
                ia[k] = ia_cs
        elif copied(k, iar):
            val = copy_value(iar[k])
            ia[k] = val

    # crowdstrikeConfig.cid → falcon.cid, unless a CID is already set for FCG
    iar_cid = cs_config.get("cid")
    if iar_cid:
        current_cid = (fcg.get("falcon") or {}).get("cid") or global_cid
        if not current_cid:
            if "falcon" not in fcg:
                fcg.insert(list(fcg.keys()).index("image") + 1, "falcon", CommentedMap())
            fcg["falcon"]["cid"] = iar_cid
        elif current_cid != iar_cid:
            warnings.append(
                "falcon-image-analyzer.crowdstrikeConfig.cid differs from the CID used for FCG. "
                "The image analyzer will use the FCG CID. Review manually."
            )

    if cs_config.get("existingSecret"):
        warnings.append(
            f"falcon-image-analyzer.crowdstrikeConfig.existingSecret='{cs_config['existingSecret']}' "
            "has no FCG equivalent and was omitted. FCG reads image analyzer credentials from "
            "falconSecret (keys AGENT_CLIENT_ID, AGENT_CLIENT_SECRET, AGENT_CID) or "
            "imageAnalyzer.crowdstrikeConfig.clientID/clientSecret."
        )
    if ia.get("crowdstrikeConfig", {}).get("clientID") and get_nested(fcg, "falconSecret", "enabled"):
        warnings.append(
            "falcon-clusterguard.falconSecret is enabled, so imageAnalyzer.crowdstrikeConfig.clientID/"
            "clientSecret must be removed. Add AGENT_CLIENT_ID and AGENT_CLIENT_SECRET to the secret instead."
        )

    # image — the image analyzer runs from the FCG image. Carry over pull auth only if
    # FCG has none, since FCG rejects pullSecret and registryConfigJSON together.
    iar_image = iar.get("image") or {}
    fcg_image = fcg["image"]
    if not any(fcg_image.get(f) for f in ("pullSecret", "registryConfigJSON")):
        for field in ("pullSecret", "registryConfigJSON"):
            if iar_image.get(field):
                fcg_image[field] = iar_image[field]
                break
    dropped_image = [f for f in ("repository", "tag", "digest") if iar_image.get(f)]
    if dropped_image:
        warnings.append(
            f"{', '.join('falcon-image-analyzer.image.' + f for f in dropped_image)} omitted — the "
            "image analyzer now runs from the FCG image (falcon-clusterguard.image.*)."
        )

    # openshift — merge at fcg root with the lowest precedence; sccName → iarSCCName
    iar_os = iar.get("openshift") or {}
    if iar_os:
        fcg_os = fcg.get("openshift") or CommentedMap()
        for k in ("enabled", "createSCC"):
            if k in iar_os and fcg_os.get(k) is None:
                fcg_os[k] = iar_os[k]
        if iar_os.get("sccName") and not fcg_os.get("iarSCCName"):
            fcg_os["iarSCCName"] = iar_os["sccName"]
        if fcg_os.get("enabled") or fcg_os.get("createSCC") is False or fcg_os.get("iarSCCName"):
            fcg["openshift"] = fcg_os

    # Cloud provider settings live at the FCG top level: azure.* moves as-is, and
    # gcp.enabled (the GKE metadata-server init container) becomes gke.enabled.
    if "azure" in iar:
        azure = copy_value(iar["azure"])
        insert_before(fcg, "azure", azure, before="nodeSensor")
    if get_nested(iar, "gcp", "enabled"):
        if "gke" not in fcg:
            insert_before(fcg, "gke", CommentedMap(), before="nodeSensor")
        if "enabled" not in fcg["gke"]:
            fcg["gke"].insert(0, "enabled", True)
        else:
            fcg["gke"]["enabled"] = True

    if get_nested(iar, "secretsStore", "enabled"):
        warnings.append(
            "falcon-image-analyzer.secretsStore was omitted. FCG uses one falcon-clusterguard.secretsStore "
            "for all components; the image analyzer reads falcon-client-id and falcon-client-secret from "
            "the same store. Review manually."
        )

    for k, v in iar.items():
        if v and k not in IAR_KEYS and k not in IAR_HANDLED_KEYS:
            warnings.append(f"falcon-image-analyzer.{k} has no FCG equivalent and was omitted.")
    for k, v in cs_config.items():
        if v and k not in IAR_CROWDSTRIKE_CONFIG_KEYS and k not in IAR_HANDLED_CROWDSTRIKE_CONFIG_KEYS:
            warnings.append(f"falcon-image-analyzer.crowdstrikeConfig.{k} has no FCG equivalent and was omitted.")

    return ia


def migrate(values: dict, warnings: list,
            fcg_image_repo: str = None,
            fcg_image_tag: str = None,
            fcg_image_digest: str = None) -> dict:
    check_structure(values)
    warnings.extend(unknown_key_warnings(values))

    fcg = CommentedMap()
    fcg["enabled"] = True

    # ---- falcon-sensor → falcon-clusterguard.nodeSensor ---------------------

    sensor = values.get("falcon-sensor", {}) or {}
    sensor_node = sensor.get("node", {}) or {}
    kac = values.get("falcon-kac", {}) or {}
    iar = values.get("falcon-image-analyzer", {}) or {}

    # namespaceOverride — pick falcon-sensor's if set, else default falcon-system
    ns_override = sensor.get("namespaceOverride") or "falcon-system"
    fcg["namespaceOverride"] = ns_override

    # clusterName — top level in FCG, shared by every component. falcon-sensor.node takes
    # precedence, then falcon-kac, then falcon-image-analyzer.crowdstrikeConfig.
    cluster_names = [
        (source, name) for source, name in (
            ("falcon-sensor.node.clusterName", sensor_node.get("clusterName")),
            ("falcon-kac.clusterName", kac.get("clusterName")),
            ("falcon-image-analyzer.crowdstrikeConfig.clusterName", get_nested(iar, "crowdstrikeConfig", "clusterName")),
        ) if name
    ]
    if cluster_names:
        kept_source, kept_name = cluster_names[0]
        fcg["clusterName"] = copy_value(kept_name)
        for source, name in cluster_names[1:]:
            if name != kept_name:
                warnings.append(
                    f"{source}='{name}' conflicts with {kept_source}='{kept_name}'. "
                    f"The {kept_source} value has been kept. Review manually."
                )

    # image — set the FCG repository, tag, and digest, then carry over pull auth and pull policy
    # from falcon-sensor.node.image or falcon-kac.image (sensor takes precedence).
    fcg_image = CommentedMap()
    if fcg_image_repo:
        fcg_image["repository"] = fcg_image_repo
    if fcg_image_tag:
        fcg_image["tag"] = fcg_image_tag
    if fcg_image_digest:
        fcg_image["digest"] = fcg_image_digest

    sensor_image = get_nested(sensor, "node", "image") or {}
    kac_image = get_nested(values.get("falcon-kac") or {}, "image") or {}
    # Pull auth comes from one source (sensor first), because FCG rejects pullSecret and
    # registryConfigJSON together. Both source charts name the pull secret pullSecrets.
    auth_image = sensor_image if (sensor_image.get("pullSecrets") or sensor_image.get("registryConfigJSON")) else kac_image
    if auth_image.get("pullSecrets"):
        fcg_image["pullSecret"] = auth_image["pullSecrets"]
    elif auth_image.get("registryConfigJSON"):
        fcg_image["registryConfigJSON"] = auth_image["registryConfigJSON"]
    pull_policy = sensor_image.get("pullPolicy") or kac_image.get("pullPolicy")
    if pull_policy:
        fcg_image["pullPolicy"] = pull_policy
    # A digest identifies the old sensor or kac image, not the FCG image, and FCG would use it
    # in place of the tag.
    dropped_digests = [
        f"{chart}.image.digest" for chart, image in (("falcon-sensor.node", sensor_image), ("falcon-kac", kac_image))
        if image.get("digest")
    ]
    if dropped_digests:
        warnings.append(
            f"{', '.join(dropped_digests)} omitted — the digest belongs to the old image. "
            "Pass --fcg-image-digest to pin the FCG image by digest."
        )

    fcg["image"] = fcg_image

    # The node sensor was not deployed before migration if there are no falcon-sensor values
    # at all, or if falcon-sensor.enabled (falcon-platform) or falcon-sensor.node.enabled is
    # false. FCG defaults nodeSensor.enabled to true, so it must be disabled explicitly.
    if not sensor:
        node_disabled_reason = "no falcon-sensor values were provided"
    elif sensor.get("enabled") is False:
        node_disabled_reason = "falcon-sensor.enabled is false"
    elif sensor_node.get("enabled") is False:
        node_disabled_reason = "falcon-sensor.node.enabled is false"
    else:
        node_disabled_reason = None

    if sensor_node:
        node = CommentedMap()

        direct_node_keys = [
            "enabled", "daemonset", "podAnnotations", "podLabels",
            "terminationGracePeriod", "hooks", "cleanupOnly",
        ]
        for k in direct_node_keys:
            if k in sensor_node:
                node[k] = copy_value(sensor_node[k])

        # node.gke.* (autopilot, allowlist versions) moves to the FCG top level, shared with
        # the image analyzer. Assigned before fcg["nodeSensor"] so it sits ahead of nodeSensor
        # in the output.
        if "gke" in sensor_node:
            gke = copy_value(sensor_node["gke"])
            fcg["gke"] = gke

        # backend is deprecated — omit it, add warning and comment
        if sensor_node.get("backend"):
            warnings.append(
                "falcon-sensor.node.backend is deprecated in FCG and has been omitted."
            )

        # serviceAccount lives at falcon-sensor top level, maps to nodeSensor.serviceAccount.
        # Carry the old name forward explicitly to avoid breaking external RBAC.
        sensor_sa = copy_value(sensor.get("serviceAccount") or {})
        if not sensor_sa.get("name"):
            sensor_sa["name"] = "crowdstrike-falcon-sa"
        node["serviceAccount"] = sensor_sa

        fcg["nodeSensor"] = node
    elif not node_disabled_reason:
        warnings.append(
            "falcon-sensor.node block not found — falcon-clusterguard.nodeSensor not populated. "
            "Add node configuration manually."
        )

    if node_disabled_reason:
        if "nodeSensor" not in fcg:
            fcg["nodeSensor"] = CommentedMap()
        if "enabled" in fcg["nodeSensor"]:
            fcg["nodeSensor"]["enabled"] = False
        else:
            fcg["nodeSensor"].insert(0, "enabled", False)
        warnings.append(
            f"falcon-clusterguard.nodeSensor.enabled set to false because {node_disabled_reason}. "
            "Set it to true to deploy the FCG node sensor."
        )

    # ---- falcon-kac → falcon-clusterguard.clusterguardController ----------

    if kac:
        cluster = CommentedMap()

        # Direct moves — key name unchanged, parent moves to clusterguardController.*
        direct_cluster_keys = [
            "webhookPort", "watcherPort", "autoCertificateUpdate", "certExpiration",
            "domainName", "hostNetwork", "dnsPolicy", "tolerations", "affinity",
            "annotations", "labels", "podAnnotations", "podLabels",
            "autoDeploymentUpdate", "tlsVersionMinimum",
        ]
        for k in direct_cluster_keys:
            if k in kac:
                cluster[k] = copy_value(kac[k])

        # falcon-kac.enabled is no longer mapped — the clusterguard controller always runs in FCG.

        # falcon-kac.admissionControl.enabled → clusterguardController.admissionControl.enabled
        # Controls the ValidatingWebhookConfiguration + webhook Service.
        # Old default: true. New default: false. Always write explicitly to preserve behavior.
        # A disabled falcon-kac (falcon-platform falcon-kac.enabled=false) had no webhook at all.
        kac_ac = kac.get("admissionControl", {}) or {}
        if kac.get("enabled") is False:
            ac_enabled = False
            warnings.append(
                "falcon-kac.enabled is false, so falcon-clusterguard.clusterguardController.admissionControl.enabled "
                "is set to false. The clusterguard controller still runs for cluster visibility."
            )
        else:
            ac_enabled = kac_ac.get("enabled", True)  # old kac default was true
        if "admissionControl" not in cluster:
            cluster["admissionControl"] = CommentedMap()
        cluster["admissionControl"]["enabled"] = ac_enabled

        # webhook block
        kac_webhook = kac.get("webhook", {}) or {}
        if kac_webhook:
            wh = copy_value(kac_webhook)
            cluster["webhook"] = wh

        # resourceQuota
        if "resourceQuota" in kac:
            cluster["resourceQuota"] = copy_value(kac["resourceQuota"])

        # Resource renames — add EOL comment showing the old key name
        resources = CommentedMap()
        for old_key, (new_key, eol_comment) in RESOURCE_RENAMES.items():
            if old_key in kac:
                val = copy_value(kac[old_key])
                resources[new_key] = val
                resources.yaml_add_eol_comment(eol_comment, key=new_key)
        if resources:
            cluster["resources"] = resources

        # serviceAccount → clusterguardController.serviceAccount.
        # Carry the old name forward explicitly to avoid breaking external RBAC.
        kac_sa = copy_value(kac.get("serviceAccount") or {})
        if not kac_sa.get("name"):
            kac_sa["name"] = "falcon-kac-sa"
        cluster["serviceAccount"] = kac_sa

        fcg["clusterguardController"] = cluster
        fcg.yaml_set_comment_before_after_key("clusterguardController", before="\n")

        # clusterVisibility — now lives under clusterguardController.visibility.*
        if "clusterVisibility" in kac:
            visibility = copy_value(kac["clusterVisibility"])
            cluster["visibility"] = visibility

        # falconImageAnalyzerNamespace is dropped — the image analyzer now runs in the FCG namespace.
        if kac.get("falconImageAnalyzerNamespace"):
            warnings.append(
                "falcon-kac.falconImageAnalyzerNamespace has been omitted — the image analyzer "
                "now runs in the FCG namespace."
            )

        # falconSecret — the sensor value takes precedence (set after this block)
        if kac.get("falconSecret") and sensor.get("falconSecret") and kac["falconSecret"] != sensor["falconSecret"]:
            warnings.append(
                "falconSecret found in both falcon-sensor and falcon-kac. "
                "The falcon-sensor value has been used. Review manually."
            )

        # falcon.* (CID, cloud, trace, etc.) — set on fcg root, NOT cluster
        # (handled below after the kac block to merge with sensor values)

    else:
        warnings.append(
            "falcon-kac block not found — falcon-clusterguard.clusterguardController not populated. "
            "Add clusterguardController configuration manually."
        )

    # falconSecret — prefer falcon-sensor's; fall back to falcon-kac's
    falcon_secret = get_nested(sensor, "falconSecret") or (values.get("falcon-kac") or {}).get("falconSecret")
    if falcon_secret:
        fcg["falconSecret"] = copy_value(falcon_secret)

    # falcon.* — merge sensor and kac values at fcg root (sensor takes precedence).
    # Inserted right after `image` to mirror where falcon.* appeared in the source
    # (falcon-sensor comes before falcon-kac in the platform values file, and
    # falcon.* appears near the top of each chart's values block).
    # CommentedMap.insert() lets us control position rather than always appending.
    sensor_falcon = sensor.get("falcon") or {}
    kac_falcon    = (values.get("falcon-kac") or {}).get("falcon") or {}
    merged_falcon = CommentedMap(
        (k, copy_value(v)) for k, v in kac_falcon.items() if k not in COMPONENT_FALCON_KEYS
    )
    merged_falcon.update({k: v for k, v in sensor_falcon.items() if v is not None})
    if merged_falcon:
        # Insert after "image" (index 2: enabled=0, namespaceOverride=1, image=2)
        image_idx = list(fcg.keys()).index("image") if "image" in fcg else len(fcg) - 1
        fcg.insert(image_idx + 1, "falcon", merged_falcon)

    # trace, feature, and tags are per component in FCG. The shared falcon.* values come from
    # falcon-sensor, as the node sensor used them; falcon-kac values that differ go to
    # clusterguardController.falcon so the controller keeps them without changing the node sensor.
    kac_component_falcon = CommentedMap(
        (k, copy_value(kac_falcon[k])) for k in COMPONENT_FALCON_KEYS
        if kac_falcon.get(k) not in (None, "")
        and kac_falcon[k] != (sensor_falcon.get(k) or FCG_FALCON_DEFAULTS.get(k))
    )
    if kac_component_falcon and "clusterguardController" in fcg:
        cluster = fcg["clusterguardController"]
        cluster.insert(list(cluster.keys()).index("admissionControl") + 1, "falcon", kac_component_falcon)

    # secretsStore — prefer sensor value; fall back to kac
    sensor_csi = sensor.get("secretsStore") or {}
    kac_csi = (values.get("falcon-kac") or {}).get("secretsStore") or {}
    merged_csi = copy_value(kac_csi)
    merged_csi.update({k: v for k, v in sensor_csi.items() if v is not None})
    if any(v for v in merged_csi.values() if v):
        fcg["secretsStore"] = merged_csi

    # openshift — prefer sensor value; fall back to kac (both map to fcg root)
    sensor_os = get_nested(sensor, "node", "openshift") or {}
    kac_os = (values.get("falcon-kac") or {}).get("openshift") or {}
    merged_os = copy_value(kac_os)
    merged_os.update({k: v for k, v in sensor_os.items() if v is not None})
    if merged_os.get("enabled") or merged_os.get("createSCC") is False:
        fcg["openshift"] = merged_os

    # ---- falcon-image-analyzer → falcon-clusterguard.imageAnalyzer ---------

    if iar:
        fcg["imageAnalyzer"] = migrate_image_analyzer(
            iar, fcg, get_nested(values, "global", "falcon", "cid"), warnings,
        )
        fcg.yaml_set_comment_before_after_key("imageAnalyzer", before="\n")

    # ---- Build output values -----------------------------------------------

    out = CommentedMap()

    # Preserve top-level keys that pass through unchanged
    preserved_top = ["global", "createComponentNamespaces"]
    for k in preserved_top:
        if k in values:
            out[k] = copy_value(values[k])

    # falcon-sensor: retain only if container mode is active.
    # If container mode is falsy, remove the block entirely — falcon-platform
    # defaults falcon-sensor.enabled=false, so no stub needed.
    sensor_container = sensor.get("container", {}) or {}
    if sensor_container and sensor_container.get("enabled"):
        # Container mode active — keep only the container block, drop all node.* values.
        sensor_out = CommentedMap()
        sensor_out["container"] = copy_value(sensor_container)
        # Preserve top-level falcon-sensor keys that apply to container mode
        for k in ("enabled", "namespaceOverride", "falcon", "falconSecret",
                  "serviceAccount", "secretsStore", "openshift"):
            if k in sensor:
                sensor_out[k] = copy_value(sensor[k])
        out["falcon-sensor"] = sensor_out
        out.yaml_set_comment_before_after_key(
            "falcon-sensor",
            before=(
                "\nRetained for container sensor (container.enabled=true)."
                "\nfalcon-sensor.node is no longer supported — replaced by falcon-clusterguard.nodeSensor.*"
            ),
        )
    # else: falcon-sensor omitted entirely — falcon-platform defaults handle it

    # Comments prepended to falcon-clusterguard noting the replaced charts.
    sensor_node_deprecated_note = "falcon-sensor.node is deprecated — replaced by falcon-clusterguard.nodeSensor.*\n"
    kac_deprecated_note = "falcon-kac is deprecated — replaced by falcon-clusterguard.clusterguardController.*\n"
    iar_deprecated_note = "falcon-image-analyzer is deprecated — replaced by falcon-clusterguard.imageAnalyzer.*\n\n"

    # falcon-clusterguard: the new chart, separated by a blank line from any keys above it
    out["falcon-clusterguard"] = fcg
    out.yaml_set_comment_before_after_key(
        "falcon-clusterguard",
        before=("\n" if len(out) > 1 else "") + sensor_node_deprecated_note + kac_deprecated_note + iar_deprecated_note,
    )

    return out


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
# ruamel attaches each comment to whatever token precedes it, so copied values lose comments that
# belong to keys copied one by one and pick up blank lines from neighboring blocks. Copies are
# stripped (copy_value) and comments are rebuilt from line numbers instead: a comment on a key's
# line is that key's end-of-line comment, a full-line comment belongs to the next key or list
# item, and comments above the first key are the file header. carry_comments() then attaches each
# comment where its key ended up in the migrated values.

F = ("falcon-clusterguard",)
CTRL = F + ("clusterguardController",)
IA = F + ("imageAnalyzer",)

# (source path, destination paths, exact). A comment at a source path goes to the destination of
# the longest matching source prefix, with the rest of its path appended. exact rules match only
# their own path. An empty destination list means the key is dropped.
COMMENT_RULES = [
    (("global",), [("global",)], False),
    (("createComponentNamespaces",), [("createComponentNamespaces",)], False),
    # falcon-sensor
    (("falcon-sensor",), [F + ("nodeSensor",)], True),
    (("falcon-sensor", "node"), [F + ("nodeSensor",)], False),
    (("falcon-sensor", "node", "clusterName"), [F + ("clusterName",)], False),
    (("falcon-sensor", "node", "gke"), [F + ("gke",)], False),
    (("falcon-sensor", "node", "openshift"), [F + ("openshift",)], False),
    (("falcon-sensor", "node", "backend"), [], False),
    (("falcon-sensor", "node", "image"), [F + ("image",)], False),
    (("falcon-sensor", "node", "image", "pullSecrets"), [F + ("image", "pullSecret")], False),
    (("falcon-sensor", "namespaceOverride"), [F + ("namespaceOverride",), ("falcon-sensor", "namespaceOverride")], False),
    (("falcon-sensor", "serviceAccount"), [F + ("nodeSensor", "serviceAccount"), ("falcon-sensor", "serviceAccount")], False),
    (("falcon-sensor", "container"), [("falcon-sensor", "container")], False),
    (("falcon-sensor", "enabled"), [("falcon-sensor", "enabled")], False),
] + [
    (("falcon-sensor", k), [F + (k,), ("falcon-sensor", k)], False)
    for k in ("falcon", "falconSecret", "secretsStore", "openshift")
] + [
    # falcon-kac: children move under clusterguardController unless a rule below says otherwise
    (("falcon-kac",), [CTRL], False),
    (("falcon-kac", "clusterVisibility"), [CTRL + ("visibility",)], False),
    (("falcon-kac", "clusterName"), [F + ("clusterName",)], False),
    (("falcon-kac", "image"), [F + ("image",)], False),
    (("falcon-kac", "image", "pullSecrets"), [F + ("image", "pullSecret")], False),
] + [
    (("falcon-kac", old), [CTRL + ("resources", new)], False) for old, (new, _) in RESOURCE_RENAMES.items()
] + [
    (("falcon-kac", k), [F + (k,)], False) for k in ("falcon", "falconSecret", "secretsStore", "openshift")
] + [
    (("falcon-kac", "falcon", k), [CTRL + ("falcon", k), F + ("falcon", k)], False) for k in COMPONENT_FALCON_KEYS
] + [
    (("falcon-kac", k), [], False)
    for k in ("enabled", "replicas", "falconImageAnalyzerNamespace", "nameOverride", "fullnameOverride", "testing",
              "global")
] + [
    # falcon-image-analyzer: children move under imageAnalyzer unless a rule below says otherwise
    (("falcon-image-analyzer",), [IA], False),
    (("falcon-image-analyzer", "crowdstrikeConfig", "clusterName"), [F + ("clusterName",)], False),
    (("falcon-image-analyzer", "crowdstrikeConfig", "cid"), [F + ("falcon", "cid")], False),
    (("falcon-image-analyzer", "image"), [F + ("image",)], False),
    (("falcon-image-analyzer", "openshift"), [F + ("openshift",)], False),
    (("falcon-image-analyzer", "openshift", "sccName"), [F + ("openshift", "iarSCCName")], False),
    (("falcon-image-analyzer", "azure"), [F + ("azure",)], False),
    (("falcon-image-analyzer", "gcp"), [F + ("gke",)], False),
    (("falcon-image-analyzer", "daemonset"), [IA + ("mode",)], True),
] + [
    (("falcon-image-analyzer", k), [], False)
    for k in ("deployment", "secretsStore", "kac", "namespaceOverride", "global", "testing")
] + [
    # The image tag, digest, and repository are set for FCG, so comments about the old image are dropped.
    ((chart, "image", k), [], False)
    for chart in ("falcon-kac", "falcon-image-analyzer") for k in ("repository", "tag", "digest")
] + [
    (("falcon-sensor", "node", "image", k), [], False) for k in ("repository", "tag", "digest")
]


def _comment_tokens(obj, found):
    if isinstance(obj, CommentToken):
        found[(obj.start_mark.line, obj.start_mark.column, obj.value)] = obj
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _comment_tokens(item, found)


def extract_comments(root, prefix=()):
    """Read the comments of a loaded values document.

    Returns (header, notes, unplaced): header is the list of comment lines above the first key,
    notes maps each key or list-item path (prefixed with prefix) to {"before": [...], "eol": str},
    and unplaced lists (path, text) for comments after the last key.
    """
    elements = []  # (line, column, path), one per map key and list item
    tokens = {}

    def walk(node, path):
        if not isinstance(node, (CommentedMap, CommentedSeq)):
            return
        _comment_tokens(node.ca.comment, tokens)
        _comment_tokens(list(node.ca.items.values()), tokens)
        _comment_tokens(getattr(node.ca, "end", None), tokens)
        if isinstance(node, CommentedMap):
            for k, v in node.items():
                if node.lc.key(k) is not None:
                    line, col = node.lc.key(k)
                    elements.append((line, col, path + (k,)))
                walk(v, path + (k,))
        else:
            for i, v in enumerate(node):
                if node.lc.item(i) is not None:
                    line, col = node.lc.item(i)
                    elements.append((line, col - 2, path + (i,)))  # the "- " is two columns left of the item
                walk(v, path + (i,))

    walk(root, prefix)
    elements.sort(key=lambda e: (e[0], e[1]))

    lines = {}  # (line, column) -> comment text, one per physical comment line
    for (line, col, value), _ in sorted(tokens.items()):
        segments = value.split("\n")
        # A token's start mark is its first comment, even when the value starts with the newline
        # that ends the previous line, so line numbers count from that segment.
        first = next((i for i, seg in enumerate(segments) if seg.strip().startswith("#")), None)
        if first is None:
            continue
        for i, segment in enumerate(segments[first:], first):
            text = segment.strip()
            if text.startswith("#"):
                seg_col = col if i == first else len(segment) - len(segment.lstrip())
                lines[(line + i - first, seg_col)] = text

    # Comments above the first key are the file header, except a block directly above the first key
    # (no blank line in between) that doesn't start at the top of the file: that block is the key's.
    first_line = elements[0][0] if elements else None
    comment_lines = {line for line, _ in lines}
    block_start = first_line
    while block_start is not None and block_start - 1 in comment_lines:
        block_start -= 1
    header_end = first_line if block_start == 0 else block_start

    header, notes, unplaced = [], {}, []
    for (line, col), text in sorted(lines.items()):
        on_line = [e for e in elements if e[0] == line and e[1] < col]
        if on_line:
            note = notes.setdefault(max(on_line, key=lambda e: e[1])[2], {"before": [], "eol": None})
            note["eol"] = text if not note["eol"] else f"{note['eol']} {text}"
            continue
        following = [e for e in elements if e[0] > line]
        if not following:
            unplaced.append(("<end of file>", text))
        elif line < header_end:
            header.append(text)
        else:
            notes.setdefault(following[0][2], {"before": [], "eol": None})["before"].append(text)
    return header, notes, unplaced


def _lookup(node, path):
    for k in path:
        if isinstance(node, dict) and k in node:
            node = node[k]
        elif isinstance(node, list) and isinstance(k, int) and k < len(node):
            node = node[k]
        else:
            raise KeyError(path)
    return node


def _plain(value):
    return json.loads(json.dumps(value, default=str))


def _comment_destinations(path):
    """Destination paths for a comment at source path, and whether an exact rule matched.

    An exact rule renames one key into another, so its comment is kept even though the value's
    form changes (for example falcon-image-analyzer.daemonset becoming imageAnalyzer.mode).
    """
    best = None
    for rule in COMMENT_RULES:
        src, dsts, exact = rule
        if path[:len(src)] == src and (not exact or len(path) == len(src)):
            if best is None or len(src) > len(best[0]):
                best = rule
    if best is None:
        return [], False
    src, dsts, exact = best
    return [dst + path[len(src):] for dst in dsts], exact


def _output_indent(out, path):
    """Column at which a key or list item at path is written (mapping indent 2, list offset 2)."""
    col, node = 0, out
    for depth, k in enumerate(path):
        if depth == len(path) - 1:
            return col
        node = node[k]
        col += 2 if isinstance(node, (dict, list)) else 0
    return col


def _add_before(parent, key, comments, indent):
    entry = parent.ca.items.setdefault(key, [None, [], None, None])
    if entry[1] is None:
        entry[1] = []
    existing = {t.value.strip() for t in entry[1]}
    entry[1].extend(CommentToken(c + "\n", CommentMark(indent)) for c in comments if c not in existing)


def _add_eol(parent, key, comment):
    entry = parent.ca.items.get(key) or []
    index = 0 if isinstance(parent, CommentedSeq) else 2
    current = entry[index] if len(entry) > index else None
    current = current.value.strip() if isinstance(current, CommentToken) else ""
    if comment in current:
        return
    text = f"{current} — {comment.lstrip('#').strip()}" if current else comment
    parent.yaml_add_eol_comment(text, key=key)


def comment_sources(values):
    """The (document, path prefix) pairs to read comments from, for carry_comments().

    A falcon-platform values file is one document. Values combined from standalone chart files
    have no line numbers of their own, so each chart file is read separately.
    """
    if isinstance(values, CommentedMap) and all(values.lc.key(k) is not None for k in values):
        return [(values, ())]
    return [(v, (k,)) for k, v in values.items() if isinstance(v, CommentedMap)]


def carry_comments(sources, out, warnings):
    """Attach the comments of the source values to their keys' new locations in out.

    sources is a list of (loaded document, path prefix) pairs: one (values, ()) for a falcon-platform
    values file, or one per standalone chart values file, such as (sensor_values, ("falcon-sensor",)).
    A comment is attached only where its key still exists with the same value, so it isn't left
    describing a value the migration changed. Containers moved as a whole keep their comments.
    Comments that can't be placed are listed in a warning.
    """
    header, unplaced = [], []
    for root, prefix in sources:
        src_header, notes, src_unplaced = extract_comments(root, prefix)
        header += src_header
        unplaced += src_unplaced
        for path, note in notes.items():
            texts = note["before"] + ([note["eol"]] if note["eol"] else [])
            try:
                value = _lookup(root, path[len(prefix):])
            except KeyError:
                continue
            placed = False
            destinations, exact = _comment_destinations(path)
            for dst in destinations:
                try:
                    new_value = _lookup(out, dst)
                except KeyError:
                    continue
                moved_container = isinstance(value, (dict, list)) and isinstance(new_value, (dict, list))
                if not (exact or moved_container) and _plain(value) != _plain(new_value):
                    continue
                parent = _lookup(out, dst[:-1])
                if not isinstance(parent, (CommentedMap, CommentedSeq)):
                    continue
                if note["before"]:
                    _add_before(parent, dst[-1], note["before"], _output_indent(out, dst))
                if note["eol"]:
                    _add_eol(parent, dst[-1], note["eol"])
                placed = True
            if not placed:
                unplaced += [(".".join(map(str, path)), t) for t in texts]

    if header:
        tokens = [CommentToken(c + "\n", CommentMark(0)) for c in header] + [CommentToken("\n", CommentMark(0))]
        if out.ca.comment is None:
            out.ca.comment = [None, tokens]
        else:
            out.ca.comment[1] = tokens + (out.ca.comment[1] or [])
    if unplaced:
        listed = "".join(f"\n       {path}: {text}" for path, text in unplaced)
        warnings.append(
            "These comments were not carried over because their key was dropped or its value changed. "
            "Copy any you still need by hand:" + listed
        )


# ---------------------------------------------------------------------------
# Interactive wizard
# ---------------------------------------------------------------------------

def _prompt(question, default=None):
    """Print a question and return stripped input. Returns default on empty input."""
    suffix = f" [{default}]" if default else ""
    answer = input(f"\n{question}{suffix}: ").strip()
    return answer or default or ""


def _choose(question, choices):
    """Present a numbered menu and return the chosen item."""
    print(f"\n{question}")
    for i, (label, _desc) in enumerate(choices, 1):
        print(f"  {i}) {label}")
    while True:
        raw = input("Enter number: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1]
        print(f"  Please enter a number between 1 and {len(choices)}.")


def run_wizard(yaml_instance, cli_admission_control=None, cli_image_analyzer=None,
               cli_image_repo=None, cli_image_tag=None, cli_image_digest=None):
    """
    Interactive wizard. Returns (values, primary_input_label, fcg_image_repo, fcg_image_tag,
    fcg_image_digest, release_name, release_ns, admission_control_override, image_analyzer_override).
    Discovers the existing Helm release, asks for registry/version, and loads or extracts values.
    """
    print("=" * 60)
    print("  Falcon Cluster Guard — Migration Wizard")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: Discover existing Helm release
    # ------------------------------------------------------------------
    print("\n── Step 1: Locate your existing falcon-platform release ──")

    release_name = None
    release_ns   = None

    try:
        result = subprocess.run(
            ["helm", "list", "-A", "-o", "json"],
            capture_output=True, text=True, check=True,
        )
        releases = json.loads(result.stdout or "[]")
        candidates = [
            r for r in releases
            if any(name in r.get("chart", "") or name in r.get("name", "")
                   for name in ("falcon-platform", "falcon-sensor", "falcon-kac"))
        ]
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        candidates = []

    if candidates:
        print("\nFound Helm releases that may be your Falcon deployment:")
        for i, r in enumerate(candidates, 1):
            print(f"  {i}) {r['name']}  (chart: {r['chart']}, namespace: {r['namespace']})")
        print(f"  {len(candidates)+1}) None of these — enter manually")

        raw = input("\nSelect a release [1]: ").strip() or "1"
        if raw.isdigit() and 1 <= int(raw) <= len(candidates):
            chosen = candidates[int(raw) - 1]
            release_name = chosen["name"]
            release_ns   = chosen["namespace"]
            print(f"  ✓ Using release '{release_name}' in namespace '{release_ns}'")
        else:
            print("  Entering manual mode.")

    if not release_name:
        release_name = _prompt("Release name", default="falcon-platform")
        release_ns   = _prompt("Release namespace", default="falcon-platform")

    # ------------------------------------------------------------------
    # Step 2: FCG image (no defaults until FCG is generally available)
    # ------------------------------------------------------------------
    print("\n── Step 2: FCG image ──")

    fcg_image_repo = cli_image_repo or prompt_image_repo(out=sys.stdout)
    if cli_image_tag or cli_image_digest:
        fcg_image_tag, fcg_image_digest = cli_image_tag, cli_image_digest
    else:
        fcg_image_tag, fcg_image_digest = prompt_image_ref(out=sys.stdout)
    if fcg_image_digest:
        print(f"  ✓ Image: {fcg_image_repo}@{fcg_image_digest}")
    else:
        print(f"  ✓ Image: {fcg_image_repo}:{fcg_image_tag}")

    # ------------------------------------------------------------------
    # Step 3: Values source
    # ------------------------------------------------------------------
    print("\n── Step 3: Values source ──")

    input_mode, _ = _choose(
        "How are your Falcon values organized?",
        [
            ("Extract from running Helm release", "helm"),
            ("Single falcon-platform umbrella values file", "umbrella"),
            ("Separate values files per chart", "individual"),
        ],
    )

    primary_input_label = None
    values = {}
    kac_provided = False  # tracks whether falcon-kac values were available

    if input_mode.startswith("Extract"):
        print(f"  Extracting values from release '{release_name}' (namespace: {release_ns})…")
        try:
            result = subprocess.run(
                ["helm", "get", "values", release_name, "-n", release_ns, "-o", "yaml"],
                capture_output=True, text=True, check=True,
            )
            if not result.stdout.strip() or result.stdout.strip() == "null":
                print("  No user-supplied values found in this release — proceeding with empty values.")
                values = {}
            else:
                values = parse_values(yaml_instance, result.stdout, f"helm get values {release_name}")
                check_platform_file(values, f"Release {release_name!r}")
            primary_input_label = f"{release_name}-extracted"
            kac_provided = "falcon-kac" in values
            print(f"  ✓ Extracted {len(values)} top-level keys from release.")
        except subprocess.CalledProcessError as e:
            print(f"  ERROR: helm get values failed: {e.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        except FileNotFoundError:
            print("  ERROR: helm not found in PATH.", file=sys.stderr)
            sys.exit(1)

    elif input_mode.startswith("Single"):
        values_path = _prompt("Path to your falcon-platform values file")
        if not values_path:
            raise InputError("no falcon-platform values file was given")
        values = load_values(yaml_instance, values_path)
        check_platform_file(values, values_path)
        primary_input_label = values_path
        kac_provided = "falcon-kac" in values
        print(f"  ✓ Loaded values from {values_path}")

    else:  # individual charts
        sensor_path = _prompt("Path to falcon-sensor values file (or Enter to skip)")
        kac_path    = _prompt("Path to falcon-kac values file (or Enter to skip)")
        iar_path    = _prompt("Path to falcon-image-analyzer values file (or Enter to skip)")

        def _load_if(path, chart):
            if not path:
                return {}
            doc = load_values(yaml_instance, path)
            check_chart_file(doc, path, chart)
            return doc

        sensor_vals = _load_if(sensor_path, "falcon-sensor")
        kac_vals    = _load_if(kac_path, "falcon-kac")
        iar_vals    = _load_if(iar_path, "falcon-image-analyzer")

        values = CommentedMap()
        if sensor_vals:
            values["falcon-sensor"] = sensor_vals
        if kac_vals:
            values["falcon-kac"] = kac_vals
        if iar_vals:
            values["falcon-image-analyzer"] = iar_vals

        kac_provided = bool(kac_vals)
        primary_input_label = sensor_path or kac_path or iar_path or "individual-charts"
        loaded = [p for p in (sensor_path, kac_path, iar_path) if p]
        print(f"  ✓ Loaded {len(loaded)} values file(s): {', '.join(loaded)}")

    print("\n" + "=" * 60)

    # ------------------------------------------------------------------
    # Step 4: Admission control
    # ------------------------------------------------------------------
    print("\n── Step 4: Admission Controller ──")

    if cli_admission_control is not None:
        admission_control_override = cli_admission_control
        print(f"  ✓ admissionControl.enabled = {str(admission_control_override).lower()} (from --admission-control flag)")
    else:
        # Derive current state from loaded values so the default is meaningful.
        # If kac values were not provided we cannot infer intent — default to false
        # to avoid accidentally enabling the webhook without a configured policy.
        current_ac = (
            get_nested(values, "falcon-clusterguard", "clusterguardController", "admissionControl", "enabled")
            or get_nested(values, "falcon-kac", "admissionControl", "enabled")
        )
        if get_nested(values, "falcon-kac", "enabled") is False:
            current_ac = False  # falcon-kac was not deployed, so it had no webhook
        if current_ac is None:
            current_ac = True if kac_provided else False
        ac_default = "true" if current_ac else "false"

        if not kac_provided:
            print("  NOTE: No falcon-kac values were found — defaulting admissionControl.enabled to false.")
        else:
            print(f"  Current: admissionControl.enabled = {ac_default}")
        print("  Enable or disable the ValidatingWebhookConfiguration for admission controller.")
        ac_raw = _prompt("Enable Admission Controller? (true/false)", default=ac_default)
        try:
            admission_control_override = _parse_bool(ac_raw)
        except ValueError:
            print(f"  Invalid value '{ac_raw}' — keeping current ({ac_default})", file=sys.stderr)
            admission_control_override = _parse_bool(ac_default)
        print(f"  ✓ admissionControl.enabled = {str(admission_control_override).lower()}")

    # ------------------------------------------------------------------
    # Step 5: Image analyzer
    # ------------------------------------------------------------------
    print("\n── Step 5: Image Analyzer ──")

    if cli_image_analyzer is not None:
        image_analyzer_override = cli_image_analyzer
        print(f"  ✓ falcon-clusterguard.imageAnalyzer.enabled = {str(image_analyzer_override).lower()} (from --image-analyzer flag)")
    else:
        current_iar = get_nested(values, "falcon-image-analyzer", "enabled")
        if current_iar is None:
            current_iar = "falcon-image-analyzer" in values
        iar_default = "true" if current_iar else "false"

        if not current_iar and "falcon-image-analyzer" not in values:
            print("  NOTE: No falcon-image-analyzer values were found — defaulting to false.")
        else:
            print(f"  Current: falcon-image-analyzer.enabled = {iar_default}")
        print("  NOTE: The image analyzer now runs inside FCG. falcon-image-analyzer values are moved")
        print("        to falcon-clusterguard.imageAnalyzer.* and the standalone subchart is disabled.")
        iar_raw = _prompt("Enable Image Analyzer? (true/false)", default=iar_default)
        try:
            image_analyzer_override = _parse_bool(iar_raw)
        except ValueError:
            print(f"  Invalid value '{iar_raw}' — keeping current ({iar_default})", file=sys.stderr)
            image_analyzer_override = _parse_bool(iar_default)
        print(f"  ✓ falcon-clusterguard.imageAnalyzer.enabled = {str(image_analyzer_override).lower()}")

    print("\n" + "=" * 60)
    return (values, primary_input_label, fcg_image_repo, fcg_image_tag, fcg_image_digest, release_name, release_ns,
            admission_control_override, image_analyzer_override)

def _detect_release(preferred_names=("falcon-platform",)):
    """Try to auto-detect the Helm release name and namespace. Returns (name, ns) or defaults."""
    try:
        result = subprocess.run(
            ["helm", "list", "-A", "-o", "json"],
            capture_output=True, text=True, check=True,
        )
        releases = json.loads(result.stdout or "[]")
        for r in releases:
            if any(n in r.get("chart", "") or n in r.get("name", "") for n in preferred_names):
                return r["name"], r["namespace"]
    except Exception:
        pass
    return "falcon-platform", "falcon-platform"


def print_next_steps(output_path, primary_input, release_name, release_ns, migrated_values):
    """Print helm upgrade command and verification steps after a successful migration."""
    fcg = migrated_values.get("falcon-clusterguard") or {}
    fcg_ns = fcg.get("namespaceOverride") or release_ns or "falcon-system"
    node_enabled    = (fcg.get("nodeSensor") or {}).get("enabled", True)
    cluster_enabled = (fcg.get("clusterguardController") or {}).get("enabled", True)
    iar_enabled     = (fcg.get("imageAnalyzer") or {}).get("enabled", False)

    sep = "─" * 60
    print(f"\n{sep}")
    print("  Next steps")
    print(sep)
    print(f"""
1) Review the migrated values file:

   diff {primary_input} {output_path}

2) Run helm upgrade:

   helm upgrade {release_name} crowdstrike/falcon-platform \\
     -n {release_ns} \\
     -f {output_path}

3) Verify the upgrade:
""")
    if node_enabled:
        node_ds = ((fcg.get("nodeSensor") or {}).get("daemonset") or {}).get("name") or "falcon-sensor"
        print(f"   # Node Sensor DaemonSet")
        print(f"   kubectl rollout status daemonset/{node_ds} -n {fcg_ns}")
        print()
    if cluster_enabled:
        print(f"   # Cluster Guard Deployment")
        print(f"   kubectl rollout status deployment/falcon-clusterguard-controller -n {fcg_ns}")
        print()
    if iar_enabled:
        print(f"   # Image Analyzer Deployment")
        print(f"   kubectl get pods -n {fcg_ns} -l app=falcon-image-analyzer")
        print()
    print(f"   # All FCG pods")
    print(f"   kubectl get pods -n {fcg_ns} -l app.kubernetes.io/instance={release_name}")
    print(f"""
4) Clean up deprecated namespaces once stable:

   kubectl delete ns falcon-kac falcon-image-analyzer
""")
    print(sep)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def make_yaml():
    """Round-trip YAML instance used to read source values and write the migrated file."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 120
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.best_map_flow_style = False
    return yaml


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Falcon platform values to falcon-clusterguard (FCG).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Input modes (mutually exclusive):\n"
            "  --interactive         Guided wizard (also auto-activates when no values flags given)\n"
            "  --platform-values     Single falcon-platform umbrella values file\n"
            "  --sensor-values / --kac-values / --iar-values\n"
            "                        Individual chart values files\n"
        ),
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--interactive",
        action="store_true",
        help="Run the interactive migration wizard",
    )
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
        default=None,
        help="FCG image repository, without a tag. Prompted for when not set "
             "(no default until FCG is generally available)",
    )
    parser.add_argument(
        "--fcg-image-tag",
        metavar="TAG",
        default=None,
        help="FCG image tag. Prompted for when neither --fcg-image-tag nor --fcg-image-digest is set "
             "(no default until FCG is generally available)",
    )
    parser.add_argument(
        "--fcg-image-digest",
        metavar="DIGEST",
        default=None,
        help="FCG image digest (sha256:<64 hex characters>). FCG uses it in place of the tag",
    )
    parser.add_argument(
        "--admission-control",
        metavar="BOOL",
        default=None,
        help="Override falcon-clusterguard.clusterguardController.admissionControl.enabled (true/false)",
    )
    parser.add_argument(
        "--image-analyzer",
        metavar="BOOL",
        default=None,
        help="Override falcon-clusterguard.imageAnalyzer.enabled (true/false)",
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
    parser.add_argument(
        "--validate",
        nargs="?",
        const="",
        metavar="CHART",
        help="Render the migrated falcon-clusterguard values with helm template to check them. CHART is a "
             "falcon-clusterguard chart path or name (default: the chart in this repository). Requires helm",
    )
    args = parser.parse_args()

    # Parse bool flags early so errors surface before any work begins
    admission_control_override = None
    image_analyzer_override = None
    if args.admission_control is not None:
        try:
            admission_control_override = _parse_bool(args.admission_control)
        except ValueError as e:
            parser.error(f"--admission-control: {e}")
    if args.image_analyzer is not None:
        try:
            image_analyzer_override = _parse_bool(args.image_analyzer)
        except ValueError as e:
            parser.error(f"--image-analyzer: {e}")

    # Validate the FCG image repository, tag, and digest. There are no defaults until FCG is generally available.
    fcg_image_repo = fcg_image_tag = fcg_image_digest = None
    if args.fcg_image_repo is not None:
        try:
            fcg_image_repo = validate_image_repo(args.fcg_image_repo)
        except ValueError as e:
            parser.error(f"--fcg-image-repo: {e}")
    if args.fcg_image_tag is not None:
        try:
            fcg_image_tag = validate_image_tag(args.fcg_image_tag)
        except ValueError as e:
            parser.error(f"--fcg-image-tag: {e}")
    if args.fcg_image_digest is not None:
        try:
            fcg_image_digest = normalize_image_digest(args.fcg_image_digest)
        except ValueError as e:
            parser.error(f"--fcg-image-digest: {e}")

    validate_chart = None
    if args.validate is not None:
        validate_chart = args.validate or default_fcg_chart()
        if not validate_chart:
            parser.error("--validate: the falcon-clusterguard chart isn't in this repository; pass its path or "
                         "name, for example --validate ./falcon-clusterguard")
        if not shutil.which("helm"):
            parser.error("--validate requires helm, which was not found in PATH")

    # Validate: individual chart flags only with --sensor-values
    if args.platform_values and (args.kac_values or args.iar_values):
        parser.error("--sensor-values, --kac-values, and --iar-values cannot be used with --platform-values")

    yaml = make_yaml()

    def load(path, chart=None):
        doc = load_values(yaml, path)
        if chart:
            check_chart_file(doc, path, chart)
        else:
            check_platform_file(doc, path)
        return doc

    # Determine mode
    use_wizard = args.interactive or (
        not args.platform_values and not args.sensor_values
    )

    if use_wizard:
        values, primary_input, fcg_image_repo, fcg_image_tag, fcg_image_digest, release_name, release_ns, \
            admission_control_override, image_analyzer_override = run_wizard(
                yaml, cli_admission_control=admission_control_override,
                cli_image_analyzer=image_analyzer_override,
                cli_image_repo=fcg_image_repo, cli_image_tag=fcg_image_tag, cli_image_digest=fcg_image_digest,
            )
    elif args.platform_values:
        values = load(args.platform_values)
        primary_input = args.platform_values
        release_name, release_ns = _detect_release()
        if admission_control_override is None and "falcon-kac" not in values:
            admission_control_override = False
        if image_analyzer_override is None and "falcon-image-analyzer" not in values:
            image_analyzer_override = False
    else:
        sensor_vals = load(args.sensor_values, "falcon-sensor")
        kac_vals    = load(args.kac_values, "falcon-kac") if args.kac_values else {}
        iar_vals    = load(args.iar_values, "falcon-image-analyzer") if args.iar_values else {}

        values = CommentedMap()
        if sensor_vals:
            values["falcon-sensor"] = sensor_vals
        if kac_vals:
            values["falcon-kac"] = kac_vals
        if iar_vals:
            values["falcon-image-analyzer"] = iar_vals
        primary_input  = args.sensor_values
        release_name, release_ns = _detect_release()
        if admission_control_override is None and not kac_vals:
            admission_control_override = False
        if image_analyzer_override is None and not iar_vals:
            image_analyzer_override = False

    missing = []
    if not fcg_image_repo:
        missing.append("an FCG image repository (--fcg-image-repo)")
    if not (fcg_image_tag or fcg_image_digest):
        missing.append("an FCG image tag or digest (--fcg-image-tag or --fcg-image-digest)")
    if missing and not sys.stdin.isatty():
        parser.error(f"{' and '.join(missing)} {'are' if len(missing) > 1 else 'is'} required. "
                     "Default values will be added once FCG is generally available.")
    if not fcg_image_repo:
        fcg_image_repo = prompt_image_repo()
    if not (fcg_image_tag or fcg_image_digest):
        fcg_image_tag, fcg_image_digest = prompt_image_ref()

    warnings = []
    migrated = migrate(values, warnings,
                       fcg_image_repo=fcg_image_repo,
                       fcg_image_tag=fcg_image_tag,
                       fcg_image_digest=fcg_image_digest)
    apply_overrides(migrated, admission_control_override, image_analyzer_override)
    carry_comments(comment_sources(values), migrated, warnings)

    if warnings:
        print("\nMIGRATION WARNINGS — review these before applying:", file=sys.stderr)
        for w in warnings:
            print(f"  ⚠  {w}", file=sys.stderr)
        print(file=sys.stderr)

    output_path = None
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
        print(f"\nMigrated values written to: {output_path}")

    if validate_chart:
        error = validate_with_helm(migrated, validate_chart, yaml)
        if error:
            print(f"\nVALIDATION FAILED — helm template could not render the migrated values with {validate_chart}:",
                  file=sys.stderr)
            print("  " + error.replace("\n", "\n  "), file=sys.stderr)
            if output_path:
                print(f"\nThe migrated values were still written to {output_path}. Fix them before upgrading.",
                      file=sys.stderr)
            sys.exit(1)
        print(f"\n✓ The migrated values render with {validate_chart}.", file=sys.stderr)

    if output_path:
        print_next_steps(output_path, primary_input, release_name, release_ns, migrated)


if __name__ == "__main__":
    try:
        main()
    except InputError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
