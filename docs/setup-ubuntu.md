# Ubuntu Setup

This guide targets Ubuntu 22.04 LTS and newer. It installs the tools required to run Flight Reader locally: uv, Docker Engine, and the Docker compose plugin.

## 1. System packages

```bash
sudo apt update
sudo apt install -y curl git ca-certificates lsb-release gnupg jq
```

`jq` is optional but handy when inspecting GeoJSON datasets.

## 2. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# Add uv to the current shell PATH (the installer prints the exact path)
source "$HOME/.cargo/env" 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
uv --version
```

## 3. Install Docker Engine and compose plugin

```bash
# Add Docker’s official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

# Install engine + plugin
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Enable Docker for the current user:

```bash
sudo usermod -aG docker "$USER"
newgrp docker
```

Verify installations:

```bash
uv --version
docker --version
docker compose version
```

You are ready to follow the main [README](../README.md) for project-specific steps.
