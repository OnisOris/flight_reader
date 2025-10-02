# Flight Reader

Flight Reader — это приложение на FastAPI для парсинга XLSX SHR/DEP/ARR и загрузки полётов БПЛА в PostgreSQL/PostGIS. В составе проекта есть автоматизированный конвейер геоимпорта и CLI‑утилиты на базе [uv](https://docs.astral.sh/uv/).

## Предварительные требования

- Python 3.11
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Docker Engine с плагином compose (`docker compose`)
- Git

Пошаговые инструкции для ОС (установка Docker, compose‑плагина, uv и т.д.):

- [Настройка Ubuntu](docs/setup-ubuntu.md)
- [Настройка Arch Linux](docs/setup-arch.md)

## Структура проекта

```
.
├── deployment                # Docker compose, инициализация БД, скрипты
├── dataset                   # Примерные XLSX-наборы
├── src/flight_reader         # Пакет приложения
├── src/parser                # Утилиты парсинга XLSX/SHR
└── README.md
```

## Локальная разработка

1. Клонируйте репозиторий и создайте виртуальную среду (uv сам подтянет нужный Python):

   ```bash
   uv venv --python 3.11
   source .venv/bin/activate
   ```

2. Установите проект в editable‑режиме:

   ```bash
   uv pip install -e .
   ```

3. Запустите API:

   ```bash
   uv run frun
   ```

   Документация доступна на <http://127.0.0.1:8001/docs>.

### Интеграция с Keycloak

По умолчанию аутентификация выключена, чтобы можно было стартовать без Keycloak (запросы исполняются от локального администратора). Чтобы включить защиту API:

1. Создайте OIDC‑клиент в вашем realm’е Keycloak (подойдёт `public` или `confidential` для проверки JWT) и настройте выдачу в токен следующего:
   - Роли `partner` и `regulator` (названия можно поменять через `KEYCLOAK_PARTNER_ROLE` / `KEYCLOAK_REGULATOR_ROLE`).
   - Для партнёров — мультизначный claim `partner_operator_codes` (коды операторов, которые есть в таблице `operators`). Регуляторам не требуется.
2. Пропишите параметры Keycloak через переменные окружения (см. пример в `deployment/.env`). Приложение читает:

   ```env
   AUTH_ENABLED=true
   KEYCLOAK_SERVER_URL=https://sso.example.com
   KEYCLOAK_REALM=flight-reader
   KEYCLOAK_CLIENT_ID=flight-reader-api
   KEYCLOAK_AUDIENCE=flight-reader-api  # по умолчанию равен CLIENT_ID
   KEYCLOAK_PARTNER_ROLE=partner
   KEYCLOAK_REGULATOR_ROLE=regulator
   KEYCLOAK_PARTNER_OPERATOR_CLAIM=partner_operator_codes
   ```

   Если используются нестандартные адреса, задайте явно `KEYCLOAK_ISSUER` и/или `KEYCLOAK_JWKS_URL`.
3. Партнёры видят только свои данные (фильтрация по `partner_operator_codes`), регуляторы/админы — всё. Без токена запросы получают `401`.

### Фронтенд (Next.js)

Интерфейс аналитики расположен в подмодуле `externals/flight-analytics`. После клонирования инициализируйте подмодули:

```bash
git submodule update --init --recursive
```

#### Локальный запуск

```bash
cd externals/flight-analytics
npm install
export API_PATH=http://127.0.0.1:8001
npm run dev
# http://localhost:3000
```

#### Сборка контейнера

```bash
docker build \
  -f externals/flight-analytics/Dockerfile \
  -t flight-reader-frontend:latest \
  externals/flight-analytics
```

Загрузка в kind и деплой:

```bash
kind load docker-image flight-reader-frontend:latest --name flight-reader
kubectl apply -f deployment/k8s/flight-reader.yaml
kubectl -n flight-reader port-forward svc/flight-reader-frontend 3000:3000
# http://127.0.0.1:3000
```

В манифесте Kubernetes переменная `API_PATH` указывает на кластерный сервис API — дополнительной настройки не требуется.

### Импорт регионов в Kubernetes

Повторить локальный сценарий `cp … && docker compose run --rm regions-import` в kind‑кластере можно так:

1. Скопируйте GeoJSON внутрь всех kind‑нод (после каждого пересоздания кластера):

   ```bash
   export PATH=$HOME/bin:$PATH  # если kind/kubectl установлены туда же
   deployment/scripts/kind-sync-regions.sh deployment/data/regions.geojson
   ```

2. Запустите Job, который прочитает файл через hostPath и выполнит SQL‑пайплайн:

   ```bash
   export KUBECONFIG=/tmp/kubeconfig-flight-reader
   kubectl -n flight-reader delete job flight-reader-regions-import --ignore-not-found
   kubectl apply -f deployment/k8s/regions-import-job.yaml
   kubectl -n flight-reader wait --for=condition=complete job/flight-reader-regions-import --timeout=10m
   kubectl -n flight-reader logs job/flight-reader-regions-import | tail
   ```

GeoJSON остаётся на нодах (`/opt/flight-reader/regions/regions.geojson`) до удаления kind‑кластера.

## База данных через Docker Compose

PostgreSQL с PostGIS и вспомогательные утилиты находятся в каталоге `deployment/`.

1. Запустить БД:

   ```bash
   docker compose -f deployment/docker-compose.yaml up -d postgres
   docker compose -f deployment/docker-compose.yaml ps
   ```

2. (Опционально) проверить доступ через `psql`:

   ```bash
   docker compose -f deployment/docker-compose.yaml exec postgres \
     psql -U flight_reader -d flight_reader -c "SELECT NOW();"
   ```

3. Импорт российских регионов (admin_level=4), чтобы сопоставлять полёты субъектам. Два пути:

   **A. Автоскачивание (нужен ключ osm‑boundaries)**

   ```bash
   export OSMB_API_KEY=YOUR_OSMB_API_KEY
   docker compose -f deployment/docker-compose.yaml run --rm regions-import
   ```

   **B. Локальный файл (в репозитории уже есть пример)**

   ```bash
   cp dataset/OSMB-cffca091e9d8f66243c5befca50e7b53a42e1770.geojson deployment/data/regions.geojson
   docker compose -f deployment/docker-compose.yaml run --rm regions-import
   ```

   Можно также положить любой GeoJSON/GeoPackage/Shapefile в `deployment/data/` и повторно запустить импорт.

   Скрипт импорта:
   - скачивает/читает набор;
   - распаковывает gz‑GeoJSON при необходимости;
   - нормализует и агрегирует геометрии по субъектам;
   - upsert’ит данные в таблицу `regions` и строит GiST‑индекс.

4. Обновить регионы позже: очистите таблицу и перезапустите импорт:

   ```bash
   docker compose -f deployment/docker-compose.yaml exec postgres \
     psql -U flight_reader -d flight_reader -c "TRUNCATE regions RESTART IDENTITY CASCADE;"
   docker compose -f deployment/docker-compose.yaml run --rm regions-import
   ```

5. Проставить регионы для уже загруженных полётов (когда таблица `regions` заполнена):

   ```sql
   UPDATE flights f SET region_from_id = r.id
     FROM regions r
    WHERE f.region_from_id IS NULL
      AND f.geom_takeoff IS NOT NULL
      AND ST_Contains(r.geom, f.geom_takeoff);

   UPDATE flights f SET region_to_id = r.id
     FROM regions r
   WHERE f.region_to_id IS NULL
     AND f.geom_landing IS NOT NULL
     AND ST_Contains(r.geom, f.geom_landing);
   ```

## Run the API with Docker

Spin up the FastAPI service together with PostgreSQL using the compose file:

```bash
docker compose -f deployment/docker-compose.yaml up -d api
```

Logs from the API container:

```bash
docker compose -f deployment/docker-compose.yaml logs -f api
```

The service listens on <http://127.0.0.1:${API_PORT:-8001}>. Adjust `API_PORT`, `POSTGRES_*`, or other environment variables via the usual compose overrides (env vars, `.env`, or `-e` flags).

Shut everything down when finished:

```bash
docker compose -f deployment/docker-compose.yaml down
```

## Kubernetes Deployment

Kubernetes manifests live under `deployment/k8s/` and provision the API, a
PostGIS database, and an optional job for importing regional boundaries.

1. Build and push the API image to a registry your cluster can access. Replace
   the example tag with your registry/project (e.g. GHCR, Docker Hub) and
   ensure the tag matches the image reference in `deployment/k8s/flight-reader.yaml`.

   ```bash
   docker build -t ghcr.io/<your-org>/flight-reader-api:latest .
   docker push ghcr.io/<your-org>/flight-reader-api:latest
   ```

2. Review `deployment/k8s/flight-reader.yaml` and adjust credentials, storage
   sizes, or the API image if necessary. Then create the namespace and deploy
   the base stack:

   ```bash
   kubectl apply -f deployment/k8s/flight-reader.yaml
   kubectl get pods -n flight-reader
   ```

   The manifest creates a `PersistentVolumeClaim` named `data` for PostgreSQL.
   Ensure your cluster has a default `StorageClass` or add one explicitly to
   the claim template.

3. Port-forward the API service (or expose it via an ingress/controller of your
   choice):

   ```bash
   kubectl port-forward -n flight-reader svc/flight-reader-api 8001:8001
   ```

   The FastAPI docs will then be available at <http://127.0.0.1:8001/docs>.

4. (Optional) import administrative regions via the supplied job. Provide an
   `OSMB_API_KEY` if you rely on osm-boundaries.com, or mount your own dataset
   into the job’s `/data` directory before execution.

   ```bash
   kubectl apply -f deployment/k8s/regions-import-job.yaml
   kubectl logs -n flight-reader job/flight-reader-regions-import -f
   ```

   Re-run the importer by deleting the existing job and re-applying the
   manifest:

   ```bash
   kubectl delete job -n flight-reader flight-reader-regions-import
   kubectl apply -f deployment/k8s/regions-import-job.yaml
   ```

## Upload Example

Upload an SHR XLSX workbook:

```bash
curl -X POST \
     -F "user_id=1" \
     -F "file=@dataset/2024.xlsx" \
     http://127.0.0.1:8001/api/uploads/shr
```

The response contains the upload identifier along with a helper link for polling status:

```json
{
  "upload_id": 42,
  "status": "QUEUED",
  "status_check": "/api/uploads/42"
}
```

Fetch the status (and possible error details) once the background import completes:

```bash
curl http://127.0.0.1:8001/api/uploads/42
```

Import progress and errors are tracked in the `upload_logs` table; any spatial deduplication is enforced via unique constraints on `(flight_id, takeoff_time, landing_time)`.

## API Highlights

- `GET /api/health/ping` – service health check
- `GET /api/map/regions` – list of regions (GeoJSON)
- `GET /api/flights/stats` – aggregated flight counts (total and per region)
- `GET /api/flights` – paginated flights with filtering parameters (`limit` defaults to 100, max 1000)
- `POST /api/uploads/shr` – asynchronous XLSX ingestion (returns polling link)
- `GET /api/uploads/{id}` – upload status and summary

## Contributing

1. Format and lint with your preferred tools (ruff/black recommended).
2. Ensure unit tests (if present) run via `uv run pytest`.
3. Submit PRs targeting the `main` branch.

## Support / Troubleshooting

- Ensure Docker Compose is available as `docker compose` (the Python `docker-compose` legacy binary is not required).
- If region import fails, verify that the dataset truly contains `admin_level=4` features. The helper script prints detailed logs and stops if the file is missing or an HTTP request fails.
- For more OS-specific prerequisites consult the linked setup guides.
