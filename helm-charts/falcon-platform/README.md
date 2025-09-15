# CrowdStrike Falcon Platform Helm Chart

A comprehensive Helm chart that deploys the complete CrowdStrike Falcon Kubernetes runtime security platform. This chart manages all individual Falcon components as dependencies, providing a unified deployment and configuration experience.

## Overview

The Falcon Platform Helm chart allows you to deploy and manage the entire CrowdStrike Falcon Kubernetes runtime security stack with a single Helm installation. It coordinates the deployment of multiple security components while providing centralized configuration management and deployment orchestration.

## Components Included

| Component                 | Purpose                                | Default Status | Requirements                           |
|---------------------------|----------------------------------------|----------------|----------------------------------------|
| **Falcon Sensor**         | Runtime node protection and monitoring | Enabled        | CID                                    |
| **Falcon KAC**            | Kubernetes admission controller        | Enabled        | CID                                    |
| **Falcon Image Analyzer** | Container image vulnerability scanning | Disabled       | CID + OAuth credentials + cluster name |

## Prerequisites
### Minimum Requirements
- Kubernetes 1.22+
- Helm 3.x
- CrowdStrike Customer ID (CID)
- Appropriate cluster permissions (cluster-admin for installation)
- Falcon registry access to pull Falcon component docker images

## Quick Start

### 1. Add the Helm Repository

```bash
helm repo add crowdstrike https://crowdstrike.github.io/falcon-helm
helm repo update
```

### 2. Minimal Installation

Deploy core security components (Sensor + Admission Controller):

```bash
helm install falcon-platform ./helm-charts/falcon-platform/ -n falcon-platform \
--create-namespace \
--set global.falcon.cid=$FALCON_CID \
--set global.docker.registryConfigJSON=$DOCKER_CONFIG_ENCODED \
--set falcon-sensor.node.image.repository=$SENSOR_DOCKER_REGISTRY \
--set falcon-sensor.node.image.tag=7.28.0-18108-1.falcon-linux.Release.US-2 \
--set falcon-kac.image.repository=$KAC_DOCKER_REGISTRY \
--set falcon-kac.image.tag=7.27.0-2502.Release.US-2
```

### 3. Comprehensive Installation

Deploy all components (requires additional configuration):

```bash
helm install falcon-platform ./helm-charts/falcon-platform/ -n falcon-platform \
--create-namespace \
--set global.falcon.cid=$FALCON_CID \
--set global.docker.registryConfigJSON=$DOCKER_CONFIG_ENCODED \
--set falcon-sensor.node.image.repository=$SENSOR_DOCKER_REGISTRY \
--set falcon-sensor.node.image.tag=7.28.0-18108-1.falcon-linux.Release.US-2 \
--set falcon-kac.image.repository=$KAC_DOCKER_REGISTRY \
--set falcon-kac.image.tag=7.27.0-2502.Release.US-2 \
--set falcon-image-analyzer.enabled=true \
--set falcon-image-analyzer.image.repository=$IMAGE_ANALYZER_DOCKER_REGISTRY \
--set falcon-image-analyzer.image.tag=1.0.20 \
--set falcon-image-analyzer.crowdstrikeConfig.clusterName=$CLUSTER_NAME \
--set falcon-image-analyzer.crowdstrikeConfig.clientID=$FALCON_CLIENT_ID \
--set falcon-image-analyzer.crowdstrikeConfig.clientSecret=$FALCON_CLIENT_SECRET
```

## Configuration

### Global Configuration
Global settings apply to all components unless overridden:

```yaml
global:
  falcon:
    cid: "YOUR_CID_HERE"                 # Required for all components unless using an existing secret with CID data
    
  # Global Falcon Secret configuration
  # Alternative to falcon.cid for falcon-sensor and falcon-kac
  # Alternative to crowdstrikeConfig.clientId and crowdstrikeConfig.clientSecret for falcon-image-analyzer
  falconSecret:
    enabled: true
    secretName: "name-of-falcon-secret"  # Name of secret with sensitive data necessary for Falcon component installation
  
  # Global docker registry configuration for pulling Falcon component images
  # Should only use one of pullSecret or registryConfigJSON, not both
  # falcon-sensor container installation requires registryConfigJSON
  docker:
    pullSecret: "name-of-pull-secret"       # Name of existing docker registry secret
    registryConfigJSON: "BASE64_ENCODED"    # Your docker config json in a base64 encoded format
```

### Component-Specific Configuration

Each component can be individually configured. Component-specific values override global settings:

```yaml
# Enable/disable components
falcon-sensor:
  enabled: true
  # All falcon-sensor chart values can be specified here
  # Global falconSecret will be inherited if not specified
  
falcon-kac:
  enabled: true
  # All falcon-kac chart values can be specified here  
  # Global falconSecret will be inherited if not specified

# Components requiring additional configuration  
falcon-image-analyzer:
  enabled: false  # Disabled by default
  crowdstrikeConfig:
    clusterName: ""   # Required
    clientID: ""      # Required if not using global.falconSecret
    clientSecret: ""  # Required if not using global.falconSecret
```

### Using External Secrets (WIP)

Instead of specifying sensitive values directly in Helm values, you can use Kubernetes secrets:

```yaml
global:
  # Option 1: Use CID directly (less secure)
  falcon:
    cid: "YOUR_CID_HERE"
    
  # Option 2: Use external secret (more secure)
  falconSecret:
    enabled: true
    secretName: falcon-secret
```

When using `falconSecret`, create the secret beforehand:

```bash
# Create secret with required Falcon credentials
kubectl create secret generic falcon-secret -n falcon-platform \
  --from-literal=FALCONCTL_OPT_CID=$FALCON_CID \
  --from-literal=FALCONCTL_OPT_PROVISIONING_TOKEN=$FALCON_PROVISIONING_TOKEN \
  --from-literal=AGENT_CLIENT_ID=$FALCON_CLIENT_ID \                            # Required for Image Analyzer only
  --from-literal=AGENT_CLIENT_SECRET=$FALCON_CLIENT_SECRET                      # Required for Image Analyzer only
```


### Component-Specific Requirements (WIP)

**Falcon Image Analyzer:**
- OAuth API credentials (Client ID + Secret)
- Kubernetes cluster name
- Container registry access


## Deployment Scenarios (WIP)

### Scenario 1: Basic Production Setup

Core runtime protection and admission control:

```yaml
global:
  falcon:
    cid: "YOUR_CID"

falcon-sensor:
  enabled: true

falcon-kac:
  enabled: true

# falcon-image-analyzer disabled by default
```

### Scenario 2: Comprehensive Security

Full security coverage with scanning and monitoring:

```yaml
global:
  falcon:
    cid: "YOUR_CID"
    cloud_region: "us-1"

falcon-sensor:
  enabled: true

falcon-kac:
  enabled: true

falcon-image-analyzer:
  enabled: true
  crowdstrikeConfig:
    clientID: "CLIENT_ID"
    clientSecret: "CLIENT_SECRET"
    agentRegion: "us-1"  
    clusterName: "production-cluster"

```


## Verification (WIP)

### Check Installation Status (WIP)

```bash
# Check all pods in the falcon namespace
kubectl get pods -n falcon-platform

# Check individual component status
helm status falcon-platform -n falcon-platform

# View component logs
kubectl logs -n falcon-platform -l app.kubernetes.io/managed-by=falcon-platform
```

### Verify Component Health

```bash
# Sensor status (should show DaemonSet pods on all nodes)
# Falcon Sensor is deployed to falcon-sensor namespace by default
kubectl get daemonset -n falcon-sensor

# KAC webhook registration
# Falcon KAC is deployed to falcon-kac namespace by default
kubectl get validatingadmissionwebhook | grep falcon

# Image analyzer deployment
# Falcon Image Analyzer is deployed to falcon-image-analyzer namespace by default
kubectl get deployment -n falcon-image-analyzer | grep image-analyzer
```

## Troubleshooting (WIP)

### Common Issues

1. **Missing CID**: Ensure `global.falcon.cid` is set
2. **Image Pull Errors**: Configure `global.docker.registryConfigJSON` if using private registries

### Component Logs

```bash
# Sensor logs
kubectl logs -n falcon-platform -l app=falcon-sensor

# KAC logs  
kubectl logs -n falcon-platform -l app=falcon-kac

# Image analyzer logs
kubectl logs -n falcon-platform -l app=falcon-image-analyzer
```

## Upgrade Strategy

### Upgrade the Umbrella Chart

```bash
# Update repository
helm repo update

helm dependency update falcon-platform crowdstrike/falcon-platform

# Upgrade with existing values
helm upgrade falcon-platform crowdstrike/falcon-platform \
  -n falcon-platform \
  -f your-values.yaml
```

### Individual Component Updates

**IMPORTANT NOTE:** You cannot control exactly which helm chart version is being used for each individual Falcon component subchart.

Component versions are managed through the umbrella chart's dependencies. The dependent subchart versions are locked.
Update the umbrella chart to get the latest Falcon component helm chart versions for each subchart.

## Uninstall

```bash
# Remove Falcon Platform and all components
helm uninstall falcon-platform -n falcon-platform

# Optionally delete the release namespace, and the namespace for each Falcon component subchart
kubectl delete namespace falcon-platform
kubectl delete namespace falcon-sensor
kubectl delete namespace falcon-kac
kubectl delete namespace falcon-image-analyzer
```
