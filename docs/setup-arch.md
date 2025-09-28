# Arch Linux Setup

This guide installs uv, Docker, and the compose plugin on Arch Linux (including derivatives like Manjaro). It assumes you have sudo access.

## 1. Sync repositories and install base tools

```bash
sudo pacman -Syu --needed git jq
```

`jq` is optional but useful for inspecting GeoJSON files.

## 2. Install uv

`uv` is available in the official repositories.

```bash
sudo pacman -S --needed uv
uv --version
```

## 3. Install Docker Engine and compose plugin

```bash
sudo pacman -S --needed docker docker-compose-plugin
```

Enable the Docker daemon and allow your user to run Docker commands without sudo:

```bash
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
newgrp docker
```

Verify:

```bash
docker --version
docker compose version
```

uv and Docker are now ready. Continue with the [README](../README.md) for project-specific setup (creating the virtual environment, starting the Postgres container, importing regions, etc.).
