FROM ghcr.io/astral-sh/uv:0.11.25 AS uv_binary
FROM python:3.12.13-slim
COPY --from=uv_binary /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable && useradd --create-home --uid 10001 eu && mkdir /data && chown eu:eu /data
ENV PATH="/app/.venv/bin:$PATH" EUPOLICYEO_ARTIFACTS=/data
USER eu
CMD ["eupolicyeo", "serve", "--host", "0.0.0.0"]
