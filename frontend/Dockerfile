# ---- Stage 1: build the Angular bundle --------------------------------------
FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build -- --configuration=production

# ---- Stage 2: serve static assets with nginx --------------------------------
FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY --from=builder /app/dist/inspectre-frontend/browser /usr/share/nginx/html
COPY nginx.spa.conf /etc/nginx/conf.d/default.conf
COPY proxy.conf /etc/nginx/proxy.conf

EXPOSE 8080
