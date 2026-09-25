# Install every Python workspace package in editable mode, in dependency
# order, plus dev extras. Run from anywhere; paths are resolved relative to
# this script, not the caller's working directory.
#
# Why a script instead of pyproject.toml `file:` URLs: pip's PEP 508 parser
# for relative `file:` dependency URLs breaks when any ancestor directory
# name contains a space (a real bug hit during Phase 1 of this repo, whose
# default clone path is "...\HealthCare Projects\..."). Each service's
# pyproject.toml lists `healthcare-tdm-contracts` as a bare dependency name
# (no URL) and relies on this script installing it first, so it's already
# present by the time pip resolves the service's own install.
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

# Upgrade setuptools in the target environment itself (not just the
# `[build-system] requires` version pip uses in its own isolated build
# environment, which does not affect what ends up importable/installed
# afterward). A real, current CVE (PYSEC-2026-3447, fixed in 83.0.0) was
# found by scripts/security/dependency_scan.py's first real CI run
# against the setuptools version actions/setup-python's Python 3.11
# ships with -- see problems_phase_12.md.
python -m pip install --upgrade "setuptools>=83.0.0"

# Push into each package dir and install "." (not an absolute path) — pip's
# editable-requirement parser mishandles `<absolute path with a space>[extra]`
# as a single argument, even though a relative "."/".[extra]" is fine.
Write-Host "==> libs/contracts"
Push-Location "$Root\libs\contracts"
python -m pip install -e ".[dev]"
Pop-Location

foreach ($service in @("control-plane", "data-plane", "governance-service")) {
    Write-Host "==> services/$service"
    Push-Location "$Root\services\$service"
    python -m pip install -e ".[dev]"
    Pop-Location
}

Write-Host "==> All Python workspace packages installed."
