# swatplus-builder container baseline
#
# Layers:
#  1. Python 3.11 slim (reproducible, small)
#  2. System geo-libraries (GDAL-lite for pygeohydro/py3dep)
#  3. Package install (core + swatplus optional extras)
#  4. Non-root runtime user
#
# SWAT+ binary is NOT bundled — mount it at runtime:
#   docker run -v /path/to/swatplus_exe:/opt/swatplus/swatplus_exe \
#              -e SWATPLUS_EXE=/opt/swatplus/swatplus_exe \
#              swatplus-builder swat version
#
# Artifacts directory is mounted at /data/artifacts by convention:
#   docker run -v $(pwd)/artifacts:/data/artifacts swatplus-builder ...

FROM python:3.11-slim AS base

# ---- system deps -----------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgdal-dev \
        gdal-bin \
        libproj-dev \
        libgeos-dev \
        libspatialindex-dev \
        git \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---- build stage -----------------------------------------------------------
FROM base AS builder

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
# Build a wheel and install it non-editably so the runtime stage does not
# need the build directory.  An editable install (-e) would leave an egg-link
# pointing at /build/src/ which does not exist in the runtime stage.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel build \
    && python -m build --wheel --no-isolation \
    && pip install --no-cache-dir ".[swatplus]" dist/swatplus_builder-*.whl

# ---- runtime stage ---------------------------------------------------------
FROM base AS runtime

LABEL org.opencontainers.image.title="swatplus-builder" \
      org.opencontainers.image.description="Agent-operable SWAT+ framework (no QGIS)" \
      org.opencontainers.image.source="https://github.com/mgalib/swatplus-builder"

# Copy installed packages from builder (site-packages, entry-point scripts).
COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin/swat /usr/local/bin/swat

# Non-root user for safe agent execution.
RUN useradd -m -s /bin/bash swatrunner
USER swatrunner

# ---------------------------------------------------------------------------
# Runtime environment
# ---------------------------------------------------------------------------
# SWATPLUS_EXE  — absolute path to the SWAT+ engine binary (mount at runtime).
# SWATPLUS_BUILDER_ARTIFACTS — root for all artifact persistence.
# SWATPLUS_DATASETS_DB       — path to reference datasets SQLite (mount at runtime).
ENV SWATPLUS_EXE=/opt/swatplus/swatplus_exe \
    SWATPLUS_BUILDER_ARTIFACTS=/data/artifacts \
    SWATPLUS_DATASETS_DB=/data/swatplus_datasets.sqlite \
    PYTHONUNBUFFERED=1

VOLUME ["/data/artifacts", "/opt/swatplus"]

WORKDIR /workspace

ENTRYPOINT ["swat"]
CMD ["--help"]
