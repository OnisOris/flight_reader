FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
COPY README.md ./
COPY src ./src

RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir .

EXPOSE 8001

CMD ["uvicorn", "flight_reader.api.__main__:app", "--host", "0.0.0.0", "--port", "8001"]
