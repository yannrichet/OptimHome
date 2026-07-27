#!/bin/bash
set -e
PARAMS_FILE="${1:-params.txt}"
CASE_ID=$(grep '^case_id=' "$PARAMS_FILE" | cut -d= -f2-)
ENV_FILE="${TMPDIR:-/tmp}/buildingopt_case_${CASE_ID}.sh"
source "$ENV_FILE"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cp -f "$REPO_DIR/BuildingOpt_init.xml" .
cp -f "$REPO_DIR/BuildingOpt_JacA.bin" . 2>/dev/null || true
"$REPO_DIR/BuildingOpt" -override="$OV" -startTime="$STARTT" -stopTime="$STOPT" -stepSize=3600 -r=res.csv > om.log 2>&1
