import uvicorn
from fastapi import FastAPI
from flight_reader.settings import Settings
from flight_reader.api.routers import health

settings = Settings()

app = FastAPI(title="Flight reader")
app.include_router(health.router, prefix=settings.api_prefix, tags=["health"])


def run() -> None:
    uvicorn.run(
        "flight_reader.api.__main__:app",
        host=settings.api_host,
        port=settings.api_port,
        # reload=False
    )


if __name__ == "__main__":
    run()
