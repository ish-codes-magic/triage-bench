# The repo-intel MCP server as an image: read-only tools over a frozen issue history.
#   docker run -i --rm -v "$PWD/data:/data" ghcr.io/<owner>/repo-intel \
#       --profile /app/configs/repos/python__cpython.yaml
# The server speaks MCP over stdio, so run it with -i and without a TTY.
# See src/triagelab/mcp_server/README.md for the data it expects under /data.

FROM python:3.12-slim AS build
# The same uv that wrote uv.lock (keep in step with .github/actions/setup-env).
COPY --from=ghcr.io/astral-sh/uv:0.11.18 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
# Dependencies first: this layer is rebuilt only when the lock changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-default-groups --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-default-groups --no-editable

FROM python:3.12-slim
RUN useradd --create-home --uid 1000 intel
COPY --from=build /app/.venv /app/.venv
# Repository profiles (taxonomy, components) for the repositories this project covers.
COPY configs/repos /app/configs/repos
ENV PATH="/app/.venv/bin:$PATH" REPO_INTEL_DATA_DIR=/data
# The embedding model is downloaded here on the first dense search; mount a volume at
# /work/.cache to keep it, or pass --no-dense for BM25 only.
WORKDIR /work
RUN chown intel /work
USER intel
ENTRYPOINT ["repo-intel"]
