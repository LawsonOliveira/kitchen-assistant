# Cockpit: standard library only (PLAN.md D34) — no dependency install step.
FROM python:3.12-slim

WORKDIR /app
COPY server.py index.html ./
ENV PYTHONUNBUFFERED=1
USER nobody

EXPOSE 8080
CMD ["python", "server.py"]
