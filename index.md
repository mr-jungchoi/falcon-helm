# CrowdStrike Falcon Helm Repository

<br><br>
### Add the CrowdStrike Falcon Helm repository

```
helm repo add jchoi_cs https://mr-jungchoi.github.io/falcon-helm
```

<br>
### Install CrowdStrike Falcon Helm Chart for KAC

```
helm upgrade --install falcon-helm jchoi_cs/falcon-kac \
    --set falcon.cid="<CrowdStrike_CID>" \
    --set node.image.repository="<Your_Registry>/falcon-kac"
```

Above command will install the CrowdStrike Falcon Helm Chart with the release name `falcon-helm` in the namespace your `kubectl` context is currently set to.
You can also install into a customized namespace by running the following:

```
helm upgrade --install falcon-helm crowdstrike/falcon-kac \
    -n falcon-system --create-namespace \
    --set falcon.cid="<CrowdStrike_CID>" \
    --set node.image.repository="<Your_Registry>/falcon-kac"
``` 

For more details please see the [falcon-helm](https://github.com/CrowdStrike/falcon-helm) repository.
