import base64
import logging

import uvicorn
from fastapi import Depends, FastAPI
from starlette.middleware.gzip import GZipMiddleware
from fastapi.responses import Response

from flight_reader.api.auth import get_auth_dependency
from flight_reader.api.routers import health
from flight_reader.api.routers import map as map_router
from flight_reader.api.routers import flights as flights_router
from flight_reader.api.routers import uploads as uploads_router
from flight_reader.api.routers import analytics
from flight_reader.db import init_db, SessionLocal
from flight_reader.services.import_shr import reset_inflight_uploads
from flight_reader.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

app = FastAPI(title="Flight reader")
auth_dependency = get_auth_dependency()
protected_kwargs: dict[str, object] = {}
if auth_dependency is not None:
    protected_kwargs["dependencies"] = [Depends(auth_dependency)]

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.include_router(health.router, prefix=settings.api_prefix, tags=["health"])
app.include_router(map_router.router, prefix=settings.api_prefix, tags=["map"], **protected_kwargs)
app.include_router(flights_router.router, prefix=settings.api_prefix, tags=["flights"], **protected_kwargs)
app.include_router(uploads_router.router, prefix=settings.api_prefix, tags=["uploads"], **protected_kwargs)
app.include_router(analytics.router, prefix=settings.api_prefix, tags=["analytics"], **protected_kwargs)


FAVICON_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAAWgmWQ0AAAAASUVORK5CYII="
)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    # Return a 1×1 transparent PNG to stop browsers from requesting a missing favicon
    return Response(content=FAVICON_BYTES, media_type="image/png")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    with SessionLocal() as session:
        count = reset_inflight_uploads(session)
        if count:
            logger.warning("Reset %s stalled SHR uploads to ERROR", count)


def run() -> None:
    uvicorn.run(
        "flight_reader.api.__main__:app",
        host=settings.api_host,
        port=settings.api_port,
        # чтобы отключить автоматическую перезагрузку, добавьте reload=False
    )


if __name__ == "__main__":
    run()
