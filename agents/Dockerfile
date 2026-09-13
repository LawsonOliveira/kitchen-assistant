# One image for all five agents (PLAN.md D18); agents differ only by the config bind-mounted at /seed.
# Official Hermes image pinned by tag and digest (PLAN.md D1, agents/NOTES.md).
FROM nousresearch/hermes-agent:v2026.9.11@sha256:9469b3e78b9545b6d576eb8887a95352e9a0ea83730eaf31431cf862ca1010e1

RUN uv pip install --python /opt/hermes/.venv/bin/python "pytest==8.4.2" "jsonschema==4.26.0"

COPY plugins /opt/sabor/plugins
COPY contracts /opt/sabor/contracts
COPY agents/entrypoint.sh /opt/sabor/entrypoint.sh
RUN chmod 755 /opt/sabor/entrypoint.sh && mkdir -p /workspace && chown hermes:hermes /workspace

# main-wrapper.sh execs an executable first argument directly, as user hermes.
CMD ["/opt/sabor/entrypoint.sh", "gateway", "run"]
