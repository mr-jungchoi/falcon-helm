{{/*
Test-specific helper functions for Helm chart tests.
These helpers are only used by test manifests and are not part of the production deployment.
*/}}

{{/*
Turn a block of labels (the output of a *SelectorLabels helper) into a kubectl label selector,
so the tests select pods with exactly the labels the workload selects them with.

Usage: {{ include "falcon-clusterguard.testLabelSelector" (include "falcon-clusterguard.nodeSelectorLabels" .) }}
*/}}
{{- define "falcon-clusterguard.testLabelSelector" -}}
{{- $selector := list -}}
{{- range $key, $value := fromYaml . -}}
{{- $selector = append $selector (printf "%s=%s" $key $value) -}}
{{- end -}}
{{- join "," $selector -}}
{{- end -}}

{{/*
POSIX shell functions shared by the test pod scripts. Every check prints [OK] or [FAIL];
a failure sets FAILED=1 and the script keeps going, so one run reports every problem.
The kubectl image runs the scripts with /bin/sh, so the functions avoid bash-only syntax.

Usage (inside the script block): {{- include "falcon-clusterguard.testShellFunctions" . | nindent 8 }}
*/}}
{{- define "falcon-clusterguard.testShellFunctions" -}}
FAILED=0
NS="{{ include "falcon-clusterguard.namespace" . }}"

ok() { echo "[OK]: $*"; }
fail() { echo "[FAIL]: $*"; FAILED=1; }

# check_equal <description> <actual> <expected>
check_equal() {
  if [ "$2" = "$3" ]; then ok "$1 is '$3'"; else fail "$1 is '$2', expected '$3'"; fi
}

# check_set <description> <actual>
check_set() {
  if [ -n "$2" ]; then ok "$1 is set"; else fail "$1 is not set"; fi
}

# check_exists <kind> <name>. Also works for cluster-scoped kinds: kubectl ignores -n for them.
check_exists() {
  if kubectl get "$1" "$2" -n "${NS}" > /dev/null 2>&1; then ok "$1 '$2' exists"; else fail "$1 '$2' not found"; fi
}

# check_absent <kind> <name>
check_absent() {
  if kubectl get "$1" "$2" -n "${NS}" > /dev/null 2>&1; then fail "$1 '$2' exists but should not"; else ok "$1 '$2' does not exist"; fi
}

# check_rollout <deployment|daemonset> <name>
check_rollout() {
  if kubectl rollout status "$1" "$2" -n "${NS}" --timeout=300s; then ok "$1 '$2' is rolled out"; else fail "$1 '$2' did not become ready"; fi
}

# check_pods_running <description> <label selector>. Sets PODS to the matching pod names.
check_pods_running() {
  PODS=$(kubectl get pods -n "${NS}" -l "$2" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null)
  if [ -z "${PODS}" ]; then fail "no $1 pods match '$2'"; return; fi
  NOT_RUNNING=$(kubectl get pods -n "${NS}" -l "$2" --field-selector=status.phase!=Running -o jsonpath='{.items[*].metadata.name}' 2>/dev/null)
  if [ -n "${NOT_RUNNING}" ]; then
    fail "$1 pods are not running: ${NOT_RUNNING}"
    kubectl get pods -n "${NS}" -l "$2"
  else
    ok "all $1 pods are running: ${PODS}"
  fi
}

# check_pods <description> <jsonpath> <expected>. Checks every pod in PODS.
check_pods() {
  for POD in ${PODS}; do
    check_equal "pod '${POD}' $1" "$(kubectl get pod "${POD}" -n "${NS}" -o jsonpath="$2" 2>&1)" "$3"
  done
}

# check_pods_set <description> <jsonpath>. Checks every pod in PODS.
check_pods_set() {
  for POD in ${PODS}; do
    check_set "pod '${POD}' $1" "$(kubectl get pod "${POD}" -n "${NS}" -o jsonpath="$2" 2>&1)"
  done
}

# check_secret_keys <secret> <keys...>. Only checks that each key has data; never prints values.
check_secret_keys() {
  NAME="$1"; shift
  if ! kubectl get secret "${NAME}" -n "${NS}" > /dev/null 2>&1; then fail "Secret '${NAME}' not found"; return; fi
  for KEY in "$@"; do
    KEY_PATH=$(echo "${KEY}" | sed 's/\./\\./g')
    if [ -n "$(kubectl get secret "${NAME}" -n "${NS}" -o jsonpath="{.data.${KEY_PATH}}" 2>/dev/null)" ]; then
      ok "Secret '${NAME}' contains ${KEY}"
    else
      fail "Secret '${NAME}' does not contain ${KEY}"
    fi
  done
}

# check_endpoints <service>. Retries for 30 seconds: endpoints can trail the rollout slightly.
check_endpoints() {
  for RETRY in 1 2 3 4 5 6; do
    ADDRESSES=$(kubectl get endpointslices -n "${NS}" -l "kubernetes.io/service-name=$1" \
      -o jsonpath='{.items[*].endpoints[?(@.conditions.ready==true)].addresses[*]}' 2>/dev/null)
    if [ -n "${ADDRESSES}" ]; then ok "Service '$1' has ready endpoints: ${ADDRESSES}"; return; fi
    sleep 5
  done
  fail "Service '$1' has no ready endpoints; its selector matches no ready pod"
}

# finish: print the summary and exit with the test result.
finish() {
  if [ "${FAILED}" -eq 1 ]; then echo "[FAIL]: Some checks failed"; exit 1; fi
  echo "[PASS]: All checks passed"
  exit 0
}
{{- end -}}
