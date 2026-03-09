# ig-gpu-instructions

> **Early-stage proof of concept.** This repository exists to support experimentation and exploration—it is **not** a production-ready offering.

An early-stage GPU observability proof of concept built on top of [Inspektor Gadget](https://inspektor-gadget.io/), eBPF-based gadgets, [Prometheus](https://prometheus.io/), [Grafana](https://grafana.com/), and [Pyroscope](https://grafana.com/oss/pyroscope/). The first iteration focuses on **CUDA GPU memory visibility in Kubernetes** (and Docker).

---

## Overview

Modern GPU workloads—ML training jobs, inference servers, HPC applications—are largely opaque from the operating-system perspective. This project explores how eBPF tooling from the Inspektor Gadget ecosystem can be used to observe CUDA memory allocation and kernel activity without any application-level changes.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         GPU Node / Cluster                          │
│                                                                     │
│  ┌─────────────┐    eBPF probes    ┌──────────────────────────┐    │
│  │  GPU        │ ─────────────────▶│  Inspektor Gadget        │    │
│  │  Workload   │                   │  (profile_cuda /         │    │
│  │  (CUDA)     │                   │   cuda_memory_metrics)   │    │
│  └─────────────┘                   └──────────┬───────────────┘    │
│                                               │                     │
│                            ┌──────────────────┼──────────────────┐ │
│                            ▼                  ▼                  │ │
│                     ┌────────────┐    ┌────────────────┐         │ │
│                     │ Pyroscope  │    │  Prometheus    │         │ │
│                     │ (profiles) │    │  (metrics)     │         │ │
│                     └──────┬─────┘    └───────┬────────┘         │ │
│                            └──────────────────┘                  │ │
│                                        │                         │ │
│                                        ▼                         │ │
│                                 ┌────────────┐                   │ │
│                                 │  Grafana   │                   │ │
│                                 │ dashboards │                   │ │
│                                 └────────────┘                   │ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Components

### Inspektor Gadget eBPF Gadgets

Two eBPF-based gadgets power the observability layer:

| Gadget | Purpose |
|--------|---------|
| `profile_cuda` | Profiles CUDA memory operations using ustack sampling and ships continuous profiling data to Pyroscope via OpenTelemetry. |
| `cuda_memory_metrics` | Tracks CUDA / cuDNN memory allocation and deallocation calls and exposes them as OpenTelemetry metrics scraped by Prometheus. |

Both gadgets run as privileged containers (or as `ig` on the host) and require no changes to the observed workload.

### Prometheus

[Prometheus](https://prometheus.io/) scrapes the `cuda_memory_metrics` gadget's OpenTelemetry metrics endpoint and stores time-series data for GPU memory allocation stats (`libcuda_mem_stats`, `libcudart_mem_stats`).

Configuration: [`docker/prometheus/`](docker/prometheus/)

### Grafana

[Grafana](https://grafana.com/) provides a unified dashboard that combines:

- **Metrics** from Prometheus (memory allocation counters, sizes, etc.)
- **Continuous profiles** from Pyroscope (flame graphs of CUDA call stacks)

Default dashboard is pre-provisioned at `http://<host>:3000/d/gmv2zv/gpu-observability`.

Configuration: [`docker/grafana-provisioning/`](docker/grafana-provisioning/)

### Pyroscope

[Grafana Pyroscope](https://grafana.com/oss/pyroscope/) stores and queries continuous profiling data. The `profile_cuda` gadget ships OpenTelemetry profiles to Pyroscope, which Grafana then renders as interactive flame graphs.

### Docker Compose Deployment

A self-contained stack for a single GPU host: see [`docker/`](docker/) for the `docker-compose.yml` and [`docker/README.md`](docker/README.md) for setup instructions.

Services started by `docker compose up`:

- `pyroscope` — profiling backend
- `grafana` — dashboards
- `prometheus` — metrics storage
- `ig_profile_cuda` — CUDA profiling gadget
- `ig_cuda_memory_metrics` — CUDA memory metrics gadget
- `cuda_sample_tf_mnist` — example GPU workload (TF MNIST demo)

### Kubernetes / Helm Deployment

An umbrella Helm chart deploys Inspektor Gadget (as a DaemonSet), Pyroscope, and Grafana onto an AKS (or any GPU-enabled) cluster: see [`kubernetes/charts/`](kubernetes/charts/) and [`kubernetes/charts/README.md`](kubernetes/charts/README.md).

---

## Testload

[`testload/`](testload/) contains a PyTorch-based GPU memory stress workload designed to exercise the observability stack and validate that the gadgets correctly capture a wide range of allocation patterns:

| Pattern | Description |
|---------|-------------|
| Steady allocation | Allocates a fixed tensor and holds it for several seconds |
| Incremental staircase | Allocates memory in equal-sized steps and then frees in reverse |
| Sawtooth | Repeatedly allocates and immediately frees to create a sawtooth curve |
| Mixed sizes | Allocates several tensors of different sizes simultaneously |
| Matrix multiply | Runs `torch.mm` in a loop to generate compute + memory activity |

The workload is packaged as a container image (`ghcr.io/inspektor-gadget/testgpu:latest`) and can be deployed on Kubernetes using [`kubernetes/gpu-testload.yaml`](kubernetes/gpu-testload.yaml).

```bash
# Quick run (adjust --max-mb to fit your GPU)
docker run --gpus all ghcr.io/inspektor-gadget/testgpu:latest \
  --duration 120 --interval 1 --max-mb 256

# On Kubernetes
kubectl apply -f kubernetes/gpu-testload.yaml
```

### Contributing Testload Patterns

We welcome contributions of new GPU memory allocation and compute patterns! If you have a workload shape that exposes interesting behaviour—fragmentation, concurrent allocations, large batch spikes, etc.—please open a pull request against [`testload/main.py`](testload/main.py). Good contributions typically:

- Add a clearly named function (e.g. `fragmentation_allocation()`)
- Include a short docstring explaining the pattern and why it is interesting
- Call the new function from `main()` in the main loop

---

## Repository Structure

```
.
├── docker/                  # Docker Compose deployment
│   ├── docker-compose.yml
│   ├── grafana-provisioning/
│   ├── ig/                  # Inspektor Gadget config
│   ├── prometheus/
│   └── README.md
├── kubernetes/              # Kubernetes / Helm deployment
│   ├── charts/              # Umbrella Helm chart
│   └── gpu-testload.yaml    # Test workload Pod spec
├── testload/                # GPU memory test workload
│   ├── Dockerfile
│   └── main.py
└── setup.sh                 # Host setup script (drivers, IG, Docker)
```

---

## Getting Started

Choose the deployment that matches your environment:

- **Single GPU host (Docker)** → follow [`docker/README.md`](docker/README.md)
- **Kubernetes cluster with GPU nodes** → follow [`kubernetes/charts/README.md`](kubernetes/charts/README.md)

---

## Disclaimer

This is an **experimental proof of concept**. APIs, gadget names, Helm values, and configuration formats may change at any time. Use it to learn, experiment, and contribute—but do not rely on it for production workloads.
