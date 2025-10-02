# Arch Linux: Полная установка и запуск

Инструкция для Arch/Manjaro: установка uv, Docker(+compose‑plugin), kubectl/kind; запуск через Docker Compose или Kubernetes; импорт регионов; (опционально) Keycloak.

## 1) Базовые инструменты

```bash
sudo pacman -Syu --needed git jq
```

`jq` — опционально, полезно для GeoJSON.

### Установка uv

```bash
sudo pacman -S --needed uv
uv --version
```

### Установка Docker и compose‑plugin

```bash
sudo pacman -S --needed docker docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
newgrp docker

docker --version
docker compose version
```

## 2) Вариант A — запуск через Docker Compose

```bash
# 2.1. Postgres
docker compose -f deployment/docker-compose.yaml up -d postgres
docker compose -f deployment/docker-compose.yaml ps

# 2.2. Импорт регионов
cp dataset/OSMB-cffca091e9d8f66243c5befca50e7b53a42e1770.geojson deployment/data/regions.geojson
docker compose -f deployment/docker-compose.yaml run --rm regions-import
# (или export OSMB_API_KEY=... и запустить ту же команду для скачивания)

# 2.3. API
docker compose -f deployment/docker-compose.yaml up -d --build api

# 2.4. Проверка
curl http://127.0.0.1:8001/api/ready
```

### Keycloak (опционально, для Compose)

Пропишите переменные в `deployment/.env` и перезапустите API:

```env
AUTH_ENABLED=true
KEYCLOAK_SERVER_URL=https://sso.example.com
KEYCLOAK_REALM=flight-reader
KEYCLOAK_CLIENT_ID=flight-reader-api
```

## 3) Вариант B — запуск в Kubernetes (kind)

### Установка kubectl и kind

```bash
sudo pacman -S --needed kubectl kind
kubectl version --client
kind version
```

### Создание кластера и деплой

```bash
kind create cluster --name flight-reader
export KUBECONFIG="$HOME/.kube/kind-flight-reader.yaml"
kind get kubeconfig --name flight-reader > "$KUBECONFIG"

kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
kubectl apply -f deployment/k8s/flight-reader.yaml

docker build -t flight-reader-api:latest .
kind load docker-image flight-reader-api:latest --name flight-reader
kubectl -n flight-reader set image deployment/flight-reader-api api=flight-reader-api:latest
kubectl -n flight-reader get pods
```

### Импорт регионов в k8s

```bash
deployment/scripts/kind-sync-regions.sh deployment/data/regions.geojson
kubectl -n flight-reader delete job flight-reader-regions-import --ignore-not-found
kubectl apply -f deployment/k8s/regions-import-job.yaml
kubectl -n flight-reader wait --for=condition=complete job/flight-reader-regions-import --timeout=10m
kubectl -n flight-reader logs job/flight-reader-regions-import | tail
```

### Keycloak в k8s (опционально)

```bash
kubectl -n flight-reader set env deploy/flight-reader-api \
  AUTH_ENABLED=true KEYCLOAK_SERVER_URL=https://sso.example.com \
  KEYCLOAK_REALM=flight-reader KEYCLOAK_CLIENT_ID=flight-reader-api
kubectl -n flight-reader rollout restart deploy/flight-reader-api
```

## Проверка API

```bash
kubectl -n flight-reader port-forward svc/flight-reader-api 8001:8001
curl http://127.0.0.1:8001/api/ready
```

## Примечания
- Если нет доступа к osm‑boundaries, используйте локальный файл + `kind-sync-regions.sh`.
- Для локальной отладки аутентификация по умолчанию выключена (`AUTH_ENABLED=false`).
