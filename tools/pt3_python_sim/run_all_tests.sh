#!/bin/bash
# PT3 simulator full regression — runs all 19 test files
# Expected: every file reports "Match rate: 100.00%"

set -e
cd "$(dirname "$0")"

echo ""
echo "PT3 Simulator Full Regression"
echo "============================="
echo ""
printf "%-65s %8s  %s\n" "File" "Match" "Status"
echo "-----------------------------------------------------------------------------------"

# Temp file for results so we can sort + count
TMP=$(mktemp)
trap "rm -f $TMP" EXIT

# Known test file pairs (non-standard naming — PSG has _ref suffix or different basename)
declare -A PAIRS=(
    ["test_files/yerzmyey.pt3"]="test_files/yerzmyey_ref.psg"
)

# Standard pairs — any .pt3 that has matching .psg
for pt3 in test_files/*.pt3; do
    psg="${pt3%.pt3}.psg"
    if [ -f "$psg" ] && [ -z "${PAIRS[$pt3]:-}" ]; then
        PAIRS["$pt3"]="$psg"
    fi
done

TOTAL=0
PASS=0

for pt3 in "${!PAIRS[@]}"; do
    psg="${PAIRS[$pt3]}"
    if [ ! -f "$psg" ]; then
        continue
    fi
    TOTAL=$((TOTAL+1))
    result=$(python3 pt3_simulator.py "$pt3" "$psg" 2>&1 | grep "Match rate" | awk '{print $3}')
    short=$(basename "$pt3" .pt3 | cut -c1-62)
    if [ "$result" = "100.0%" ]; then
        printf "  %-65s %8s  OK\n" "$short" "$result" >> "$TMP"
        PASS=$((PASS+1))
    else
        printf "  %-65s %8s  FAIL\n" "$short" "$result" >> "$TMP"
    fi
done

sort "$TMP"

echo ""
echo "-----------------------------------------------------------------------------------"
echo "Total: $PASS/$TOTAL passed"
if [ "$PASS" -eq "$TOTAL" ]; then
    echo "ALL TESTS PASS -- bit-exact match against VTII reference"
    exit 0
else
    echo "$((TOTAL-PASS)) tests failed -- regression detected!"
    exit 1
fi
