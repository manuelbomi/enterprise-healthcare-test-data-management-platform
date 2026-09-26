# syntax=docker/dockerfile:1
#
# Multi-stage build for the TDM console. Build stage compiles the real
# Vite/React app (the exact `npm ci && npm run build` CI already runs);
# runtime stage serves the static output with nginx. See ARCHITECTURE.md
# section 2.5 -- this console talks only to the control-plane REST API,
# never directly to storage/the metadata database/Spark.
#
# Build context MUST be `frontend/`:
#
#   docker build -t tdm-console:local frontend
FROM node:20-alpine AS builder

WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
FROM nginx:1.29-alpine AS runtime

LABEL org.opencontainers.image.title="tdm-console" \
      org.opencontainers.image.description="React/TypeScript console for the enterprise healthcare test data management platform." \
      org.opencontainers.image.source="https://github.com/manuelbomi/enterprise-healthcare-test-data-management-platform"

# Defense in depth, on top of pinning a current base tag above: apply any
# Alpine security patches published after this base image was built.
# Real, found-and-fixed motivation, not a defensive boilerplate line --
# .github/workflows/container-build.yml's Trivy CRITICAL gate genuinely
# failed on this image's first real CI run (a real CVE in the base
# image's openssl/libcrypto3 package, fixed upstream but not yet in the
# pinned tag's layer) -- see docs/problems/problems_phase_12.md.
RUN apk update && apk upgrade --no-cache

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
