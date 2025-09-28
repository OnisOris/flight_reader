import base64

import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response

from flight_reader.api.routers import health
from flight_reader.api.routers import map as map_router
from flight_reader.api.routers import flights as flights_router
from flight_reader.api.routers import uploads as uploads_router
from flight_reader.db import init_db
from flight_reader.settings import get_settings

settings = get_settings()

app = FastAPI(title="Flight reader")
app.include_router(health.router, prefix=settings.api_prefix, tags=["health"])
app.include_router(map_router.router, prefix=settings.api_prefix, tags=["map"])
app.include_router(flights_router.router, prefix=settings.api_prefix, tags=["flights"])
app.include_router(uploads_router.router, prefix=settings.api_prefix, tags=["uploads"])


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


def run() -> None:
    uvicorn.run(
        "flight_reader.api.__main__:app",
        host=settings.api_host,
        port=settings.api_port,
        # чтобы отключить автоматическую перезагрузку, добавьте reload=False
    )


if __name__ == "__main__":
    run()
