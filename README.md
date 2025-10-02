# Flight Reader

Flight Reader is a FastAPI application for parsing SHR/DEP/ARR XLSX workbooks and loading drone flights into PostgreSQL/PostGIS. The project ships with an automated geospatial import pipeline and CLI helpers built around [uv](https://docs.astral.sh/uv/).

## Prerequisites

- Python 3.11
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Docker Engine with the compose plugin (`docker compose`)
- Git

OS-specific setup notes (installing Docker, compose plugin, uv, etc.) are documented here:

- [Ubuntu setup](docs/setup-ubuntu.md)
- [Arch Linux setup](docs/setup-arch.md)

## Project Layout

```
.
├── deployment                # Docker compose, DB init SQL, helper scripts
├── dataset                   # Example XLSX datasets
├── src/flight_reader         # Application package
├── src/parser                # XLSX/SHR parsing utilities
└── README.md
```

## Local Development

1. Clone the repository and create a virtual environment (uv manages the Python version for you):

   ```bash
   uv venv --python 3.11
   source .venv/bin/activate
   ```

2. Install the project in editable mode:

   ```bash
   uv pip install -e .
   ```

3. Run the API:

 ```bash
  uv run frun
  ```

  The service exposes interactive docs at <http://127.0.0.1:8001/docs>.

### Keycloak integration

Authentication is disabled by default so the project can start without Keycloak during
experimentation (requests run as a local admin user). To secure the API:

1. Create an OIDC client in your Keycloak realm (confidential or public is fine for JWT-only
   validation) and configure it to include the following in issued access tokens:
   - Realm or client-level roles `partner` and `regulator` (names can be customised via
     `KEYCLOAK_PARTNER_ROLE` / `KEYCLOAK_REGULATOR_ROLE`).
   - A multi-valued attribute named `partner_operator_codes` for partner accounts. The claim must
     resolve to ICAO/operator codes that exist in the `operators` table; regulators can omit it.
2. Export the realm metadata and copy the relevant URLs into the API environment (see
   `deployment/.env` for a reference). The application reads the following variables:

   ```env
   AUTH_ENABLED=true
   KEYCLOAK_SERVER_URL=https://sso.example.com
   KEYCLOAK_REALM=flight-reader
   KEYCLOAK_CLIENT_ID=flight-reader-api
   KEYCLOAK_AUDIENCE=flight-reader-api  # defaults to client ID when omitted
   KEYCLOAK_PARTNER_ROLE=partner
   KEYCLOAK_REGULATOR_ROLE=regulator
   KEYCLOAK_PARTNER_OPERATOR_CLAIM=partner_operator_codes
   ```

   If your environment uses non-standard issuer/JWKS URLs, set `KEYCLOAK_ISSUER` and/or
   `KEYCLOAK_JWKS_URL` explicitly.
3. Partners will only see flights, maps, analytics, and upload logs for the operator codes present
   in their token. Regulators (and admins) have unrestricted access. Requests with missing or
   expired tokens are rejected with `401`.

### Импорт регионов в Kubernetes

Рабочий способ повторить `cp … && docker compose run --rm regions-import` в kind‑кластере:

1. Скопируйте GeoJSON внутрь всех kind-нод (делать при каждом пересоздании кластера):

   ```bash
   export PATH=$HOME/bin:$PATH  # если kind/kubectl установлены туда же
   deployment/scripts/kind-sync-regions.sh deployment/data/regions.geojson
   ```

2. Запустите Job, который подтянет файл по hostPath и выполнит SQL-пайплайн:

   ```bash
   export KUBECONFIG=/tmp/kubeconfig-flight-reader
   kubectl -n flight-reader delete job flight-reader-regions-import --ignore-not-found
   kubectl apply -f deployment/k8s/regions-import-job.yaml
   kubectl -n flight-reader wait --for=condition=complete job/flight-reader-regions-import --timeout=10m
   kubectl -n flight-reader logs job/flight-reader-regions-import | tail
   ```

GeoJSON остаётся на нодах (`/opt/flight-reader/regions/regions.geojson`) до тех пор, пока вы не удалите kind‑кластер.

## Database with Docker Compose

A PostGIS-enabled PostgreSQL instance and helper utilities live under `deployment/`.

1. Start the database:

   ```bash
   docker compose -f deployment/docker-compose.yaml up -d postgres
   docker compose -f deployment/docker-compose.yaml ps
   ```

2. (Optional) connect with `psql` to verify credentials:

   ```bash
   docker compose -f deployment/docker-compose.yaml exec postgres \
     psql -U flight_reader -d flight_reader -c "SELECT NOW();"
   ```

3. Import Russian regions (admin_level=4) so that flights can be matched to subjects of the federation. There are two supported paths:

   **A. Automatic download (requires osm-boundaries API key)**

   ```bash
   export OSMB_API_KEY=YOUR_OSMB_API_KEY
   docker compose -f deployment/docker-compose.yaml run --rm regions-import
   ```

  **B. Manual file (bundled fallback)**

  The repository already ships with an osm-boundaries GeoJSON at `dataset/OSMB-cffca091e9d8f66243c5befca50e7b53a42e1770.geojson` (admin_level=4 for all Russian regions).

  ```bash
  cp dataset/OSMB-cffca091e9d8f66243c5befca50e7b53a42e1770.geojson deployment/data/regions.geojson
  docker compose -f deployment/docker-compose.yaml run --rm regions-import
  ```

  You can also drop any other GeoJSON/GeoPackage/Shapefile into `deployment/data/` and reuse the same command.

   The import script automatically:
   - downloads or reads the dataset;
   - unpacks gzipped GeoJSON if needed;
   - normalises and unions geometries grouped by subject;
   - upserts data into the `regions` table and builds a GiST index.

4. If you need to refresh the regions later, truncate the table and re-run the importer:

   ```bash
   docker compose -f deployment/docker-compose.yaml exec postgres \
     psql -U flight_reader -d flight_reader -c "TRUNCATE regions RESTART IDENTITY CASCADE;"
   docker compose -f deployment/docker-compose.yaml run --rm regions-import
   ```

5. Populate regions for already imported flights (after regions exist):

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
