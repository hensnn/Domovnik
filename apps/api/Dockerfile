# Produkční image API (kontext sestavení: apps/api)
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --locked --no-dev

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 domovnik && mkdir -p /data/files && chown -R domovnik /data
WORKDIR /app
COPY --from=build --chown=domovnik /app /app
COPY --chmod=755 entrypoint.sh /entrypoint.sh
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 DOMOVNIK_ENV=production FILES_DIR=/data/files
USER domovnik
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "domovnik.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
