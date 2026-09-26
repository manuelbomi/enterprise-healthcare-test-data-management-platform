# syntax=docker/dockerfile:1
#
# Multi-stage build for the control-plane service.
#
# Phase 12: this is the first real Dockerfile in the repository --
# `ARCHITECTURE.md`'s Phase 11 note documented container health
# (HEALTHCHECK) as "design intent only" because no Dockerfile existed
# yet to attach one to (see docs/problems/problems_phase_11.md P11-2). This file
# resolves that gap for the control plane.
#
# Build context MUST be the repository root (not this directory),
# because the image needs both `libs/contracts` (a workspace-local
# dependency, per scripts/bootstrap.sh's own explanation of why it is
# installed as a bare package name rather than a relative `file:` URL)
# and `services/control-plane` itself:
#
#   docker build -f services/control-plane/Dockerfile -t tdm-control-plane:local .
#
# Stage 1 builds real wheels for the contracts library and the control
# plane (plus every third-party dependency) so the runtime stage never
# needs a compiler toolchain or network access.
FROM python:3.11-slim AS builder

WORKDIR /build
RUN pip install --no-cache-dir --upgrade pip

COPY libs/contracts ./libs/contracts
COPY services/control-plane ./services/control-plane

RUN pip wheel --no-cache-dir --wheel-dir /wheels ./libs/contracts \
    && pip wheel --no-cache-dir --wheel-dir /wheels --find-links /wheels ./services/control-plane

# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="tdm-control-plane" \
      org.opencontainers.image.description="Control plane (FastAPI): orchestration, policy, and the public REST API for the enterprise healthcare test data management platform." \
      org.opencontainers.image.source="https://github.com/manuelbomi/enterprise-healthcare-test-data-management-platform"

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin tdm
WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels tdm-control-plane \
    && rm -rf /wheels /root/.cache

# Non-secret, deployment-shape defaults only -- real secrets (database
# credentials, etc.) are supplied at deploy time via environment
# variables/orchestrator secrets, never baked into the image. See
# SECURITY.md and config.py's own docstring.
ENV PYTHONUNBUFFERED=1 \
    TDM_CONTROL_PLANE_LOG_LEVEL=INFO

USER tdm
EXPOSE 8000

# Container-level health signal, wired to the real Phase 0 liveness
# endpoint (not /ready -- a container orchestrator's own readiness
# probe is the correct place to point at /api/v1/ready; HEALTHCHECK
# here answers "is the process itself alive", matching health.py's own
# liveness-vs-readiness distinction).
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).status == 200 else 1)" || exit 1

CMD ["uvicorn", "control_plane.main:app", "--host", "0.0.0.0", "--port", "8000"]
