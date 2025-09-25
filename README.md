# flight_reader

Установите [uv](https://docs.astral.sh/uv/getting-started/installation/) 

Склонируйте репозиторий, далее создайте и активируйте вирутальное окружение

```
uv venv --python 3.13
source .venv/bin/activate
```

Установите проект (для разработчиков)

```
uv pip install -e .
```

Запуск сервера

```
frun
```

Документация по api:

http://127.0.0.1:8001/docs


## Настройки окружения

1. Скопируйте `.env.example` в `.env` и при необходимости измените значения.
2. Если используете Docker, дополнительно скопируйте `deployment/.env.example` в `deployment/.env`.


## Docker Compose

В каталоге `deployment` лежит конфигурация для запуска PostgreSQL:

1. Поднимите базу командой `docker compose -f deployment/docker-compose.yaml up -d`.
2. Проверьте состояние контейнера: `docker compose -f deployment/docker-compose.yaml ps`.
3. Скрипт `deployment/db-init/001_map_regions.sql` автоматически создаст таблицу `map_regions` и заполнит демонстрационные данные. При необходимости запустите его вручную через `psql`.
