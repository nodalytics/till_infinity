#!/usr/bin/env bash
# Runs gbmenvelope.py's jobs on the lab, ten at a time, niced and thread-capped, then the report.
#   research/harness/gbmenvelope.sh      (from $HOME/till_infinity, with repo/ and data/seqlab)
set -u
cd "$HOME/till_infinity"
export SEQLAB="$HOME/till_infinity/data/seqlab" OUT="$HOME/till_infinity/data/gbmenvelope"
export PYTHONPATH="$HOME/till_infinity/repo" OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
PY="$HOME/till_infinity/.venv/bin/python"
job() {
  local h=$1 fam=$2
  PART=run HORIZON=$h FAMILY=$fam nice -n 10 "$PY" -W ignore -u repo/research/harness/gbmenvelope.py \
    > "logs/gbmenvelope_${h}_${fam}.log" 2>&1
}
export -f job
export PY
{
  for h in 50 20 5; do
    for fam in pooled fx dex boomcrash crypto driftswitch rangebreak metals walks_iid walks_garch; do
      echo "$h $fam"
    done
  done
} | xargs -P 10 -L 1 bash -c 'job "$0" "$1"'
PART=size nice -n 10 "$PY" -W ignore -u repo/research/harness/gbmenvelope.py > logs/gbmenvelope_size.log 2>&1
PART=report nice -n 10 "$PY" -W ignore -u repo/research/harness/gbmenvelope.py > logs/gbmenvelope_report.log 2>&1
echo done > logs/gbmenvelope.flag
