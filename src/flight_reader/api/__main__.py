import uvicorn
from fastapi import FastAPI

from flight_reader.api.routers import health
from flight_reader.api.routers import map as map_router
from flight_reader.db import init_db
from flight_reader.settings import get_settings

settings = get_settings()

app = FastAPI(title="Flight reader")
app.include_router(health.router, prefix=settings.api_prefix, tags=["health"])
app.include_router(map_router.router, prefix=settings.api_prefix, tags=["map"])


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
