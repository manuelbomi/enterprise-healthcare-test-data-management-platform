# syntax=docker/dockerfile:1
#
# Multi-stage build for the governance service. Same pattern as
# services/control-plane/Dockerfile -- see that file's header comment
# for the full rationale. This service is still a structural scaffold
# as of Phase 12 (see ARCHITECTURE.md section 2.4 and
# governance_service/main.py's module docstring): it exposes only a
# liveness endpoint today. This Dockerfile exists so the container
# build/scan/deploy pipeline is proven for every service directory now,
# not only for the two services with more business logic.
#
# Build context MUST be the repository root:
#
#   docker build -f services/governance-service/Dockerfile -t tdm-governance-service:local .
FROM python:3.11-slim AS builder

WORKDIR /build
RUN pip install --no-cache-dir --upgrade pip

COPY libs/contracts ./libs/contracts
COPY services/governance-service ./services/governance-service

RUN pip wheel --no-cache-dir --wheel-dir /wheels ./libs/contracts \
    && pip wheel --no-cache-dir --wheel-dir /wheels --find-links /wheels ./services/governance-service

# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="tdm-governance-service" \
      org.opencontainers.image.description="Security/governance plane scaffold (FastAPI) for the enterprise healthcare test data management platform." \
      org.opencontainers.image.source="https://github.com/manuelbomi/enterprise-healthcare-test-data-management-platform"

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin tdm
WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels tdm-governance-service \
    && rm -rf /wheels /root/.cache

ENV PYTHONUNBUFFERED=1

USER tdm
EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=2).status == 200 else 1)" || exit 1

CMD ["uvicorn", "governance_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
