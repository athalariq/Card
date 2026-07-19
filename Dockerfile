FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system larpcard \
    && adduser --system --ingroup larpcard larpcard

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations

RUN pip install --no-cache-dir .

RUN mkdir -p /app/assets /app/logs \
    && chown -R larpcard:larpcard /app

USER larpcard

CMD ["larpcard"]

