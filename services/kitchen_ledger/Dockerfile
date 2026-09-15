FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY kitchen_ledger ./kitchen_ledger
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["python", "-m", "kitchen_ledger.server"]
