#!/bin/bash
set -e
OV=$(grep -E '^[a-zA-Z_]+=' "${1:-params.txt}" | paste -sd, -)   # fz passe le fichier compile en argument
cp -f /Users/richet/Downloads/optimhome/optimhome/BuildingOpt_init.xml /Users/richet/Downloads/optimhome/optimhome/weather_orly.txt .
cp -f /Users/richet/Downloads/optimhome/optimhome/BuildingOpt_JacA.bin . 2>/dev/null || true
/Users/richet/Downloads/optimhome/optimhome/BuildingOpt -override="$OV" -r=res.csv > om.log 2>&1
