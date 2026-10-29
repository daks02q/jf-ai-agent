#!/usr/bin/env bash
set -euo pipefail

export OMP_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
export MKL_NUM_THREADS=2
export NUMEXPR_NUM_THREADS=2
export VECLIB_MAXIMUM_THREADS=2
export KMP_BLOCKTIME=0
export KMP_INIT_AT_FORK=FALSE
export OMP_WAIT_POLICY=PASSIVE
export GOMP_SPINCOUNT=0

exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 "$@"
