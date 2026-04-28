## Advanced GPU Observability with Inspektor Gadget on Kubernetes

This guide contains the instructions to deploy Inspektor Gadget and Pyroscope on
a Kubernetes cluster to profile GPU workloads. The profiles are then visualized
with Grafana.

### Prerequisities

You must have an AKS cluster with at least one GPU node:

```bash
$ kubectl get node -l accelerator=nvidia
NAME                              STATUS   ROLES    AGE    VERSION
aks-nodepool1-29354345-vmss000000 Ready    <none>   4h11m  v1.33.6
```

This [script](https://github.com/eiffel-fl/azure-scripts/blob/f398eb017bf3/az-aks.sh) can help you achieve this.

### Deploying

The following steps are needed to deploy the components:

```bash
$ bash deploy-stack -n your_resource_group -g named_wanted_for_grafana -k your_aks_cluster
...
Everything is ready, you can now access Grafana from: https://...cus.grafana.azure.com.
Do not forget to remove it with: az grafana delete -n named_wanted_for_grafana -g your_resource_group --no-wait.
```

### Testing

The following steps will run a job accessing the GPU, Inspektor Gadget will then
profile the memory operation from the CUDA library and will send the profiles to
pyroscope. The profiles can then be displayed with Grafana.

```bash
$ kubectl apply -f gpu-testload.yaml
```

You should be able to see our dashboard at the address printed by `deploy-stack.sh`:

![Memory consumption metrics](./images/dashboard1.png)

![Memory allocation rate](./images/dashboard2.png)

![Memory profiles](./images/dashboard3.png)

Please refer to the [How to Read Flamegraphs](./how-to-read-flamegraphs.md) guide for tips on how to analyze the profiles.
