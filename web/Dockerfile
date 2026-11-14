# The web app of Sudoo.sh: built with Node, served by Caddy (a single small binary).
# Released as ghcr.io/sudoo-sh/sudoo-web for linux/amd64 and linux/arm64. The build stage runs on the builder's own
# platform: its output (HTML, CSS, JavaScript) is the same for every architecture.
FROM --platform=$BUILDPLATFORM node:26-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM caddy:2-alpine
LABEL org.opencontainers.image.title="Sudoo.sh web" \
      org.opencontainers.image.source="https://github.com/Sudoo-sh/sudoo.sh" \
      org.opencontainers.image.authors="Yousef M. Y. Al Sabbah"
COPY Caddyfile /etc/caddy/Caddyfile
COPY --chmod=755 entrypoint.sh /entrypoint.sh
COPY --from=build /app/dist /srv
ENTRYPOINT ["/entrypoint.sh"]
