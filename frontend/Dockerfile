# ---- Stage 1: build the Angular bundle --------------------------------------
FROM node:24-alpine AS builder

WORKDIR /app

COPY VERSION /VERSION
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ .
RUN npm run build -- --configuration=production

# ---- Stage 2: serve static assets with nginx --------------------------------
FROM nginxinc/nginx-unprivileged:1.28-alpine

COPY --from=builder /app/dist/inspectre-frontend/browser /usr/share/nginx/html
COPY frontend/nginx.spa.conf.template /etc/nginx/templates/default.conf.template
COPY frontend/proxy.conf /etc/nginx/proxy.conf

# Defaults match deploy/docker-compose.yml's `api` service — no compose
# changes needed. Override both when `spa` is the only publicly reachable
# container (e.g. Kubernetes) and `api` lives at a different address.
# See docs/deployment-and-config.md.
ENV API_UPSTREAM=http://api:8000
ENV RESOLVER_ADDRESS=127.0.0.11

EXPOSE 8080
