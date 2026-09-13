# One image for all five agents (PLAN.md D18); agents differ only by the config bind-mounted at /seed.
# Official Hermes image pinned by tag and digest (PLAN.md D1, agents/NOTES.md).
FROM nousresearch/hermes-agent:v2026.9.11@sha256:9469b3e78b9545b6d576eb8887a95352e9a0ea83730eaf31431cf862ca1010e1

# langfuse 4.15.1: Python SDK v4, fully supported by self-hosted Langfuse v4 (4.15.2 is still inside the image's 14-day uv
# exclude-newer quarantine in /opt/hermes/pyproject.toml); its OpenTelemetry, httpx and pydantic
# requirements are already bundled in the image (plugins/sabor_observability/NOTES.md).
RUN uv pip install --python /opt/hermes/.venv/bin/python "pytest==8.4.2" "jsonschema==4.26.0" "langfuse==4.15.1"

COPY plugins /opt/sabor/plugins
COPY contracts /opt/sabor/contracts
COPY evals/web_fixtures /opt/sabor/evals/web_fixtures
COPY agents/entrypoint.sh /opt/sabor/entrypoint.sh
RUN chmod 755 /opt/sabor/entrypoint.sh && mkdir -p /workspace /opt/data/cache/documents && chown hermes:hermes /workspace /opt/data/cache /opt/data/cache/documents

# main-wrapper.sh execs an executable first argument directly, as user hermes.
CMD ["/opt/sabor/entrypoint.sh", "gateway", "run"]
