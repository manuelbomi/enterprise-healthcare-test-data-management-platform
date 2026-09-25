#!/usr/bin/env bash
# Install every Python workspace package in editable mode, in dependency
# order, plus dev extras. Run from anywhere; paths are resolved relative to
# this script, not the caller's cwd.
#
# Why a script instead of pyproject.toml `file:` URLs: pip's PEP 508 parser
# for relative `file:` dependency URLs breaks when any ancestor directory
# name contains a space (a real bug hit during Phase 1 of this repo, whose
# default clone path is "...\HealthCare Projects\..."). Each service's
# pyproject.toml lists `healthcare-tdm-contracts` as a bare dependency name
# (no URL) and relies on this script installing it first, so it's already
# present by the time pip resolves the service's own install.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# `cd` into each package dir and install "." (not an absolute path) — pip's
# editable-requirement parser mishandles `<absolute path with a space>[extra]`
# as a single argument, even though a relative "."/".[extra]" is fine.
echo "==> libs/contracts"
(cd "$ROOT/libs/contracts" && python -m pip install -e ".[dev]")

for service in control-plane data-plane governance-service; do
  echo "==> services/$service"
  (cd "$ROOT/services/$service" && python -m pip install -e ".[dev]")
done

echo "==> All Python workspace packages installed."
