# Frontend image for fx-historical-market-analysis-service.
#
# Multi-stage build: the Vite production bundle is built in a builder stage and
# served by a minimal static file server in the runtime stage. The container
# runs as a non-root user.

FROM node:20-alpine AS builder

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY frontend ./
RUN npm run build

FROM nginx:1.27-alpine AS runtime

# Run the nginx worker processes as a non-root user.
RUN apk add --no-cache wget \
    && addgroup -g 1001 app \
    && adduser -u 1001 -G app -D app

COPY --from=builder /build/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://127.0.0.1:8080/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
