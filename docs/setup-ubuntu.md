# Ubuntu: Полная установка и запуск

Инструкция для Ubuntu 22.04 LTS+ с двумя сценариями запуска: через Docker Compose (проще) и через Kubernetes/kind (ближе к продакшену). Включены шаги для импорта регионов и (опционально) интеграции Keycloak.

## 1) Базовые инструменты

```bash
sudo apt update
sudo apt install -y curl git ca-certificates lsb-release gnupg jq
```

`jq` — опционально, полезно для проверки GeoJSON.

### Установка uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# Добавьте uv в PATH (инсталлятор подскажет точный путь)
source "$HOME/.cargo/env" 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
uv --version
```

### Установка Docker Engine и compose-plugin

```bash
# Ключ Docker
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Репозиторий Docker
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Разрешить вашему пользователю запускать docker без sudo
sudo usermod -aG docker "$USER"
newgrp docker

docker --version
docker compose version
```

## 2) Вариант A — запуск через Docker Compose (рекомендуется для старта)

```bash
# 2.1. Запуск Postgres (с PostGIS)
docker compose -f deployment/docker-compose.yaml up -d postgres
docker compose -f deployment/docker-compose.yaml ps

# 2.2. Импорт регионов (два пути)
# A) Использовать локальный файл (в репозитории уже есть dataset/OSMB-....geojson)
cp dataset/OSMB-cffca091e9d8f66243c5befca50e7b53a42e1770.geojson deployment/data/regions.geojson
docker compose -f deployment/docker-compose.yaml run --rm regions-import

# B) Или скачать с osm-boundaries (нужен ключ)
# export OSMB_API_KEY=... ; можно переопределить REGIONS_SOURCE_URL
docker compose -f deployment/docker-compose.yaml run --rm regions-import

# 2.3. Сборка и запуск API
docker compose -f deployment/docker-compose.yaml up -d --build api

# 2.4. Проверки
curl http://127.0.0.1:8001/api/ready
curl http://127.0.0.1:8001/api/flights
```

Опционально: `docker compose -f deployment/docker-compose.yaml up -d pgadmin` и зайдите на http://127.0.0.1:5050.

### Включение Keycloak (опционально)

В файле `deployment/.env` задайте переменные и перезапустите API:

```env
AUTH_ENABLED=true
KEYCLOAK_SERVER_URL=https://sso.example.com
KEYCLOAK_REALM=flight-reader
KEYCLOAK_CLIENT_ID=flight-reader-api
# KEYCLOAK_AUDIENCE=flight-reader-api    # по умолчанию равен CLIENT_ID
# KEYCLOAK_PARTNER_ROLE=partner
# KEYCLOAK_REGULATOR_ROLE=regulator
# KEYCLOAK_PARTNER_OPERATOR_CLAIM=partner_operator_codes
```

```bash
docker compose -f deployment/docker-compose.yaml up -d api
```

## 3) Вариант B — запуск в Kubernetes (kind)

### Установка kubectl и kind

```bash
# kubectl (официальный репозиторий Kubernetes)
sudo apt-get install -y apt-transport-https ca-certificates curl
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.30/deb/Release.key | \
  sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] \
  https://pkgs.k8s.io/core:/stable:/v1.30/deb/ /" | \
  sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update
sudo apt-get install -y kubectl

# kind
curl -Lo kind https://kind.sigs.k8s.io/dl/v0.23.0/kind-linux-amd64
chmod +x kind
sudo mv kind /usr/local/bin/

kubectl version --client
kind version
```

### Создание кластера, деплой БД и API

```bash
kind create cluster --name flight-reader
export KUBECONFIG="$HOME/.kube/kind-flight-reader.yaml"
kind get kubeconfig --name flight-reader > "$KUBECONFIG"

# Разрешим скедулинг на control-plane (в kind часто одной ноды достаточно)
kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true

# Применяем манифесты
kubectl apply -f deployment/k8s/flight-reader.yaml

# Собираем локальный образ API и загружаем его в kind
docker build -t flight-reader-api:latest .
kind load docker-image flight-reader-api:latest --name flight-reader
kubectl -n flight-reader set image deployment/flight-reader-api api=flight-reader-api:latest

# Дожидаемся запуска
kubectl -n flight-reader get pods
```

### Импорт регионов в k8s (из локального файла)

```bash
# Скопируйте GeoJSON в ноды kind (делается при каждом пересоздании кластера)
deployment/scripts/kind-sync-regions.sh deployment/data/regions.geojson

# Запустите Job импорта
kubectl -n flight-reader delete job flight-reader-regions-import --ignore-not-found
kubectl apply -f deployment/k8s/regions-import-job.yaml
kubectl -n flight-reader wait --for=condition=complete job/flight-reader-regions-import --timeout=10m
kubectl -n flight-reader logs job/flight-reader-regions-import | tail

# Прокиньте порт API и проверьте
kubectl -n flight-reader port-forward svc/flight-reader-api 8001:8001
curl http://127.0.0.1:8001/api/ready
```

### Keycloak в k8s (опционально)

Самый простой способ — добавить env прямо в Deployment:

```bash
kubectl -n flight-reader set env deploy/flight-reader-api \
  AUTH_ENABLED=true \
  KEYCLOAK_SERVER_URL=https://sso.example.com \
  KEYCLOAK_REALM=flight-reader \
  KEYCLOAK_CLIENT_ID=flight-reader-api \
  KEYCLOAK_AUDIENCE=flight-reader-api
```

И перезапустить: `kubectl -n flight-reader rollout restart deploy/flight-reader-api`.

## Тестовые запросы API

```bash
curl http://127.0.0.1:8001/api/ready
curl http://127.0.0.1:8001/api/flights | jq . | head
curl "http://127.0.0.1:8001/api/flights/stats?direction=all" | jq .
```

## Траблшутинг
- `ImagePullBackOff` в k8s: убедитесь, что образ загружен в kind и выставлен в Deployment (`kind load docker-image …`, `kubectl set image …`).
- `Pending` из‑за PVC в kind: на дефолтном StorageClass `standard` (local-path) должно взлетать; проверьте `kubectl get sc`.
- Импорт регионов: если нет доступа к osm‑boundaries, используйте локальный файл и `kind-sync-regions.sh`.
