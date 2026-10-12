#!/bin/sh
# Passes when the library's OpenSTA check passed: every declared path and
# ordering of the timing contract measured on the routed netlist, in bounds.
# With EXPECT=fail it passes only when the check found a violation.
set -eu
dir="$1"
status=$(sed -n 's/.*"status": "\([A-Z_]*\)".*/\1/p' "$dir/sta/result.json" 2>/dev/null | head -1)
grep -h 'CA_TIMING_PATH\|CA_TIMING_ORDER\|TIMING_' "$dir/sta/opensta.log" 2>/dev/null | head -200 || true
echo "status: ${status:-none}"
if [ "${EXPECT:-pass}" = fail ]; then
  [ "$status" = ERROR ] && grep -q 'TIMING_MIN_VIOLATION\|TIMING_MAX_VIOLATION\|TIMING_ORDER_VIOLATION' "$dir/sta/opensta.log"
else
  [ "$status" = CHECKED_DECLARED_PATHS ]
fi
