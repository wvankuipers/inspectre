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
COPY frontend/nginx.spa.conf /etc/nginx/conf.d/default.conf
COPY frontend/proxy.conf /etc/nginx/proxy.conf

EXPOSE 8080
