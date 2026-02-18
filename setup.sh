#!/usr/bin/env bash

# Docker
## Add Docker's official GPG key:
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

## Add the repository to Apt sources:
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable docker
sudo systemctl start docker

sudo groupadd docker
sudo usermod -aG docker $USER
newgrp docker

# NVIDIA Drivers and CUDA
## Get Ubuntu version (20.04 → 2004, etc.)
UBUNTU_VERSION=$(source /etc/os-release && echo "${VERSION_ID//./}")

CUDA_REPO_BASE="https://developer.download.nvidia.com/compute/cuda/repos/ubuntu${UBUNTU_VERSION}/x86_64"
CUDA_KEYRING="cuda-keyring_1.0-1_all.deb"

wget "${CUDA_REPO_BASE}/${CUDA_KEYRING}"
sudo dpkg -i "${CUDA_KEYRING}"

sudo apt update
sudo apt-get install -y datacenter-gpu-manager cuda-drivers

# needed to run containers using the gpu
# https://stackoverflow.com/a/77269071
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker


# IG
## Golang
wget https://go.dev/dl/go1.25.6.linux-amd64.tar.gz
sudo tar -C /usr/local -xzf go1.25.6.linux-amd64.tar.gz
echo "export PATH=$PATH:/usr/local/go/bin" >> .profile
source .profile

## IG 

git clone https://github.com/inspektor-gadget/inspektor-gadget
cd inspektor-gadget
git checkout mauricio/profile-cuda
make install/ig
IG_SOURCE_PATH=`pwd` sudo -E ig image build ./gadgets/profile_cuda -t profile_cuda
cd ..


# Observability stack
git clone https://github.com/mauriciovasquezbernal/ig-gpu-instructions
docker compose -f ig-gpu-instructions/pyroscope/docker/docker-compose.yml up -d

# ollama
## Scary sh pipe
curl -fsSL https://ollama.com/install.sh | sh

# DONE instruct the user to run certain commands one after another
echo -e "\n\nFirst run\nsudo ig run profile_cuda --verify-image=false --config=./ig-gpu-instructions/ig/config.yaml --otel-profiles-exporter=my-profiles-exporter --collect-ustack=true --host"
echo -e "\nAnd then start ollama with\nollama run gemma3"
