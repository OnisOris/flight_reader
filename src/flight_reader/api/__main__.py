import uvicorn
from fastapi import FastAPI
from flight_reader.settings import Settings
from flight_reader.api.routers import health
from flight_reader.api.routers import map as map_router

settings = Settings()

app = FastAPI(title="Flight reader")
app.include_router(health.router, prefix=settings.api_prefix, tags=["health"])
app.include_router(map_router.router, prefix=settings.api_prefix, tags=["map"])


def run() -> None:
    uvicorn.run(
        "flight_reader.api.__main__:app",
        host=settings.api_host,
        port=settings.api_port,
        # reload=False
    )


if __name__ == "__main__":
    run()
