# IG + GPU PoC Instructions

This guide contains the instructions to test the Advanced GPU observability
PoC.

## 0. Get a machine with a GPU

We have access to the `Standard NC40ads H100 v5 (40 vcpus, 320 GiB memory)` VM
on the `South Central US (Zone 1)` region our `AzCoreLinux eBPF tools`
subscripton.

## 1. Install the NVIDIA driver and other tools

```bash
#! /bin/bash
sudo apt-get update

# Install drivers, cuda, and dcgm
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/cuda-keyring_1.0-1_all.deb
sudo dpkg -i cuda-keyring_1.0-1_all.deb
sudo add-apt-repository -y "deb https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/ /"
sudo apt-get update
sudo apt-get install -y datacenter-gpu-manager cuda-drivers

# Enable dcgm server (nv-hostengine)
sudo systemctl --now enable nvidia-dcgm

# Try them
dcgmi discovery -l
nvidia-smi

# docker
sudo apt-get install -y docker.io

# needed to run containers using the gpu
# https://stackoverflow.com/a/77269071
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

sudo groupadd docker
sudo usermod -aG docker $USER

# or logout and log again
newgrp docker
```

## 2. Run Pyroscope, Grafana and Prometheus

The `observability` folder contains a `docker-compose.yaml` file that will run
Pyroscope, Prometheus, and Grafana with the necessary configurations to show the
profiles and metrics on Grafana. Prometheus is configured to scrape metrics from
IG on port 2224.

```bash
cd observability/docker
docker compose up -d
```

## 3. Build ig and profile_malloc gadget

- Build IG from `mauricio/profile-cuda` branch
- Build the `profile_malloc` gadget from the same branch

## 4. Run profile_malloc gadget

Run the profile_malloc gadget for profiling:

```bash
sudo ig run profile_malloc --verify-image=false --config=./ig/config.yaml \
--otel-profiles-exporter=my-profiles-exporter \
--collect-ustack=true --host
```

Run the profile_malloc gadget separately for metrics:

```bash
sudo ig run profile_malloc --verify-image=false \
--otel-metrics-listen=true --otel-metrics-name=DS1:foo,DS2:bar
```

This will:
- Export profile data to Pyroscope via OTLP
- Expose metrics on port 2224 for Prometheus to scrape

## 5. Run a GPU workload

One easy way is to run an ollama model following
https://docs.ollama.com/quickstart:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama run gemma3
```

## 6. Check Pyroscope / Grafana

Open your browser to access:
- **Profiles**: `http://<VM_IP>:3000/a/grafana-pyroscope-app/explore` to view profiling data
- **Metrics**: `http://<VM_IP>:3000/explore` to view metrics from Prometheus
- **Prometheus**: `http://<VM_IP>:9090` to access Prometheus UI directly

NOTE: If you don't have direct access to the VM IP, you can create an SSH tunnel
with:

```bash
ssh -L 3000:localhost:3000 -L 9090:localhost:9090 <user>@<VM_IP>
```
