# The panel image: Python with the dependencies locked in uv.lock, plus the Docker CLI and Compose plugin (to manage
# instances on the host's Docker), git and SSH (to fetch code with deploy keys), and the documentation shown in the
# panel (README.md and docs/). Released as ghcr.io/sudoo-sh/sudoo-panel for linux/amd64 and linux/arm64.
FROM python:3.15-alpine

LABEL org.opencontainers.image.title="Sudoo" \
      org.opencontainers.image.authors="Yousef M. Y. Al Sabbah" \
      org.opencontainers.image.source="https://github.com/Sudoo-sh/sudoo.sh" \
      org.opencontainers.image.licenses="PolyForm-Noncommercial-1.0.0"

COPY --from=docker:29-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker:29-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

RUN apk add --no-cache git openssh-client openssh-keygen tzdata \
 && git config --system --add safe.directory '*'

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
# dependencies first: this layer is rebuilt only when uv.lock changes
COPY pyproject.toml uv.lock README.md LICENSE.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
# the documentation of this very version, shown under Help (DOCS_DIR, /app/documentation)
COPY README.md ./documentation/README.md
COPY docs ./documentation/docs

# `sudoo.sh serve` starts gunicorn with one process (jobs, monitor and gateway share its memory), listening
# where the exposure plugin needs it: 127.0.0.1 behind a tunnel, every interface when visitors connect directly.
CMD ["sudoo.sh", "serve"]
