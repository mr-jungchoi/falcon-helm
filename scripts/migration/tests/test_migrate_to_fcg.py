"""Tests for scripts/migration/migrate-to-fcg.py.

Run from the repository root:

    python3 -m unittest discover -s scripts/migration/tests -v

Requires ruamel.yaml (the script's only dependency). The helm render test is skipped when helm is
not on PATH.
"""

import importlib.util
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from ruamel.yaml import YAML

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parents[1]
SCRIPT = SCRIPTS_DIR / "migrate-to-fcg.py"
README = SCRIPTS_DIR / "README.md"
FCG_CHART = REPO_ROOT / "helm-charts" / "falcon-clusterguard"

_spec = importlib.util.spec_from_file_location("migrate_to_fcg", SCRIPT)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

CID = "1234567890ABCDEF1234567890ABCDEF-12"
# Example FCG image values; the script has no defaults until FCG is generally available.
REPO = "registry.crowdstrike.com/falcon-clusterguard/release/falcon-clusterguard"
TAG = "8.14.0-12345-1"


def load(text):
    """Parse YAML the same way the script parses its input files."""
    return mig.make_yaml().load(text) or {}


def dump(obj):
    buf = io.StringIO()
    mig.make_yaml().dump(obj, buf)
    return buf.getvalue()


def migrate(text, **kwargs):
    """Run migrate() on a YAML string. Returns (output, falcon-clusterguard block, warnings)."""
    kwargs.setdefault("fcg_image_repo", REPO)
    warnings = []
    out = mig.migrate(load(text), warnings, **kwargs)
    return out, out["falcon-clusterguard"], warnings


def plain(obj):
    """Convert ruamel containers to plain dicts and lists for comparisons."""
    return json.loads(json.dumps(obj))


def warned(warnings, fragment):
    return any(fragment in w for w in warnings)


# A falcon-platform values file that sets every key the script maps, with values that are valid
# for the FCG chart. Used by the contract tests.
FULL_PLATFORM_VALUES = f"""
global:
  falcon:
    cid: {CID}
createComponentNamespaces: true
falcon-sensor:
  enabled: true
  namespaceOverride: falcon-system
  falcon:
    cid: {CID}
    trace: info
    tags: "a,b"
  serviceAccount:
    name: custom-sensor-sa
    annotations:
      iam.example.com/role: sensor
  node:
    enabled: true
    clusterName: my-cluster
    backend: bpf
    image:
      repository: registry.example.com/falcon-sensor
      tag: 7.30.0
      pullPolicy: IfNotPresent
      pullSecrets: sensor-pull-secret
    daemonset:
      tolerations:
        - key: example.com/taint
          operator: Exists
          effect: NoSchedule
      updateStrategy: RollingUpdate
      maxUnavailable: 2
      resources:
        requests:
          cpu: 250m
          memory: 512Mi
    podAnnotations:
      a: b
    podLabels:
      c: d
    terminationGracePeriod: 90
    hooks:
      postDelete:
        enabled: true
    cleanupOnly: false
    gke:
      autopilot: false
falcon-kac:
  enabled: true
  clusterName: my-cluster
  falcon:
    trace: debug
    tags: "a,b"
  replicas: 1
  webhookPort: 4443
  watcherPort: 4080
  autoCertificateUpdate: false
  autoDeploymentUpdate: false
  certExpiration: 365
  domainName: example.io
  hostNetwork: false
  dnsPolicy: ClusterFirst
  tolerations:
    - key: example.com/taint
      operator: Exists
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
          - matchExpressions:
              - key: kubernetes.io/arch
                operator: In
                values: [amd64]
  annotations:
    e: f
  labels:
    g: h
  podAnnotations:
    i: j
  podLabels:
    k: l
  admissionControl:
    enabled: true
  webhook:
    failurePolicy: Ignore
    disableNamespaces: "ns1,ns2"
  resourceQuota:
    pods: 3
  falconClientResources:
    limits:
      memory: 384Mi
    requests:
      cpu: 250m
      memory: 384Mi
  falconClientNoWebhookResources:
    limits:
      memory: 128Mi
    requests:
      cpu: 100m
      memory: 128Mi
  falconWatcherResources:
    limits:
      memory: 512Mi
    requests:
      cpu: 250m
      memory: 512Mi
  falconAcResources:
    limits:
      memory: 256Mi
    requests:
      cpu: 100m
      memory: 256Mi
  serviceAccount:
    annotations:
      iam.example.com/role: kac
  clusterVisibility:
    resourceSnapshots:
      enabled: true
      interval: 12h
    resourceWatcher:
      enabled: true
    resourceConfigMap:
      enabled: false
  image:
    pullSecrets: kac-pull-secret
falcon-image-analyzer:
  enabled: true
  crowdstrikeConfig:
    clientID: abcdefABCDEF0123456789abcdefABCD
    clientSecret: abcdefABCDEF0123456789abcdefABCDEF012345
    agentRegion: us-1
    agentMaxConsumerThreads: "2"
    enableKlogs: "false"
    clusterName: my-cluster
  exclusions:
    namespace: kube-system
    registry: ""
    imageName: ""
  hostNetwork: false
  podAnnotations:
    m: n
  podLabels:
    o: p
  resources:
    limits:
      memory: 1Gi
  tolerations: []
  priorityClassName: ""
  nodeSelector:
    kubernetes.io/os: linux
  watcher:
    listPageSize: 250
  log:
    output: 2
    verbosity: debug
  iarAgentService:
    httpPort: 8001
    certExpiration: 365
  privateRegistries:
    credentials: ""
    autoDiscoverCredentials: true
  volumes:
    - name: tmp-volume
      emptyDir:
        sizeLimit: 10Gi
  volumeMounts:
    - mountPath: /tmp
      name: tmp-volume
  proxyConfig:
    HTTP_PROXY: ""
    HTTPS_PROXY: ""
    NO_PROXY: ""
  azure:
    enabled: false
  gcp:
    enabled: true
"""


class TestHelpers(unittest.TestCase):
    def test_get_nested(self):
        d = {"a": {"b": {"c": 1}}}
        self.assertEqual(mig.get_nested(d, "a", "b", "c"), 1)
        self.assertIsNone(mig.get_nested(d, "a", "x"))
        self.assertIsNone(mig.get_nested(d, "a", "b", "c", "d"))
        self.assertIsNone(mig.get_nested(None, "a"))

    def test_set_nested_creates_intermediate_maps(self):
        d = {"a": "scalar"}
        mig.set_nested(d, ["a", "b", "c"], 2)
        self.assertEqual(plain(d), {"a": {"b": {"c": 2}}})

    def test_insert_before(self):
        cm = load("x: 1\nz: 3\n")
        mig.insert_before(cm, "y", 2, before="z")
        self.assertEqual(list(cm), ["x", "y", "z"])
        mig.insert_before(cm, "w", 0, before="missing")
        self.assertEqual(list(cm), ["x", "y", "z", "w"])
        mig.insert_before(cm, "x", 10, before="z")  # existing key: updated in place
        self.assertEqual(list(cm), ["x", "y", "z", "w"])
        self.assertEqual(cm["x"], 10)

    def test_parse_bool(self):
        for value in ("true", "TRUE", "1", "yes"):
            self.assertIs(mig._parse_bool(value), True)
        for value in ("false", "False", "0", "no"):
            self.assertIs(mig._parse_bool(value), False)
        with self.assertRaises(ValueError):
            mig._parse_bool("maybe")

    def test_strip_comments(self):
        cm = load("a:  # comment\n  b: 1  # another\n\nc: 2\n")
        mig.strip_comments(cm)
        self.assertEqual(dump(cm), "a:\n  b: 1\nc: 2\n")


class TestImageReference(unittest.TestCase):
    """FCG image tag and digest handling. There are no defaults until FCG is generally available."""

    DIGEST = "sha256:" + "a" * 64

    def test_validate_image_repo(self):
        for repo in (REPO, "my-reg.corp.io:5000/fcg", "localhost:5000/fcg", "fcg", "Registry.Example.com/fcg",
                     "123456789012.dkr.ecr.us-east-1.amazonaws.com/team/falcon-clusterguard", "a/b__c/d--e"):
            self.assertEqual(mig.validate_image_repo(repo), repo)
        for repo in ("", None, "registry.example.com/fcg:1.0.0", "registry.example.com/fcg@sha256:abc",
                     "registry.example.com/FCG", "https://registry.example.com/fcg", "registry.example.com/",
                     "registry.example.com//fcg", "has space/fcg", "-bad.io/fcg"):
            with self.assertRaises(ValueError, msg=repo):
                mig.validate_image_repo(repo)

    def test_repo_prompt_asks_again_until_valid(self):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(f"\nreg.io/fcg:1.0\n{REPO}\n")):
            self.assertEqual(mig.prompt_image_repo(out=out), REPO)
        self.assertEqual(out.getvalue().count("FCG image repository (for example"), 3)
        self.assertIn("invalid image repository 'reg.io/fcg:1.0'", out.getvalue())

    def test_repo_prompt_exits_at_end_of_input(self):
        with self.assertRaises(SystemExit) as ctx, mock.patch("sys.stdin", io.StringIO("")):
            mig.prompt_image_repo(out=io.StringIO())
        self.assertIn("no FCG image repository", str(ctx.exception.code))

    def test_validate_image_tag(self):
        for tag in ("8.14.0-12345-1", "latest", "v1_2", "a" * 128):
            self.assertEqual(mig.validate_image_tag(tag), tag)
        for tag in ("", "has space", "-leading-dash", ".leading-dot", "a" * 129, "tag:with:colons", None):
            with self.assertRaises(ValueError, msg=tag):
                mig.validate_image_tag(tag)

    def test_normalize_image_digest(self):
        self.assertEqual(mig.normalize_image_digest(self.DIGEST), self.DIGEST)
        self.assertEqual(mig.normalize_image_digest("a" * 64), self.DIGEST)
        for digest in ("sha256:abc", "sha256:" + "A" * 64, "sha512:" + "a" * 64, "", None):
            with self.assertRaises(ValueError, msg=digest):
                mig.normalize_image_digest(digest)

    def test_parse_image_ref(self):
        self.assertEqual(mig.parse_image_ref(" 8.14.0-12345-1\n"), ("8.14.0-12345-1", None))
        self.assertEqual(mig.parse_image_ref(self.DIGEST), (None, self.DIGEST))
        self.assertEqual(mig.parse_image_ref("a" * 64), (None, self.DIGEST))
        with self.assertRaises(ValueError):
            mig.parse_image_ref("sha256:short")
        with self.assertRaises(ValueError):
            mig.parse_image_ref("")

    def prompt(self, answers):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(answers)):
            return mig.prompt_image_ref(out=out), out.getvalue()

    def test_prompt_asks_again_until_valid(self):
        (tag, digest), text = self.prompt("\nbad tag!\n8.14.0-12345-1\n")
        self.assertEqual((tag, digest), ("8.14.0-12345-1", None))
        self.assertIn("Default values will be added once FCG is generally available", text)
        self.assertEqual(text.count("FCG image tag, or digest"), 3)
        self.assertIn("invalid image tag 'bad tag!'", text)

    def test_prompt_accepts_a_digest(self):
        (tag, digest), _ = self.prompt(self.DIGEST + "\n")
        self.assertEqual((tag, digest), (None, self.DIGEST))

    def test_prompt_exits_at_end_of_input(self):
        with self.assertRaises(SystemExit) as ctx:
            self.prompt("bad tag!\n")
        self.assertIn("no FCG image tag or digest", str(ctx.exception.code))

    def test_prompt_writes_to_stderr_by_default(self):
        stderr = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("1.0.0\n")), mock.patch("sys.stderr", stderr), \
                redirect_stdout(io.StringIO()) as stdout:
            mig.prompt_image_ref()
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("FCG image tag, or digest", stderr.getvalue())


class TestImage(unittest.TestCase):
    def test_no_image_values_by_default(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {enabled: true}}", fcg_image_repo=None)
        self.assertEqual(plain(fcg["image"]), {})
        _, fcg, _ = migrate("falcon-sensor: {node: {image: {pullSecrets: s}}}", fcg_image_repo=None)
        self.assertEqual(plain(fcg["image"]), {"pullSecret": "s"})

    def test_repository_only(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {enabled: true}}")
        self.assertEqual(plain(fcg["image"]), {"repository": REPO})

    def test_custom_repository_and_tag(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {enabled: true}}", fcg_image_repo="my.reg/fcg", fcg_image_tag="1.2.3")
        self.assertEqual(plain(fcg["image"]), {"repository": "my.reg/fcg", "tag": "1.2.3"})

    def test_digest(self):
        digest = "sha256:" + "b" * 64
        _, fcg, _ = migrate("falcon-sensor: {node: {enabled: true}}", fcg_image_digest=digest)
        self.assertEqual(plain(fcg["image"]), {"repository": REPO, "digest": digest})
        _, fcg, _ = migrate("falcon-sensor: {node: {enabled: true}}", fcg_image_tag="1.2.3", fcg_image_digest=digest)
        self.assertEqual(plain(fcg["image"]), {"repository": REPO, "tag": "1.2.3", "digest": digest})

    def test_source_repository_and_tag_are_replaced(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {image: {repository: old/sensor, tag: '7.0'}}}", fcg_image_tag="1.2.3")
        self.assertEqual(fcg["image"]["repository"], REPO)
        self.assertEqual(fcg["image"]["tag"], "1.2.3")

    def test_sensor_pull_secrets_becomes_pull_secret(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {image: {pullSecrets: my-secret}}}")
        self.assertEqual(fcg["image"]["pullSecret"], "my-secret")
        self.assertNotIn("pullSecrets", fcg["image"])

    def test_kac_pull_secrets_used_when_sensor_has_none(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {enabled: true}}\nfalcon-kac: {image: {pullSecrets: kac-secret}}")
        self.assertEqual(fcg["image"]["pullSecret"], "kac-secret")

    def test_sensor_pull_secret_takes_precedence_over_kac(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {image: {pullSecrets: s}}}\nfalcon-kac: {image: {pullSecrets: k}}")
        self.assertEqual(fcg["image"]["pullSecret"], "s")

    def test_registry_config_json(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {image: {registryConfigJSON: e30=}}}")
        self.assertEqual(fcg["image"]["registryConfigJSON"], "e30=")
        self.assertNotIn("pullSecret", fcg["image"])

    def test_pull_auth_comes_from_one_source(self):
        # FCG fails when both pullSecret and registryConfigJSON are set.
        _, fcg, _ = migrate("falcon-sensor: {node: {image: {pullSecrets: s}}}\nfalcon-kac: {image: {registryConfigJSON: e30=}}")
        self.assertEqual(fcg["image"]["pullSecret"], "s")
        self.assertNotIn("registryConfigJSON", fcg["image"])
        _, fcg, _ = migrate("falcon-sensor: {node: {image: {registryConfigJSON: e30=}}}\nfalcon-kac: {image: {pullSecrets: k}}")
        self.assertEqual(fcg["image"]["registryConfigJSON"], "e30=")
        self.assertNotIn("pullSecret", fcg["image"])

    def test_pull_policy(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {image: {pullPolicy: Always}}}\nfalcon-kac: {image: {pullPolicy: Never}}")
        self.assertEqual(fcg["image"]["pullPolicy"], "Always")
        _, fcg, _ = migrate("falcon-sensor: {node: {enabled: true}}\nfalcon-kac: {image: {pullPolicy: Never}}")
        self.assertEqual(fcg["image"]["pullPolicy"], "Never")

    def test_digests_are_dropped_with_a_warning(self):
        # A sensor or kac digest would make FCG pull <fcg-repo>@<old-digest>.
        _, fcg, warnings = migrate(
            "falcon-sensor: {node: {image: {digest: 'sha256:aaa'}}}\nfalcon-kac: {image: {digest: 'sha256:bbb'}}"
        )
        self.assertNotIn("digest", fcg["image"])
        self.assertTrue(warned(warnings, "falcon-sensor.node.image.digest, falcon-kac.image.digest omitted"))


class TestNodeSensor(unittest.TestCase):
    def test_direct_keys_are_copied(self):
        _, fcg, _ = migrate("""
falcon-sensor:
  node:
    enabled: true
    daemonset: {updateStrategy: OnDelete, maxUnavailable: 3}
    podAnnotations: {a: b}
    podLabels: {c: d}
    terminationGracePeriod: 30
    hooks: {postDelete: {enabled: false}}
    cleanupOnly: true
""")
        node = plain(fcg["nodeSensor"])
        self.assertEqual(node["daemonset"], {"updateStrategy": "OnDelete", "maxUnavailable": 3})
        self.assertEqual(node["podAnnotations"], {"a": "b"})
        self.assertEqual(node["podLabels"], {"c": "d"})
        self.assertEqual(node["terminationGracePeriod"], 30)
        self.assertEqual(node["hooks"], {"postDelete": {"enabled": False}})
        self.assertIs(node["cleanupOnly"], True)
        self.assertIs(node["enabled"], True)

    def test_keys_handled_elsewhere_are_not_in_node_sensor(self):
        _, fcg, _ = migrate("""
falcon-sensor:
  node:
    backend: kernel
    clusterName: c1
    image: {pullSecrets: s}
    openshift: {enabled: true}
    gke: {autopilot: true}
""")
        for key in ("backend", "clusterName", "image", "openshift", "gke"):
            self.assertNotIn(key, fcg["nodeSensor"])

    def test_backend_is_dropped_with_a_warning(self):
        _, _, warnings = migrate("falcon-sensor: {node: {backend: kernel}}")
        self.assertTrue(warned(warnings, "falcon-sensor.node.backend is deprecated"))

    def test_gke_moves_to_the_top_level_before_node_sensor(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {gke: {autopilot: true, deployAllowListVersion: v1.0.3}}}")
        self.assertEqual(plain(fcg["gke"]), {"autopilot": True, "deployAllowListVersion": "v1.0.3"})
        self.assertLess(list(fcg).index("gke"), list(fcg).index("nodeSensor"))

    def test_service_account_defaults_to_the_old_chart_name(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {enabled: true}}")
        self.assertEqual(plain(fcg["nodeSensor"]["serviceAccount"]), {"name": "crowdstrike-falcon-sa"})

    def test_service_account_is_carried_over(self):
        _, fcg, _ = migrate("falcon-sensor: {serviceAccount: {name: my-sa, annotations: {x: y}}, node: {enabled: true}}")
        self.assertEqual(plain(fcg["nodeSensor"]["serviceAccount"]), {"name": "my-sa", "annotations": {"x": "y"}})

    def test_disabled_when_there_are_no_sensor_values(self):
        _, fcg, warnings = migrate("falcon-kac: {enabled: true}")
        self.assertEqual(plain(fcg["nodeSensor"]), {"enabled": False})
        self.assertTrue(warned(warnings, "because no falcon-sensor values were provided"))
        self.assertFalse(warned(warnings, "falcon-sensor.node block not found"))

    def test_disabled_when_falcon_sensor_is_disabled(self):
        _, fcg, warnings = migrate("falcon-sensor: {enabled: false, node: {enabled: true, clusterName: c1}}")
        self.assertIs(fcg["nodeSensor"]["enabled"], False)
        self.assertEqual(fcg["clusterName"], "c1")
        self.assertTrue(warned(warnings, "because falcon-sensor.enabled is false"))

    def test_disabled_when_node_is_disabled(self):
        _, fcg, warnings = migrate("falcon-sensor: {node: {enabled: false, clusterName: c1}}")
        self.assertIs(fcg["nodeSensor"]["enabled"], False)
        self.assertTrue(warned(warnings, "because falcon-sensor.node.enabled is false"))

    def test_enabled_is_written_first_when_disabled(self):
        _, fcg, _ = migrate("falcon-sensor: {enabled: false, node: {clusterName: c1}}")
        self.assertEqual(list(fcg["nodeSensor"])[0], "enabled")

    def test_missing_node_block_warns(self):
        _, fcg, warnings = migrate("falcon-sensor: {container: {enabled: true}}")
        self.assertNotIn("nodeSensor", fcg)
        self.assertTrue(warned(warnings, "falcon-sensor.node block not found"))

    def test_namespace_override(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {enabled: true}}")
        self.assertEqual(fcg["namespaceOverride"], "falcon-system")
        _, fcg, _ = migrate("falcon-sensor: {namespaceOverride: custom-ns, node: {enabled: true}}")
        self.assertEqual(fcg["namespaceOverride"], "custom-ns")

    def test_copied_values_drop_source_blank_lines(self):
        out, _, _ = migrate("falcon-sensor:\n  node:\n    daemonset:\n      maxUnavailable: 2\n\n    podLabels: {a: b}\n")
        self.assertIn("    daemonset:\n      maxUnavailable: 2\n    podLabels:", dump(out))


class TestClusterguardController(unittest.TestCase):
    def test_direct_keys_are_copied(self):
        _, fcg, _ = migrate(FULL_PLATFORM_VALUES)
        ctrl = plain(fcg["clusterguardController"])
        src = plain(load(FULL_PLATFORM_VALUES)["falcon-kac"])
        for key in ("webhookPort", "watcherPort", "autoCertificateUpdate", "certExpiration", "domainName", "hostNetwork",
                    "dnsPolicy", "tolerations", "affinity", "annotations", "labels", "podAnnotations", "podLabels",
                    "autoDeploymentUpdate", "webhook", "resourceQuota"):
            self.assertEqual(ctrl[key], src[key], key)

    def test_replicas_is_dropped(self):
        _, fcg, _ = migrate("falcon-kac: {replicas: 2}")
        self.assertNotIn("replicas", fcg["clusterguardController"])

    def test_admission_control_defaults_to_the_old_kac_default(self):
        _, fcg, _ = migrate("falcon-kac: {webhookPort: 4443}")
        self.assertIs(fcg["clusterguardController"]["admissionControl"]["enabled"], True)

    def test_admission_control_explicit_false(self):
        _, fcg, _ = migrate("falcon-kac: {admissionControl: {enabled: false}}")
        self.assertIs(fcg["clusterguardController"]["admissionControl"]["enabled"], False)

    def test_disabled_kac_disables_admission_control(self):
        _, fcg, warnings = migrate("falcon-kac: {enabled: false, admissionControl: {enabled: true}}")
        self.assertIs(fcg["clusterguardController"]["admissionControl"]["enabled"], False)
        self.assertTrue(warned(warnings, "falcon-kac.enabled is false"))

    def test_resource_keys_are_renamed_with_comments(self):
        out, fcg, _ = migrate(FULL_PLATFORM_VALUES)
        resources = plain(fcg["clusterguardController"]["resources"])
        src = plain(load(FULL_PLATFORM_VALUES)["falcon-kac"])
        for old, (new, comment) in mig.RESOURCE_RENAMES.items():
            self.assertEqual(resources[new], src[old])
            self.assertRegex(dump(out), rf"\n +{new}: +{comment}\n")

    def test_source_comments_are_not_carried_over(self):
        out, _, _ = migrate("falcon-kac:\n  falconClientResources:  # sized for prod\n    limits:\n      memory: 1Gi\n")
        text = dump(out)
        self.assertIn("client:  # was: falconClientResources\n", text)
        self.assertNotIn("sized for prod", text)

    def test_service_account_defaults_to_the_old_chart_name(self):
        _, fcg, _ = migrate("falcon-kac: {webhookPort: 4443}")
        self.assertEqual(plain(fcg["clusterguardController"]["serviceAccount"]), {"name": "falcon-kac-sa"})

    def test_service_account_is_carried_over(self):
        _, fcg, _ = migrate("falcon-kac: {serviceAccount: {name: my-kac-sa, annotations: {x: y}}}")
        self.assertEqual(plain(fcg["clusterguardController"]["serviceAccount"]), {"name": "my-kac-sa", "annotations": {"x": "y"}})

    def test_cluster_visibility_becomes_visibility(self):
        _, fcg, _ = migrate("falcon-kac: {clusterVisibility: {resourceSnapshots: {enabled: false, interval: 2h}}}")
        self.assertEqual(plain(fcg["clusterguardController"]["visibility"]), {"resourceSnapshots": {"enabled": False, "interval": "2h"}})

    def test_cluster_name_moves_to_the_top_level(self):
        _, fcg, warnings = migrate("falcon-sensor: {node: {enabled: true}}\nfalcon-kac: {clusterName: kac-name}")
        self.assertEqual(fcg["clusterName"], "kac-name")
        self.assertNotIn("clusterName", fcg["nodeSensor"])
        self.assertNotIn("clusterName", fcg["clusterguardController"])
        self.assertFalse(warned(warnings, "conflicts"))

    def test_cluster_name_conflict_keeps_the_sensor_value(self):
        _, fcg, warnings = migrate("falcon-sensor: {node: {clusterName: s}}\nfalcon-kac: {clusterName: k}")
        self.assertEqual(fcg["clusterName"], "s")
        self.assertTrue(warned(warnings, "falcon-kac.clusterName='k' conflicts with falcon-sensor.node.clusterName='s'"))

    def test_identical_cluster_names_do_not_warn(self):
        _, _, warnings = migrate("falcon-sensor: {node: {clusterName: same}}\nfalcon-kac: {clusterName: same}")
        self.assertFalse(warned(warnings, "conflicts"))

    def test_image_analyzer_namespace_is_dropped_with_a_warning(self):
        _, fcg, warnings = migrate("falcon-kac: {falconImageAnalyzerNamespace: iar-ns}")
        self.assertNotIn("falconImageAnalyzerNamespace", fcg["clusterguardController"])
        self.assertTrue(warned(warnings, "falconImageAnalyzerNamespace has been omitted"))

    def test_missing_kac_warns(self):
        _, fcg, warnings = migrate("falcon-sensor: {node: {enabled: true}}")
        self.assertNotIn("clusterguardController", fcg)
        self.assertTrue(warned(warnings, "falcon-kac block not found"))


class TestSharedSettings(unittest.TestCase):
    def test_cluster_name_is_placed_before_image(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {enabled: true, clusterName: c1}}")
        keys = list(fcg)
        self.assertEqual(fcg["clusterName"], "c1")
        self.assertEqual(keys.index("clusterName"), keys.index("image") - 1)

    def test_cluster_name_precedence_is_sensor_then_kac_then_image_analyzer(self):
        _, fcg, warnings = migrate("""
falcon-sensor: {node: {clusterName: s}}
falcon-kac: {clusterName: k}
falcon-image-analyzer: {crowdstrikeConfig: {clusterName: i}}
""")
        self.assertEqual(fcg["clusterName"], "s")
        self.assertTrue(warned(warnings, "falcon-kac.clusterName='k' conflicts with falcon-sensor.node.clusterName='s'"))
        self.assertTrue(warned(warnings, "falcon-image-analyzer.crowdstrikeConfig.clusterName='i' conflicts with falcon-sensor.node.clusterName='s'"))

    def test_empty_cluster_names_are_ignored(self):
        _, fcg, warnings = migrate("falcon-sensor: {node: {clusterName: ''}}\nfalcon-kac: {clusterName: k}")
        self.assertEqual(fcg["clusterName"], "k")
        self.assertFalse(warned(warnings, "conflicts"))

    def test_no_cluster_name_without_a_source_value(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {enabled: true}}\nfalcon-kac: {enabled: true}")
        self.assertNotIn("clusterName", fcg)

    def test_falcon_values_merge_with_sensor_precedence(self):
        _, fcg, _ = migrate("""
falcon-sensor: {falcon: {cid: sensor-cid, billing: null}, node: {enabled: true}}
falcon-kac: {falcon: {cid: kac-cid, billing: metered, cloud: us-2}}
""")
        self.assertEqual(plain(fcg["falcon"]), {"cid": "sensor-cid", "billing": "metered", "cloud": "us-2"})

    def test_kac_trace_feature_and_tags_go_to_the_controller(self):
        _, fcg, _ = migrate("""
falcon-sensor: {falcon: {trace: info, tags: shared}, node: {enabled: true}}
falcon-kac: {falcon: {trace: debug, feature: f1, tags: kac-tag}}
""")
        self.assertEqual(plain(fcg["falcon"]), {"trace": "info", "tags": "shared"})
        self.assertEqual(plain(fcg["clusterguardController"]["falcon"]),
                         {"trace": "debug", "feature": "f1", "tags": "kac-tag"})

    def test_kac_values_matching_the_sensor_are_not_repeated(self):
        _, fcg, _ = migrate("""
falcon-sensor: {falcon: {trace: info, tags: shared}, node: {enabled: true}}
falcon-kac: {falcon: {trace: info, tags: shared}}
""")
        self.assertNotIn("falcon", fcg["clusterguardController"])

    def test_kac_default_trace_is_not_written(self):
        # falcon-kac's default trace (none) is also FCG's, so it needs no override.
        _, fcg, _ = migrate("falcon-sensor: {node: {enabled: true}}\nfalcon-kac: {falcon: {trace: none}}")
        self.assertNotIn("falcon", fcg["clusterguardController"])
        self.assertNotIn("falcon", fcg)

    def test_kac_trace_without_a_sensor_value_goes_to_the_controller(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {enabled: true}}\nfalcon-kac: {falcon: {trace: debug}}")
        self.assertEqual(plain(fcg["clusterguardController"]["falcon"]), {"trace": "debug"})
        self.assertNotIn("falcon", fcg)

    def test_controller_falcon_is_placed_after_admission_control(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {enabled: true}}\nfalcon-kac: {falcon: {trace: debug}}")
        keys = list(fcg["clusterguardController"])
        self.assertEqual(keys.index("falcon"), keys.index("admissionControl") + 1)

    def test_falcon_is_placed_after_image(self):
        _, fcg, _ = migrate("falcon-sensor: {falcon: {cid: c}, node: {enabled: true}}")
        keys = list(fcg)
        self.assertEqual(keys.index("falcon"), keys.index("image") + 1)

    def test_falcon_secret_from_sensor(self):
        _, fcg, _ = migrate("falcon-sensor: {falconSecret: {enabled: true, secretName: s}, node: {enabled: true}}")
        self.assertEqual(plain(fcg["falconSecret"]), {"enabled": True, "secretName": "s"})

    def test_falcon_secret_from_kac(self):
        _, fcg, _ = migrate("falcon-kac: {falconSecret: {enabled: true, secretName: k}}")
        self.assertEqual(plain(fcg["falconSecret"]), {"enabled": True, "secretName": "k"})

    def test_falcon_secret_sensor_takes_precedence(self):
        _, fcg, warnings = migrate("""
falcon-sensor: {falconSecret: {enabled: true, secretName: s}, node: {enabled: true}}
falcon-kac: {falconSecret: {enabled: true, secretName: k}}
""")
        self.assertEqual(fcg["falconSecret"]["secretName"], "s")
        self.assertTrue(warned(warnings, "falconSecret found in both"))

    def test_identical_falcon_secrets_do_not_warn(self):
        _, _, warnings = migrate("""
falcon-sensor: {falconSecret: {enabled: true, secretName: s}, node: {enabled: true}}
falcon-kac: {falconSecret: {enabled: true, secretName: s}}
""")
        self.assertFalse(warned(warnings, "falconSecret found in both"))

    def test_secrets_store_merges_with_sensor_precedence(self):
        _, fcg, _ = migrate("""
falcon-sensor: {secretsStore: {enabled: true, provider: azure}, node: {enabled: true}}
falcon-kac: {secretsStore: {enabled: false, azure: {vaultName: v}}}
""")
        self.assertEqual(plain(fcg["secretsStore"]), {"enabled": True, "provider": "azure", "azure": {"vaultName": "v"}})

    def test_empty_secrets_store_is_not_written(self):
        _, fcg, _ = migrate("falcon-sensor: {secretsStore: {enabled: false, provider: ''}, node: {enabled: true}}")
        self.assertNotIn("secretsStore", fcg)

    def test_openshift_written_when_enabled(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {openshift: {enabled: true}}}\nfalcon-kac: {openshift: {enabled: false, createSCC: true}}")
        self.assertEqual(plain(fcg["openshift"]), {"enabled": True, "createSCC": True})

    def test_openshift_written_when_create_scc_is_false(self):
        _, fcg, _ = migrate("falcon-kac: {openshift: {createSCC: false}}")
        self.assertEqual(plain(fcg["openshift"]), {"createSCC": False})

    def test_openshift_not_written_by_default(self):
        _, fcg, _ = migrate("falcon-sensor: {node: {openshift: {enabled: false}}}")
        self.assertNotIn("openshift", fcg)


class TestImageAnalyzer(unittest.TestCase):
    def iar(self, block, extra=""):
        return migrate(f"{extra}\nfalcon-image-analyzer:\n" + "".join(f"  {line}\n" for line in block.strip().splitlines()))

    def test_enabled_unless_explicitly_disabled(self):
        _, fcg, _ = self.iar("log: {verbosity: info}")
        self.assertIs(fcg["imageAnalyzer"]["enabled"], True)
        _, fcg, _ = self.iar("enabled: false")
        self.assertIs(fcg["imageAnalyzer"]["enabled"], False)

    def test_copied_keys(self):
        _, fcg, _ = migrate(FULL_PLATFORM_VALUES)
        ia = plain(fcg["imageAnalyzer"])
        src = plain(load(FULL_PLATFORM_VALUES)["falcon-image-analyzer"])
        for key in ("exclusions", "hostNetwork", "podAnnotations", "podLabels", "resources", "tolerations",
                    "priorityClassName", "nodeSelector", "watcher", "log", "iarAgentService", "privateRegistries",
                    "volumes", "volumeMounts", "proxyConfig"):
            self.assertEqual(ia[key], src[key], key)

    def test_deployment_mode_drops_daemonset_only_keys(self):
        _, fcg, _ = self.iar("""
deployment: {enabled: true}
securityContext: {privileged: true}
crowdstrikeConfig: {clientID: a, agentRuntime: crio, agentRuntimeSocket: unix:///crio.sock}
""")
        ia = plain(fcg["imageAnalyzer"])
        self.assertNotIn("mode", ia)
        self.assertNotIn("securityContext", ia)
        self.assertEqual(ia["crowdstrikeConfig"], {"clientID": "a"})

    def test_daemonset_mode(self):
        _, fcg, _ = self.iar("""
daemonset: {enabled: true}
securityContext: {privileged: true}
crowdstrikeConfig: {agentRuntime: crio, agentRuntimeSocket: unix:///crio.sock}
""")
        ia = plain(fcg["imageAnalyzer"])
        self.assertEqual(ia["mode"], "daemonset")
        self.assertEqual(ia["securityContext"], {"privileged": True})
        self.assertEqual(ia["crowdstrikeConfig"], {"agentRuntime": "crio", "agentRuntimeSocket": "unix:///crio.sock"})

    def test_keys_without_an_fcg_equivalent_warn(self):
        _, fcg, warnings = self.iar("""
replicaCount: 2
unknownKey: x
crowdstrikeConfig: {dockerAPIToken: t, somethingElse: y}
""")
        ia = plain(fcg["imageAnalyzer"])
        self.assertNotIn("replicaCount", ia)
        self.assertNotIn("crowdstrikeConfig", ia)
        for key in ("replicaCount", "unknownKey", "crowdstrikeConfig.dockerAPIToken", "crowdstrikeConfig.somethingElse"):
            self.assertTrue(warned(warnings, f"falcon-image-analyzer.{key} has no FCG equivalent"), key)

    def test_handled_keys_do_not_warn(self):
        _, _, warnings = self.iar("""
kac: {namespace: falcon-kac}
namespaceOverride: falcon-image-analyzer
global: {falcon: {cid: x}}
testing: {enabled: false}
deployment: {enabled: true}
""")
        self.assertFalse(warned(warnings, "has no FCG equivalent"))

    def test_cluster_name_moves_to_the_top_level(self):
        _, fcg, _ = self.iar("crowdstrikeConfig: {clusterName: iar-name}", "falcon-sensor: {node: {enabled: true}}")
        self.assertEqual(fcg["clusterName"], "iar-name")
        self.assertNotIn("clusterName", fcg["nodeSensor"])
        self.assertNotIn("clusterName", fcg["imageAnalyzer"].get("crowdstrikeConfig", {}))

    def test_cluster_name_conflict_keeps_the_node_value(self):
        _, fcg, warnings = self.iar("crowdstrikeConfig: {clusterName: iar-name}", "falcon-sensor: {node: {clusterName: node-name}}")
        self.assertEqual(fcg["clusterName"], "node-name")
        self.assertTrue(warned(warnings, "crowdstrikeConfig.clusterName='iar-name' conflicts with falcon-sensor.node.clusterName='node-name'"))

    def test_cluster_name_conflict_keeps_the_kac_value(self):
        _, fcg, warnings = self.iar("crowdstrikeConfig: {clusterName: iar-name}", "falcon-kac: {clusterName: kac-name}")
        self.assertEqual(fcg["clusterName"], "kac-name")
        self.assertTrue(warned(warnings, "crowdstrikeConfig.clusterName='iar-name' conflicts with falcon-kac.clusterName='kac-name'"))

    def test_cid_becomes_falcon_cid_after_image(self):
        _, fcg, _ = self.iar("crowdstrikeConfig: {cid: iar-cid}")
        self.assertEqual(fcg["falcon"]["cid"], "iar-cid")
        self.assertEqual(list(fcg).index("falcon"), list(fcg).index("image") + 1)

    def test_cid_is_not_written_when_a_global_cid_exists(self):
        _, fcg, warnings = self.iar("crowdstrikeConfig: {cid: iar-cid}", "global: {falcon: {cid: global-cid}}")
        self.assertNotIn("falcon", fcg)
        self.assertTrue(warned(warnings, "crowdstrikeConfig.cid differs"))

    def test_matching_cid_does_not_warn(self):
        _, _, warnings = self.iar("crowdstrikeConfig: {cid: same}", "falcon-sensor: {falcon: {cid: same}, node: {enabled: true}}")
        self.assertFalse(warned(warnings, "cid differs"))

    def test_existing_secret_warns(self):
        _, _, warnings = self.iar("crowdstrikeConfig: {existingSecret: iar-secret}")
        self.assertTrue(warned(warnings, "existingSecret='iar-secret' has no FCG equivalent"))

    def test_client_id_with_falcon_secret_warns(self):
        _, _, warnings = self.iar("crowdstrikeConfig: {clientID: a}",
                                  "falcon-sensor: {falconSecret: {enabled: true, secretName: s}, node: {enabled: true}}")
        self.assertTrue(warned(warnings, "clientSecret must be removed"))

    def test_pull_auth_used_when_fcg_has_none(self):
        _, fcg, _ = self.iar("image: {pullSecret: iar-secret}", "falcon-sensor: {node: {enabled: true}}")
        self.assertEqual(fcg["image"]["pullSecret"], "iar-secret")

    def test_pull_auth_ignored_when_fcg_has_some(self):
        _, fcg, _ = self.iar("image: {registryConfigJSON: e30=}", "falcon-sensor: {node: {image: {pullSecrets: s}}}")
        self.assertEqual(fcg["image"]["pullSecret"], "s")
        self.assertNotIn("registryConfigJSON", fcg["image"])

    def test_image_repository_tag_and_digest_are_dropped(self):
        _, fcg, warnings = self.iar("image: {repository: r, tag: t, digest: 'sha256:x'}")
        self.assertEqual(fcg["image"]["repository"], REPO)
        self.assertTrue(warned(warnings, "falcon-image-analyzer.image.repository, falcon-image-analyzer.image.tag, "
                                         "falcon-image-analyzer.image.digest omitted"))

    def test_openshift_merges_with_the_lowest_precedence(self):
        # kac (on OpenShift) wins over the image analyzer; sccName only exists in the image analyzer.
        _, fcg, _ = self.iar("openshift: {enabled: true, createSCC: false, sccName: my-scc}",
                             "falcon-kac: {openshift: {enabled: true, createSCC: true}}")
        self.assertEqual(plain(fcg["openshift"]), {"enabled": True, "createSCC": True, "iarSCCName": "my-scc"})

    def test_openshift_from_the_image_analyzer_alone(self):
        _, fcg, _ = self.iar("openshift: {enabled: true, createSCC: false}", "falcon-sensor: {node: {enabled: true}}")
        self.assertEqual(plain(fcg["openshift"]), {"enabled": True, "createSCC": False})

    def test_azure_moves_to_the_top_level(self):
        _, fcg, _ = self.iar("azure: {enabled: true, azureConfig: /etc/azure.json}", "falcon-sensor: {node: {enabled: true}}")
        self.assertEqual(plain(fcg["azure"]), {"enabled": True, "azureConfig": "/etc/azure.json"})
        self.assertLess(list(fcg).index("azure"), list(fcg).index("nodeSensor"))

    def test_gcp_enabled_becomes_gke_enabled(self):
        _, fcg, _ = self.iar("gcp: {enabled: true}", "falcon-sensor: {node: {gke: {autopilot: true}}}")
        self.assertEqual(plain(fcg["gke"]), {"enabled": True, "autopilot": True})
        _, fcg, _ = self.iar("gcp: {enabled: true}", "falcon-sensor: {node: {enabled: true}}")
        self.assertEqual(plain(fcg["gke"]), {"enabled": True})
        self.assertLess(list(fcg).index("gke"), list(fcg).index("nodeSensor"))

    def test_gcp_disabled_does_not_set_gke(self):
        _, fcg, _ = self.iar("gcp: {enabled: false}", "falcon-sensor: {node: {enabled: true}}")
        self.assertNotIn("gke", fcg)

    def test_secrets_store_warns(self):
        _, fcg, warnings = self.iar("secretsStore: {enabled: true}")
        self.assertNotIn("secretsStore", fcg)
        self.assertTrue(warned(warnings, "falcon-image-analyzer.secretsStore was omitted"))


class TestOutput(unittest.TestCase):
    def test_global_and_component_namespaces_pass_through(self):
        out, _, _ = migrate("global: {falcon: {cid: c}}\ncreateComponentNamespaces: true\nfalcon-sensor: {node: {enabled: true}}")
        self.assertEqual(plain(out["global"]), {"falcon": {"cid": "c"}})
        self.assertIs(out["createComponentNamespaces"], True)

    def test_source_charts_are_removed(self):
        out, _, _ = migrate(FULL_PLATFORM_VALUES)
        self.assertNotIn("falcon-kac", out)
        self.assertNotIn("falcon-image-analyzer", out)
        self.assertNotIn("falcon-sensor", out)

    def test_container_sensor_is_retained(self):
        out, _, _ = migrate("""
falcon-sensor:
  enabled: true
  namespaceOverride: falcon-system
  falcon: {cid: c}
  container: {enabled: true, image: {repository: r, tag: t}}
  node: {enabled: false, clusterName: c1}
""")
        sensor = plain(out["falcon-sensor"])
        self.assertEqual(set(sensor), {"container", "enabled", "namespaceOverride", "falcon"})
        self.assertIn("Retained for container sensor", dump(out))

    def test_disabled_container_sensor_is_removed(self):
        out, _, _ = migrate("falcon-sensor: {container: {enabled: false}, node: {enabled: true}}")
        self.assertNotIn("falcon-sensor", out)

    def test_deprecation_notes(self):
        text = dump(migrate("falcon-sensor: {node: {enabled: true}}")[0])
        for note in ("# falcon-sensor.node is deprecated — replaced by falcon-clusterguard.nodeSensor.*",
                     "# falcon-kac is deprecated — replaced by falcon-clusterguard.clusterguardController.*",
                     "# falcon-image-analyzer is deprecated — replaced by falcon-clusterguard.imageAnalyzer.*"):
            self.assertIn(note, text)


def migrate_text(values, admission_control=None, image_analyzer=None, tag=TAG, repo=REPO):
    """Run the same steps as main(): migrate, apply overrides, carry comments. Returns (text, warnings).

    values is a YAML string, or a dict of chart name to YAML string for standalone chart files.
    """
    if isinstance(values, dict):
        loaded = mig.CommentedMap((chart, load(text)) for chart, text in values.items())
    else:
        loaded = load(values)
    warnings = []
    out = mig.migrate(loaded, warnings, fcg_image_repo=repo, fcg_image_tag=tag)
    mig.apply_overrides(out, admission_control, image_analyzer)
    mig.carry_comments(mig.comment_sources(loaded), out, warnings)
    return dump(out), warnings


def unplaced(warnings):
    """The (path, comment) pairs listed in the comments-not-carried-over warning."""
    found = [w for w in warnings if w.startswith("These comments were not carried over")]
    if not found:
        return []
    return [tuple(line.strip().split(": ", 1)) for line in found[0].split("\n")[1:]]


class TestComments(unittest.TestCase):
    def assertLines(self, text, *expected):
        """Assert the expected lines appear consecutively in text."""
        self.assertIn("\n".join(expected) + "\n", text)

    def test_end_of_line_comment_on_a_key_copied_by_itself(self):
        text, _ = migrate_text("falcon-sensor:\n  node:\n    clusterName: c1   # matches the CMDB\n")
        self.assertIn("\n  clusterName: c1  # matches the CMDB\n", text)

    def test_comment_above_a_key_copied_by_itself(self):
        text, _ = migrate_text("falcon-kac:\n  webhookPort: 4443\n  # pinned by the firewall team\n  watcherPort: 4080\n")
        self.assertLines(text, "    webhookPort: 4443", "    # pinned by the firewall team", "    watcherPort: 4080")

    def test_comments_inside_a_moved_block(self):
        text, _ = migrate_text("""
falcon-sensor:
  node:
    daemonset:
      # spot nodes are tainted
      tolerations:
        - key: spot
      resources:
        requests:
          cpu: 500m   # raised after INC-123
""")
        self.assertLines(text, "    daemonset:", "      # spot nodes are tainted", "      tolerations:")
        self.assertLines(text, "          cpu: 500m  # raised after INC-123")

    def test_list_item_comments(self):
        text, _ = migrate_text("""
falcon-sensor:
  node:
    daemonset:
      tolerations:
        # first
        - key: a   # eol in item
          operator: Exists
        # second
        - key: b
""")
        self.assertLines(text, "      tolerations:", "        # first", "        - key: a  # eol in item",
                         "          operator: Exists", "        # second", "        - key: b")

    def test_header_is_kept_above_the_deprecation_notes(self):
        text, _ = migrate_text("# cluster prod-us-1\n# owner: platform team\nfalcon-sensor:\n  node: {enabled: true}\n")
        self.assertTrue(text.startswith("# cluster prod-us-1\n# owner: platform team\n\n# falcon-sensor.node is deprecated"))

    def test_comment_directly_above_the_first_key_is_the_keys(self):
        text, _ = migrate_text({"falcon-kac": "# kac file\n\n# strict in prod\nwebhook:\n  failurePolicy: Fail\n"},
                               admission_control=True)
        self.assertTrue(text.startswith("# kac file\n\n"))
        self.assertLines(text, "    # strict in prod", "    webhook:")

    def test_comment_above_a_chart_block_moves_to_its_fcg_block(self):
        text, _ = migrate_text("falcon-sensor:\n  node: {enabled: true}\n\n# KAC settings\nfalcon-kac:\n  webhookPort: 4443\n")
        # The script's blank line before clusterguardController is kept.
        self.assertLines(text, "", "  # KAC settings", "  clusterguardController:")

    def test_renamed_resource_key_keeps_both_comments(self):
        text, _ = migrate_text("falcon-kac:\n  falconWatcherResources:   # sized for 2k pods\n    limits:\n      memory: 1Gi\n")
        self.assertIn("      watcher:  # was: falconWatcherResources — sized for 2k pods\n", text)

    def test_renamed_keys(self):
        text, _ = migrate_text("""
falcon-sensor:
  node:
    image:
      pullSecrets: ps   # registry credentials
falcon-kac:
  clusterVisibility:   # visibility tuning
    resourceWatcher:
      enabled: true
falcon-image-analyzer:
  daemonset:   # socket mode for containerd
    enabled: true
  openshift:
    enabled: true
    sccName: my-scc   # pre-created SCC
""")
        self.assertIn("    pullSecret: ps  # registry credentials\n", text)
        self.assertIn("    visibility:  # visibility tuning\n", text)
        self.assertIn("    mode: daemonset  # socket mode for containerd\n", text)
        self.assertIn("    iarSCCName: my-scc  # pre-created SCC\n", text)

    def test_kac_trace_comment_moves_to_the_controller(self):
        text, _ = migrate_text("falcon-sensor:\n  node: {enabled: true}\nfalcon-kac:\n  falcon:\n    trace: debug   # noisy on purpose\n")
        self.assertLines(text, "  clusterguardController:", "    admissionControl:", "      enabled: true",
                         "    falcon:", "      trace: debug  # noisy on purpose")

    def test_cluster_name_from_kac_keeps_its_comment(self):
        text, _ = migrate_text("falcon-sensor:\n  node: {enabled: true}\nfalcon-kac:\n  clusterName: k1   # from kac\n")
        self.assertIn("\n  clusterName: k1  # from kac\n", text)

    def test_comments_on_dropped_keys_are_reported(self):
        text, warnings = migrate_text("""
falcon-sensor:
  node:
    backend: kernel   # legacy backend
    image:
      tag: "7.0"   # pinned old tag
falcon-kac:
  replicas: 2   # two for HA
""")
        self.assertEqual(sorted(unplaced(warnings)), [
            ("falcon-kac.replicas", "# two for HA"),
            ("falcon-sensor.node.backend", "# legacy backend"),
            ("falcon-sensor.node.image.tag", "# pinned old tag"),
        ])
        for comment in ("legacy backend", "pinned old tag", "two for HA"):
            self.assertNotIn(comment, text)

    def test_comment_on_a_changed_value_is_reported(self):
        text, warnings = migrate_text("falcon-kac:\n  enabled: false\n  admissionControl:\n    enabled: true   # on in prod\n")
        self.assertIn(("falcon-kac.admissionControl.enabled", "# on in prod"), unplaced(warnings))
        self.assertNotIn("on in prod", text)

    def test_comment_on_a_value_changed_by_an_override_is_reported(self):
        source = "falcon-kac:\n  admissionControl:\n    enabled: false   # off until CR-42\n"
        text, _ = migrate_text(source)
        self.assertIn("enabled: false  # off until CR-42", text)
        text, warnings = migrate_text(source, admission_control=True)
        self.assertNotIn("CR-42", text)
        self.assertIn(("falcon-kac.admissionControl.enabled", "# off until CR-42"), unplaced(warnings))

    def test_only_the_winning_sources_comment_is_kept(self):
        text, warnings = migrate_text("""
falcon-sensor:
  falcon:
    cid: S   # sensor cid
  node: {enabled: true}
falcon-kac:
  falcon:
    cid: K   # kac cid
""")
        self.assertIn("    cid: S  # sensor cid\n", text)
        self.assertIn(("falcon-kac.falcon.cid", "# kac cid"), unplaced(warnings))

    def test_retained_container_sensor_keeps_comments_in_both_copies(self):
        text, _ = migrate_text("""
falcon-sensor:
  enabled: true   # container sensor
  falcon:
    cid: C   # shared cid
  container:
    enabled: true
""")
        out = text.split("falcon-clusterguard:")
        self.assertIn("  enabled: true  # container sensor\n", out[0])
        self.assertIn("    cid: C  # shared cid\n", out[0])
        self.assertIn("    cid: C  # shared cid\n", out[1])

    def test_footer_comment_is_reported(self):
        _, warnings = migrate_text("falcon-sensor:\n  node: {enabled: true}\n# end of file\n")
        self.assertIn(("<end of file>", "# end of file"), unplaced(warnings))

    def test_block_scalar_content_is_not_a_comment(self):
        text, warnings = migrate_text("""
falcon-sensor:
  node:
    podAnnotations:
      note: |
        # part of the value
        more
    # about podLabels
    podLabels: {a: b}
""")
        self.assertEqual(text.count("# part of the value"), 1)
        self.assertLines(text, "    # about podLabels", "    podLabels: {a: b}")
        self.assertEqual(unplaced(warnings), [])

    def test_no_stray_blank_lines_from_the_source(self):
        text, _ = migrate_text("falcon-sensor:\n  node:\n    daemonset:\n      maxUnavailable: 2\n\n\n"
                               "falcon-kac:\n  webhook:\n    failurePolicy: Ignore   # default\n\n\n"
                               "falcon-image-analyzer:\n  enabled: true\n")
        self.assertLines(text, "      maxUnavailable: 2", "    serviceAccount:")
        self.assertLines(text, "      failurePolicy: Ignore  # default", "    serviceAccount:")

    def test_chart_files_are_read_separately(self):
        # The same line number in two files must not mix up their comments.
        text, _ = migrate_text({
            "falcon-sensor": "# sensor file\nnode:\n  clusterName: c1   # sensor name\n",
            "falcon-kac": "# kac file\nwebhookPort: 4443\nwatcherPort: 4080   # kac watcher\n",
        })
        self.assertTrue(text.startswith("# sensor file\n# kac file\n\n"))
        self.assertIn("\n  clusterName: c1  # sensor name\n", text)
        self.assertIn("    watcherPort: 4080  # kac watcher\n", text)

    def test_comments_do_not_change_the_migrated_values(self):
        commented = FULL_PLATFORM_VALUES.replace("clusterName: my-cluster", "clusterName: my-cluster  # c") \
            .replace("  falconClientResources:", "  # client\n  falconClientResources:  # sized")
        with_comments, _ = migrate_text(commented)
        without, _ = migrate_text(FULL_PLATFORM_VALUES)
        self.assertEqual(plain(load(with_comments)), plain(load(without)))

    def test_comment_sources(self):
        platform = load("falcon-sensor: {node: {enabled: true}}\n")
        self.assertEqual(mig.comment_sources(platform), [(platform, ())])
        combined = mig.CommentedMap([("falcon-sensor", load("node: {}\n")), ("falcon-kac", load("webhookPort: 1\n"))])
        self.assertEqual([prefix for _, prefix in mig.comment_sources(combined)], [("falcon-sensor",), ("falcon-kac",)])

    def test_extract_comments(self):
        header, notes, footer = mig.extract_comments(load(
            "# header\n\na: 1   # eol a\n# before b\nb:\n  - x   # eol item\n# footer\n"))
        self.assertEqual(header, ["# header"])
        self.assertEqual(notes[("a",)], {"before": [], "eol": "# eol a"})
        self.assertEqual(notes[("b",)], {"before": ["# before b"], "eol": None})
        self.assertEqual(notes[("b", 0)], {"before": [], "eol": "# eol item"})
        self.assertEqual(footer, [("<end of file>", "# footer")])

    def test_cli_keeps_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "v.yaml"
            f.write_text("# my cluster\nfalcon-sensor:\n  node:\n    clusterName: c1   # cmdb name\n    backend: bpf   # old\n")
            result = run_cli("--platform-values", str(f), "--dry-run")
        self.assertTrue(result.stdout.startswith("# my cluster\n"))
        self.assertIn("clusterName: c1  # cmdb name", result.stdout)
        self.assertIn("falcon-sensor.node.backend: # old", result.stderr)


class TestApplyOverrides(unittest.TestCase):
    def test_overrides_create_blocks(self):
        out, fcg, _ = migrate("falcon-sensor: {node: {enabled: true}}")
        mig.apply_overrides(out, admission_control_override=True, image_analyzer_override=False)
        self.assertIs(fcg["clusterguardController"]["admissionControl"]["enabled"], True)
        self.assertIs(fcg["imageAnalyzer"]["enabled"], False)

    def test_overrides_replace_migrated_values(self):
        out, fcg, _ = migrate("falcon-kac: {admissionControl: {enabled: true}}\nfalcon-image-analyzer: {enabled: true}")
        mig.apply_overrides(out, admission_control_override=False, image_analyzer_override=False)
        self.assertIs(fcg["clusterguardController"]["admissionControl"]["enabled"], False)
        self.assertIs(fcg["imageAnalyzer"]["enabled"], False)

    def test_no_overrides(self):
        out, fcg, _ = migrate("falcon-sensor: {node: {enabled: true}}")
        before = dump(out)
        mig.apply_overrides(out, None, None)
        self.assertEqual(dump(out), before)


def fcg_value_paths():
    """Dotted paths defined by the FCG chart's values.yaml and values.schema.json."""
    paths = set()

    def walk_values(d, prefix=""):
        for k, v in d.items():
            p = f"{prefix}{k}"
            paths.add(p)
            if isinstance(v, dict):
                walk_values(v, p + ".")

    def walk_schema(s, prefix=""):
        for k, v in (s.get("properties") or {}).items():
            p = f"{prefix}{k}"
            paths.add(p)
            walk_schema(v, p + ".")

    walk_values(YAML(typ="safe").load((FCG_CHART / "values.yaml").read_text()))
    walk_schema(json.loads((FCG_CHART / "values.schema.json").read_text()))
    return paths


# Maps whose contents are Kubernetes objects or user-defined keys, so their children aren't listed
# in values.yaml. clusterguardController.resources is the exception: its children are fixed.
FREE_FORM_KEYS = {
    "resources", "limits", "requests", "tolerations", "affinity", "annotations", "labels", "podAnnotations",
    "podLabels", "dnsConfig", "podSecurityContext", "securityContext", "nodeSelector", "volumes", "volumeMounts",
}
FIXED_CHILD_PATHS = {"clusterguardController.resources"}
# Set by falcon-platform on its subcharts rather than defined in the FCG values.
SUBCHART_KEYS = {"enabled", "namespaceOverride"}


class TestChartContract(unittest.TestCase):
    """The migrated values must use only keys the falcon-clusterguard chart defines."""

    def test_every_written_key_exists_in_the_fcg_chart(self):
        out, fcg, _ = migrate(FULL_PLATFORM_VALUES, fcg_image_tag=TAG)
        mig.apply_overrides(out, True, True)
        known = fcg_value_paths()
        unknown = []

        def walk(d, prefix=""):
            for k, v in d.items():
                p = f"{prefix}{k}"
                if p in known:
                    if isinstance(v, dict) and (k not in FREE_FORM_KEYS or p in FIXED_CHILD_PATHS):
                        walk(v, p + ".")
                elif not (k in FREE_FORM_KEYS and prefix.rstrip(".") not in FIXED_CHILD_PATHS) and p not in SUBCHART_KEYS:
                    unknown.append(p)

        walk(plain(fcg))
        self.assertEqual(unknown, [], "migrated keys that falcon-clusterguard does not define")

    @unittest.skipUnless(shutil.which("helm"), "helm is not installed")
    def test_migrated_values_render(self):
        out, fcg, _ = migrate(FULL_PLATFORM_VALUES, fcg_image_tag=TAG)
        mig.apply_overrides(out, True, True)
        with tempfile.TemporaryDirectory() as tmp:
            values = Path(tmp) / "values.yaml"
            values.write_text(dump(fcg))
            result = subprocess.run(
                ["helm", "template", "t", str(FCG_CHART), "-n", "falcon-system", "-f", str(values)],
                capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        for kind in ("kind: DaemonSet", "kind: Deployment", "kind: ValidatingWebhookConfiguration"):
            self.assertIn(kind, result.stdout)


def run_cli(*args, cwd=None, tag=True, repo=True):
    """Run the script in a subprocess. Adds --fcg-image-repo and --fcg-image-tag unless repo=False or
    tag=False, since stdin isn't a TTY and the script would otherwise exit asking for them."""
    # helm is left off PATH so release detection falls back to its defaults.
    env = dict(os.environ, PATH="/usr/bin:/bin")
    extra = []
    if "--help" not in args:
        extra += ["--fcg-image-repo", REPO] if repo else []
        extra += ["--fcg-image-tag", TAG] if tag else []
    return subprocess.run([sys.executable, str(SCRIPT), *args, *extra], capture_output=True, text=True, cwd=cwd,
                          env=env, stdin=subprocess.DEVNULL)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text):
        path = self.tmp / name
        path.write_text(text)
        return str(path)

    def test_help(self):
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0)
        for flag in ("--admission-control", "--fcg-image-tag", "--fcg-image-digest"):
            self.assertIn(flag, result.stdout)
        self.assertIn("generally available", result.stdout)

    def test_an_input_mode_is_required(self):
        result = run_cli(tag=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("one of the arguments", result.stderr)

    def test_input_modes_are_mutually_exclusive(self):
        f = self.write("v.yaml", "{}\n")
        result = run_cli("--platform-values", f, "--sensor-values", f)
        self.assertEqual(result.returncode, 2)

    def test_chart_files_cannot_be_combined_with_platform_values(self):
        f = self.write("v.yaml", "{}\n")
        result = run_cli("--platform-values", f, "--kac-values", f, "--dry-run")
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot be used with --platform-values", result.stderr)

    def test_invalid_bool_flags(self):
        f = self.write("v.yaml", "{}\n")
        for flag in ("--admission-control", "--image-analyzer"):
            result = run_cli("--platform-values", f, flag, "maybe", "--dry-run")
            self.assertEqual(result.returncode, 2, flag)
            self.assertIn(f"{flag}: Expected true/false", result.stderr)

    def test_tag_or_digest_is_required_without_a_terminal(self):
        f = self.write("v.yaml", "falcon-sensor: {node: {enabled: true}}\n")
        result = run_cli("--platform-values", f, "--dry-run", tag=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("an FCG image tag or digest (--fcg-image-tag or --fcg-image-digest) is required", result.stderr)
        self.assertIn("generally available", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_repository_is_required_without_a_terminal(self):
        f = self.write("v.yaml", "falcon-sensor: {node: {enabled: true}}\n")
        result = run_cli("--platform-values", f, "--dry-run", repo=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("an FCG image repository (--fcg-image-repo) is required", result.stderr)
        self.assertIn("generally available", result.stderr)
        result = run_cli("--platform-values", f, "--dry-run", repo=False, tag=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("an FCG image repository (--fcg-image-repo) and an FCG image tag or digest "
                      "(--fcg-image-tag or --fcg-image-digest) are required", result.stderr)

    def test_invalid_repository_flag(self):
        f = self.write("v.yaml", "{}\n")
        result = run_cli("--platform-values", f, "--dry-run", "--fcg-image-repo", "registry.example.com/fcg:1.0.0",
                         repo=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--fcg-image-repo: invalid image repository", result.stderr)

    def test_invalid_tag_and_digest_flags(self):
        f = self.write("v.yaml", "{}\n")
        result = run_cli("--platform-values", f, "--dry-run", "--fcg-image-tag", "bad tag", tag=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--fcg-image-tag: invalid image tag", result.stderr)
        result = run_cli("--platform-values", f, "--dry-run", "--fcg-image-digest", "sha256:abc", tag=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--fcg-image-digest: invalid image digest", result.stderr)

    def test_digest_flag(self):
        f = self.write("v.yaml", "falcon-sensor: {node: {enabled: true}}\n")
        result = run_cli("--platform-values", f, "--dry-run", "--fcg-image-digest", "c" * 64, tag=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        image = plain(load(result.stdout)["falcon-clusterguard"]["image"])
        self.assertEqual(image, {"repository": REPO, "digest": "sha256:" + "c" * 64})

    def test_platform_values_dry_run(self):
        f = self.write("platform.yaml", FULL_PLATFORM_VALUES)
        result = run_cli("--platform-values", f, "--dry-run", "--fcg-image-tag", "9.9.9", tag=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        fcg = load(result.stdout)["falcon-clusterguard"]
        self.assertEqual(fcg["image"]["tag"], "9.9.9")
        self.assertIs(fcg["clusterguardController"]["admissionControl"]["enabled"], True)
        self.assertIs(fcg["imageAnalyzer"]["enabled"], True)
        self.assertIn("MIGRATION WARNINGS", result.stderr)
        self.assertFalse((self.tmp / "platform.fcg-migrated.yaml").exists())

    def test_platform_values_without_kac_or_iar_disable_them(self):
        f = self.write("platform.yaml", "falcon-sensor: {node: {enabled: true}}\n")
        result = run_cli("--platform-values", f, "--dry-run")
        fcg = load(result.stdout)["falcon-clusterguard"]
        self.assertIs(fcg["clusterguardController"]["admissionControl"]["enabled"], False)
        self.assertIs(fcg["imageAnalyzer"]["enabled"], False)

    def test_override_flags(self):
        f = self.write("platform.yaml", FULL_PLATFORM_VALUES)
        result = run_cli("--platform-values", f, "--dry-run", "--admission-control", "false", "--image-analyzer", "no")
        fcg = load(result.stdout)["falcon-clusterguard"]
        self.assertIs(fcg["clusterguardController"]["admissionControl"]["enabled"], False)
        self.assertIs(fcg["imageAnalyzer"]["enabled"], False)

    def test_individual_chart_files(self):
        platform = load(FULL_PLATFORM_VALUES)
        sensor = self.write("sensor.yaml", dump(platform["falcon-sensor"]))
        kac = self.write("kac.yaml", dump(platform["falcon-kac"]))
        iar = self.write("iar.yaml", dump(platform["falcon-image-analyzer"]))
        result = run_cli("--sensor-values", sensor, "--kac-values", kac, "--iar-values", iar, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = mig.migrate(load(FULL_PLATFORM_VALUES), [], fcg_image_repo=REPO, fcg_image_tag=TAG)["falcon-clusterguard"]
        actual = load(result.stdout)["falcon-clusterguard"]
        self.assertEqual(plain(actual), plain(expected))

    def test_individual_sensor_only_disables_kac_and_iar(self):
        sensor = self.write("sensor.yaml", "node: {enabled: true}\n")
        result = run_cli("--sensor-values", sensor, "--dry-run")
        fcg = load(result.stdout)["falcon-clusterguard"]
        self.assertIs(fcg["clusterguardController"]["admissionControl"]["enabled"], False)
        self.assertIs(fcg["imageAnalyzer"]["enabled"], False)

    def test_writes_the_default_output_file(self):
        f = self.write("platform.yaml", "falcon-sensor: {node: {enabled: true}}\n")
        result = run_cli("--platform-values", f)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.tmp / "platform.fcg-migrated.yaml"
        self.assertIn("falcon-clusterguard", load(output.read_text()))
        self.assertIn(f"Migrated values written to: {output}", result.stdout)
        self.assertIn("helm upgrade falcon-platform crowdstrike/falcon-platform", result.stdout)

    def test_writes_the_output_flag_path(self):
        f = self.write("platform.yaml", "falcon-sensor: {node: {enabled: true}}\n")
        output = self.tmp / "custom.yaml"
        result = run_cli("--platform-values", f, "--output", str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.exists())

    def test_refuses_to_overwrite_the_input(self):
        f = self.write("platform.yaml", "falcon-sensor: {node: {enabled: true}}\n")
        result = run_cli("--platform-values", f, "--output", f)
        self.assertEqual(result.returncode, 1)
        self.assertIn("would overwrite input file", result.stderr)
        self.assertEqual(Path(f).read_text(), "falcon-sensor: {node: {enabled: true}}\n")

    def test_readme_example_matches_the_output(self):
        text = README.read_text()
        section = text[text.index("## Example"):]

        def block(after, lang="yaml"):
            start = section.index(f"```{lang}\n", section.index(after)) + len(f"```{lang}\n")
            return section[start:section.index("```", start)]

        f = self.write("my-values.yaml", block("Input (`my-values.yaml`):"))
        # Run the documented command, with the input file path swapped in.
        command = shlex.split(block("Run:", "bash").replace("\\\n", " "))
        self.assertEqual(command[:2], ["python3", "scripts/migration/migrate-to-fcg.py"])
        args = [f if a == "my-values.yaml" else a for a in command[2:]]
        result = run_cli(*args, tag=False, repo=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, block("Output:"), "scripts/migration/README.md example output is out of date")


class TTYInput(io.StringIO):
    """stdin stand-in that reports being a terminal."""

    def isatty(self):
        return True


class TestMainPrompt(unittest.TestCase):
    """main() prompts for the image tag or digest when stdin is a terminal and no flag is set."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.values = Path(self._tmp.name) / "v.yaml"
        self.values.write_text("falcon-sensor: {node: {enabled: true}}\n")

    def tearDown(self):
        self._tmp.cleanup()

    def run_main(self, answers, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ["migrate-to-fcg.py", "--platform-values", str(self.values), "--dry-run", *args]
        with mock.patch("sys.argv", argv), mock.patch("sys.stdin", TTYInput(answers)), \
                mock.patch("sys.stderr", stderr), mock.patch.object(mig, "_detect_release", return_value=("r", "ns")), \
                redirect_stdout(stdout):
            mig.main()
        return load(stdout.getvalue())["falcon-clusterguard"]["image"], stderr.getvalue()

    def test_prompts_for_the_repository_and_a_tag(self):
        image, stderr = self.run_main(f"{REPO}\n8.14.0-12345-1\n")
        self.assertEqual(plain(image), {"repository": REPO, "tag": "8.14.0-12345-1"})
        self.assertLess(stderr.index("FCG image repository (for example"), stderr.index("FCG image tag, or digest"))

    def test_prompts_for_a_digest(self):
        image, _ = self.run_main("sha256:" + "d" * 64 + "\n", "--fcg-image-repo", REPO)
        self.assertEqual(image["digest"], "sha256:" + "d" * 64)
        self.assertNotIn("tag", image)

    def test_prompts_only_for_what_is_missing(self):
        image, stderr = self.run_main(f"{REPO}\n", "--fcg-image-tag", "1.0.0")
        self.assertEqual(plain(image), {"repository": REPO, "tag": "1.0.0"})
        self.assertNotIn("FCG image tag, or digest", stderr)

    def test_no_prompt_when_flags_are_set(self):
        image, stderr = self.run_main("", "--fcg-image-repo", REPO, "--fcg-image-tag", "1.0.0")
        self.assertEqual(plain(image), {"repository": REPO, "tag": "1.0.0"})
        self.assertNotIn("FCG image", stderr)


def completed(stdout="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class TestWizard(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text):
        path = self.tmp / name
        path.write_text(text)
        return str(path)

    def run_wizard(self, answers, helm=None, image_answer=f"{REPO}\n{TAG}\n", **kwargs):
        """Run the wizard with scripted input() answers, image repository and tag answers on stdin,
        and a fake subprocess.run for helm. Returns the wizard's result as a dict."""
        def fake_run(cmd, **_):
            if helm is None:
                raise FileNotFoundError("helm")
            return helm(cmd)

        with mock.patch("builtins.input", side_effect=answers), \
                mock.patch("sys.stdin", io.StringIO(image_answer)), \
                mock.patch.object(mig.subprocess, "run", side_effect=fake_run), \
                redirect_stdout(io.StringIO()):
            result = mig.run_wizard(mig.make_yaml(), **kwargs)
        names = ("values", "label", "repo", "tag", "digest", "release", "ns", "ac", "ia")
        self.assertEqual(len(result), len(names))
        return dict(zip(names, result))

    @staticmethod
    def helm_list(releases, values_yaml=""):
        def helm(cmd):
            if cmd[1] == "list":
                return completed(json.dumps(releases))
            if cmd[1] == "get":
                return completed(values_yaml)
            raise AssertionError(cmd)
        return helm

    def test_umbrella_file_with_a_discovered_release(self):
        f = self.write("v.yaml", "falcon-sensor: {node: {enabled: true}}\nfalcon-kac: {webhookPort: 4443}\nfalcon-image-analyzer: {}\n")
        releases = [{"name": "falcon", "chart": "falcon-platform-1.0.0", "namespace": "falcon-platform"}]
        r = self.run_wizard(["1", "2", f, "", ""], helm=self.helm_list(releases))
        self.assertIn("falcon-kac", r["values"])
        self.assertEqual(r["label"], f)
        self.assertEqual((r["repo"], r["tag"], r["digest"]), (REPO, TAG, None))
        self.assertEqual((r["release"], r["ns"]), ("falcon", "falcon-platform"))
        self.assertIs(r["ac"], True)   # falcon-kac present, so the old default (true) is offered
        self.assertIs(r["ia"], True)   # falcon-image-analyzer block present

    def test_image_prompt_accepts_a_digest_and_asks_again(self):
        f = self.write("v.yaml", "{}\n")
        digest = "sha256:" + "e" * 64
        r = self.run_wizard(["rel", "ns", "2", f, "", ""], image_answer=f"{REPO}\n\nnot valid!\n{digest}\n")
        self.assertEqual((r["tag"], r["digest"]), (None, digest))

    def test_cli_image_flags_skip_the_image_prompt(self):
        f = self.write("v.yaml", "{}\n")
        digest = "sha256:" + "f" * 64
        r = self.run_wizard(["rel", "ns", "2", f, "", ""], image_answer="", cli_image_repo=REPO, cli_image_digest=digest)
        self.assertEqual((r["repo"], r["tag"], r["digest"]), (REPO, None, digest))
        r = self.run_wizard(["rel", "ns", "2", f, "", ""], image_answer=f"{TAG}\n", cli_image_repo="my.reg/fcg")
        self.assertEqual((r["repo"], r["tag"]), ("my.reg/fcg", TAG))
        r = self.run_wizard(["rel", "ns", "2", f, "", ""], image_answer=f"{REPO}\n", cli_image_tag="2.0.0")
        self.assertEqual((r["repo"], r["tag"], r["digest"]), (REPO, "2.0.0", None))

    def test_admission_control_defaults_to_false_without_kac(self):
        f = self.write("v.yaml", "falcon-sensor: {node: {enabled: true}}\n")
        r = self.run_wizard(["falcon", "falcon-platform", "2", f, "", ""])
        self.assertIs(r["ac"], False)
        self.assertIs(r["ia"], False)

    def test_admission_control_defaults_to_false_when_kac_was_disabled(self):
        f = self.write("v.yaml", "falcon-kac: {enabled: false}\n")
        r = self.run_wizard(["falcon", "falcon-platform", "2", f, "", ""])
        self.assertIs(r["ac"], False)

    def test_explicit_answers_and_cli_overrides(self):
        f = self.write("v.yaml", "falcon-kac: {admissionControl: {enabled: true}}\n")
        r = self.run_wizard(["falcon", "falcon-platform", "2", f, "false", "true"])
        self.assertEqual((r["ac"], r["ia"]), (False, True))
        # CLI flags skip both prompts.
        r = self.run_wizard(["falcon", "falcon-platform", "2", f], cli_admission_control=True, cli_image_analyzer=False)
        self.assertEqual((r["ac"], r["ia"]), (True, False))

    def test_manual_release_mirror_registry_and_chart_files(self):
        sensor = self.write("sensor.yaml", "node: {enabled: true}\n")
        r = self.run_wizard(["rel", "ns", "3", sensor, "", "", "", ""], image_answer="my.reg/fcg\n1.2.3\n")
        self.assertEqual(list(r["values"]), ["falcon-sensor"])
        self.assertEqual(r["label"], sensor)
        self.assertEqual((r["repo"], r["tag"], r["release"], r["ns"]), ("my.reg/fcg", "1.2.3", "rel", "ns"))
        self.assertEqual((r["ac"], r["ia"]), (False, False))

    def test_extract_values_from_the_release(self):
        r = self.run_wizard(["rel", "ns", "1", "", ""],
                            helm=self.helm_list([], values_yaml="falcon-kac:\n  webhookPort: 4443\n"))
        self.assertEqual(plain(r["values"]), {"falcon-kac": {"webhookPort": 4443}})
        self.assertEqual(r["label"], "rel-extracted")
        self.assertIs(r["ac"], True)

    def test_extract_with_no_user_values(self):
        r = self.run_wizard(["rel", "ns", "1", "", ""], helm=self.helm_list([], values_yaml="null\n"))
        self.assertEqual(r["values"], {})

    def test_missing_file_is_an_input_error(self):
        with self.assertRaisesRegex(mig.InputError, "missing.yaml: file not found"):
            self.run_wizard(["rel", "ns", "2", str(self.tmp / "missing.yaml")])

    def test_wrong_kind_of_file_is_an_input_error(self):
        f = self.write("sensor.yaml", "node: {enabled: true}\n")
        with self.assertRaisesRegex(mig.InputError, "looks like a standalone falcon-sensor values file"):
            self.run_wizard(["rel", "ns", "2", f])

    def test_individual_file_for_the_wrong_chart_is_an_input_error(self):
        f = self.write("kac.yaml", "admissionControl: {enabled: true}\n")
        with self.assertRaisesRegex(mig.InputError, "looks like a falcon-kac values file, not a falcon-sensor"):
            self.run_wizard(["rel", "ns", "3", f, "", ""])

    def test_invalid_menu_choice_is_asked_again(self):
        f = self.write("v.yaml", "{}\n")
        r = self.run_wizard(["rel", "ns", "9", "x", "2", f, "", ""])
        self.assertEqual(r["release"], "rel")


class TestNextSteps(unittest.TestCase):
    def next_steps(self, fcg):
        buf = io.StringIO()
        with redirect_stdout(buf):
            mig.print_next_steps("out.yaml", "in.yaml", "falcon", "falcon-platform", {"falcon-clusterguard": fcg})
        return buf.getvalue()

    def test_all_components(self):
        text = self.next_steps({"namespaceOverride": "fcg-ns", "imageAnalyzer": {"enabled": True}})
        self.assertIn("helm upgrade falcon crowdstrike/falcon-platform", text)
        self.assertIn("-f out.yaml", text)
        self.assertIn("kubectl rollout status daemonset/falcon-sensor -n fcg-ns", text)
        self.assertIn("kubectl rollout status deployment/falcon-clusterguard-controller -n fcg-ns", text)
        self.assertIn("-l app=falcon-image-analyzer", text)

    def test_disabled_components_are_skipped(self):
        text = self.next_steps({"nodeSensor": {"enabled": False}})
        self.assertNotIn("daemonset/", text)
        self.assertNotIn("falcon-image-analyzer", text.split("4)")[0])


def nested(path, value):
    """A falcon-platform values mapping with value at path."""
    for key in reversed(path):
        value = {key: value}
    return value


class TestLoadValues(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.yaml = mig.make_yaml()

    def load_text(self, text, name="v.yaml"):
        f = self.tmp / name
        f.write_bytes(text) if isinstance(text, bytes) else f.write_text(text)
        return mig.load_values(self.yaml, str(f))

    def test_a_mapping_loads(self):
        self.assertEqual(plain(self.load_text("falcon-sensor: {node: {enabled: true}}\n")),
                         {"falcon-sensor": {"node": {"enabled": True}}})

    def test_missing_file(self):
        with self.assertRaisesRegex(mig.InputError, "missing.yaml: file not found"):
            mig.load_values(self.yaml, str(self.tmp / "missing.yaml"))

    def test_directory(self):
        with self.assertRaisesRegex(mig.InputError, "is a directory, not a values file"):
            mig.load_values(self.yaml, str(self.tmp))

    def test_binary_file(self):
        with self.assertRaisesRegex(mig.InputError, "not a UTF-8 text file"):
            self.load_text(b"\xff\xfe\x00")

    def test_invalid_yaml_reports_the_line_and_column(self):
        with self.assertRaisesRegex(mig.InputError, r"v.yaml, line 3, column 1: invalid YAML: expected the node content"):
            self.load_text("falcon-sensor:\n  node: [\n")

    def test_duplicate_keys(self):
        with self.assertRaisesRegex(mig.InputError, r"line 4, column 3: invalid YAML: found duplicate key \"node\""):
            self.load_text("falcon-sensor:\n  node: {enabled: true}\n  # again\n  node: {enabled: false}\n")

    def test_undefined_alias(self):
        with self.assertRaisesRegex(mig.InputError, "found undefined alias 'y'"):
            self.load_text("a: &x [1]\nb: *y\n")

    def test_empty_file(self):
        with self.assertRaisesRegex(mig.InputError, "no values found.*helm get values <release>"):
            self.load_text("")

    def test_comment_only_file(self):
        with self.assertRaisesRegex(mig.InputError, "no values found"):
            self.load_text("# nothing here\n")

    def test_top_level_list(self):
        with self.assertRaisesRegex(mig.InputError, "expected a mapping of values at the top level, got a list"):
            self.load_text("- a\n- b\n")

    def test_top_level_scalar(self):
        with self.assertRaisesRegex(mig.InputError, "got a string \\('just text'\\)"):
            self.load_text("just text\n")

    def test_empty_mapping_is_allowed(self):
        self.assertEqual(plain(self.load_text("{}\n")), {})


class TestInputKind(unittest.TestCase):
    def test_platform_file_passes(self):
        mig.check_platform_file(load("falcon-sensor: {node: {enabled: true}}\n"), "p.yaml")

    def test_platform_file_with_only_global_passes(self):
        mig.check_platform_file(load("global: {falcon: {cid: x}}\n"), "p.yaml")

    def test_standalone_files_are_rejected_as_platform_values(self):
        for chart, text in (("falcon-sensor", "node: {enabled: true}\n"),
                            ("falcon-kac", "admissionControl: {enabled: true}\n"),
                            ("falcon-image-analyzer", "crowdstrikeConfig: {clientID: x}\n")):
            with self.subTest(chart), self.assertRaisesRegex(
                    mig.InputError, f"looks like a standalone {chart} values file, not a falcon-platform"):
                mig.check_platform_file(load(text), "p.yaml")

    def test_migrated_values_are_rejected(self):
        for text in ("falcon-clusterguard: {enabled: true}\n", "nodeSensor: {enabled: true}\n",
                     "falcon-kac: {}\nfalcon-clusterguard: {}\n"):
            with self.subTest(text), self.assertRaisesRegex(mig.InputError, "already migrated"):
                mig.check_platform_file(load(text), "p.yaml")
            with self.subTest(text), self.assertRaisesRegex(mig.InputError, "already migrated"):
                mig.check_chart_file(load(text), "s.yaml", "falcon-sensor")

    def test_chart_files_pass(self):
        mig.check_chart_file(load("node: {enabled: true}\n"), "s.yaml", "falcon-sensor")
        mig.check_chart_file(load("admissionControl: {enabled: true}\n"), "k.yaml", "falcon-kac")
        mig.check_chart_file(load("crowdstrikeConfig: {clientID: x}\n"), "i.yaml", "falcon-image-analyzer")

    def test_chart_file_without_distinctive_keys_passes(self):
        mig.check_chart_file(load("falcon: {cid: x}\n"), "s.yaml", "falcon-sensor")

    def test_platform_file_is_rejected_as_chart_values(self):
        with self.assertRaisesRegex(mig.InputError, "has a top-level falcon-kac key.*--platform-values p.yaml"):
            mig.check_chart_file(load("falcon-kac: {enabled: true}\n"), "p.yaml", "falcon-sensor")

    def test_file_for_another_chart_is_rejected(self):
        with self.assertRaisesRegex(mig.InputError, "looks like a falcon-kac values file, not a falcon-sensor.*--kac-values"):
            mig.check_chart_file(load("admissionControl: {enabled: true}\n"), "k.yaml", "falcon-sensor")
        with self.assertRaisesRegex(mig.InputError, "looks like a falcon-sensor values file, not a falcon-image-analyzer.*--sensor-values"):
            mig.check_chart_file(load("node: {enabled: true}\n"), "s.yaml", "falcon-image-analyzer")


class TestStructure(unittest.TestCase):
    def assertRejected(self, values, fragment):
        with self.assertRaises(mig.InputError) as ctx:
            mig.migrate(load(dump(values)), [])
        self.assertIn(fragment, str(ctx.exception))

    def test_every_block_must_be_a_mapping(self):
        for path in mig.MAPPING_PATHS:
            for bad in ("text", ["a"], True, 3):
                with self.subTest(path=path, value=bad):
                    self.assertRejected(nested(path, bad), f"{'.'.join(path)} must be a mapping, got")

    def test_flags_must_be_booleans(self):
        for path in mig.BOOL_PATHS:
            with self.subTest(path=path):
                self.assertRejected(nested(path, "false"), f"{'.'.join(path)} must be true or false, got a string ('false')")

    def test_names_must_be_strings(self):
        for path in mig.STRING_PATHS:
            with self.subTest(path=path):
                self.assertRejected(nested(path, ["a"]), f"{'.'.join(path)} must be a string, got a list")

    def test_null_values_are_allowed(self):
        for path in mig.MAPPING_PATHS + mig.BOOL_PATHS + mig.STRING_PATHS:
            with self.subTest(path=path):
                mig.migrate(load(dump(nested(path, None))), [])

    def test_every_problem_is_listed(self):
        with self.assertRaises(mig.InputError) as ctx:
            migrate("falcon-sensor: {node: {enabled: 'yes', image: x}}\nfalcon-kac: {admissionControl: true}")
        message = str(ctx.exception)
        for fragment in ("falcon-sensor.node.enabled must be true or false", "falcon-sensor.node.image must be a mapping",
                         "falcon-kac.admissionControl must be a mapping"):
            self.assertIn(fragment, message)

    def test_the_full_platform_values_pass(self):
        mig.check_structure(load(FULL_PLATFORM_VALUES))


class TestUnknownKeys(unittest.TestCase):
    def test_typos_are_reported(self):
        _, _, warnings = migrate("""
falcon-sesnor: {node: {enabled: true}}
falcon-sensor:
  node: {enabled: true, daemonSet: {}}
  nodeOverride: x
falcon-kac: {webhookPrt: 1}
""")
        for fragment in ("falcon-sesnor is not a falcon-platform value, so it was omitted",
                         "falcon-sensor.node.daemonSet is not a falcon-sensor value, so it was omitted",
                         "falcon-sensor.nodeOverride is not a falcon-sensor value",
                         "falcon-kac.webhookPrt is not a falcon-kac value"):
            self.assertTrue(warned(warnings, fragment), fragment)

    def test_unknown_falcon_options_are_reported_and_copied(self):
        _, fcg, warnings = migrate("falcon-sensor: {falcon: {trase: debug}, node: {enabled: true}}")
        self.assertTrue(warned(warnings, "falcon-sensor.falcon.trase is not a falconctl option. It was copied"))
        self.assertEqual(fcg["falcon"]["trase"], "debug")

    def test_known_keys_are_not_reported(self):
        _, _, warnings = migrate(FULL_PLATFORM_VALUES)
        self.assertFalse(warned(warnings, "check it for a typo"), warnings)
        self.assertFalse(warned(warnings, "Check it for a typo"), warnings)

    def test_every_documented_source_key_is_known(self):
        # Keys in the standalone charts' values.yaml on main must not be reported as typos.
        for chart, path in (("falcon-sensor", ("falcon-sensor",)), ("falcon-kac", ("falcon-kac",))):
            result = subprocess.run(["git", "show", f"main:helm-charts/{chart}/values.yaml"], cwd=REPO_ROOT,
                                    capture_output=True, text=True)
            if result.returncode != 0:
                self.skipTest("main branch charts are not available")
            keys = set(load(result.stdout))
            self.assertEqual(keys - mig.KNOWN_KEYS[path], set(), chart)


class TestCLIInputErrors(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def write(self, name, text):
        f = self.tmp / name
        f.write_text(text)
        return str(f)

    def assertInputError(self, result, fragment):
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("ERROR: ", result.stderr)
        self.assertIn(fragment, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_missing_file(self):
        self.assertInputError(run_cli("--platform-values", str(self.tmp / "nope.yaml"), "--dry-run"), "file not found")

    def test_invalid_yaml(self):
        f = self.write("bad.yaml", "falcon-sensor: [\n")
        self.assertInputError(run_cli("--platform-values", f, "--dry-run"), "invalid YAML")

    def test_wrong_input_flag(self):
        f = self.write("platform.yaml", "falcon-sensor: {node: {enabled: true}}\nfalcon-kac: {admissionControl: {enabled: true}}\n")
        self.assertInputError(run_cli("--sensor-values", f, "--dry-run"), "Use --platform-values")

    def test_wrong_chart_file(self):
        s = self.write("s.yaml", "node: {enabled: true}\n")
        k = self.write("k.yaml", "crowdstrikeConfig: {clientID: x}\n")
        self.assertInputError(run_cli("--sensor-values", s, "--kac-values", k, "--dry-run"),
                              "looks like a falcon-image-analyzer values file, not a falcon-kac values file")

    def test_wrong_value_type(self):
        f = self.write("v.yaml", "falcon-kac: {admissionControl: true}\n")
        self.assertInputError(run_cli("--platform-values", f, "--dry-run"),
                              "falcon-kac.admissionControl must be a mapping, got a boolean (true)")

    def test_no_output_file_is_written_on_an_input_error(self):
        f = self.write("v.yaml", "falcon-kac: {admissionControl: true}\n")
        run_cli("--platform-values", f)
        self.assertFalse((self.tmp / "v.fcg-migrated.yaml").exists())


class TestValidate(unittest.TestCase):
    GOOD = f"global: {{falcon: {{cid: {CID}}}}}\nfalcon-sensor: {{node: {{enabled: true}}}}\n"
    LOW_MEMORY = (f"global: {{falcon: {{cid: {CID}}}}}\n"
                  "falcon-sensor: {node: {enabled: true, daemonset: {resources: {requests: {memory: 256Mi}}}}}\n")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def write(self, name, text):
        f = self.tmp / name
        f.write_text(text)
        return str(f)

    def test_requires_helm(self):
        # run_cli leaves helm off PATH.
        result = run_cli("--platform-values", self.write("v.yaml", self.GOOD), "--dry-run", "--validate")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--validate requires helm", result.stderr)

    def test_default_chart_is_the_repository_chart(self):
        self.assertEqual(Path(mig.default_fcg_chart()), FCG_CHART.resolve())

    @unittest.skipUnless(shutil.which("helm"), "helm is not installed")
    def test_valid_values_render(self):
        out, _, _ = migrate(self.GOOD, fcg_image_tag=TAG)
        self.assertIsNone(mig.validate_with_helm(out, str(FCG_CHART), mig.make_yaml()))

    @unittest.skipUnless(shutil.which("helm"), "helm is not installed")
    def test_invalid_values_return_the_helm_error(self):
        out, _, _ = migrate(self.LOW_MEMORY, fcg_image_tag=TAG)
        error = mig.validate_with_helm(out, str(FCG_CHART), mig.make_yaml())
        self.assertIn("nodeSensor.daemonset.resources.requests.memory must be at least 512Mi", error)
        self.assertNotIn("--debug", error)

    @unittest.skipUnless(shutil.which("helm"), "helm is not installed")
    def test_cli_reports_validation(self):
        env_path = f"{Path(shutil.which('helm')).parent}:/usr/bin:/bin"
        def cli(text, *extra):
            f = self.write("v.yaml", text)
            return subprocess.run([sys.executable, str(SCRIPT), "--platform-values", f, "--fcg-image-repo", REPO,
                                   "--fcg-image-tag", TAG, "--validate", *extra],
                                  capture_output=True, text=True, env=dict(os.environ, PATH=env_path),
                                  stdin=subprocess.DEVNULL)
        ok = cli(self.GOOD, "--dry-run")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("The migrated values render with", ok.stderr)
        self.assertTrue(ok.stdout.startswith("global:"))
        bad = cli(self.LOW_MEMORY)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("VALIDATION FAILED", bad.stderr)
        self.assertIn("must be at least 512Mi", bad.stderr)
        self.assertIn("were still written to", bad.stderr)
        self.assertTrue((self.tmp / "v.fcg-migrated.yaml").exists())
        self.assertNotIn("Next steps", bad.stdout)


if __name__ == "__main__":
    unittest.main()
