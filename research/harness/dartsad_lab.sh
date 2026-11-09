#!/usr/bin/env bash
# Launch one phase of the darts anomaly study on the lab, detached.
#
#   ./.secrets/lab.sh sync
#   ./.secrets/lab.sh exec '$HOME/till_infinity/repo/research/harness/dartsad_lab.sh score'
#   ./.secrets/lab.sh exec '$HOME/till_infinity/repo/research/harness/dartsad_lab.sh report'
#   ./.secrets/lab.sh exec 'tail -40 $HOME/till_infinity/logs/dartsad_score.log'
#
# `DARTSAD_TAG` suffixes the log and flag names so a second grid - the deep
# pass, which drops the quadratic scorer to reach 200,000 bars - does not
# overwrite the first one's log:
#
#   DARTSAD_TAG=deep .../dartsad_lab.sh score BARS=200000 \
#       SCORERS=norm,kmeans1,kmeans10,iforest10 DARTSAD_OUT=$HOME/till_infinity/out/dartsad_deep
#
# `lab.sh run` cannot be used: it launches the repo's own venv, and `u8darts`
# brings numpy 2.5 and pandas 3.1 majors that must not be installed beside the
# suite's. The darts venv is built once with
#
#   /usr/bin/python3.12 -m venv $HOME/till_infinity/.venv-darts
#   $HOME/till_infinity/.venv-darts/bin/pip install u8darts pyod
#
# One thread per process, because `phase_score` runs a 25-way pool and sklearn's
# own threading drove the load average to 658 on 64 cores once already.
set -euo pipefail

PHASE="${1:?usage: dartsad_lab.sh <score|report|power|leak> [KEY=VAL ...]}"
shift || true

ROOT="$HOME/till_infinity"
PY="$ROOT/.venv-darts/bin/python"
[ -x "$PY" ] || { echo "no darts venv at $PY - see the header" >&2; exit 1; }
mkdir -p "$ROOT/logs"

NAME="dartsad_$PHASE${DARTSAD_TAG:+_$DARTSAD_TAG}"
LOG="$ROOT/logs/$NAME.log"
rm -f "$LOG" "$ROOT/logs/$NAME.flag"

nohup env \
  OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  PYTHONPATH="$ROOT/repo" PHASE="$PHASE" "$@" \
  sh -c "$PY -u $ROOT/repo/research/harness/dartsad_run.py > $LOG 2>&1; \
         echo done > $ROOT/logs/$NAME.flag" >/dev/null 2>&1 &

echo "launched $NAME -> $LOG"
