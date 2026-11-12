#!/bin/sh
# Score the last assistant turn when a coding agent stops.
# did the work: the turn was scored and the summary is on stderr when it is over the max.
# had no work: stop_hook_active is set, or there is no transcript to score.
# could not do it: the payload or the checker could not be used.
# Exit 2 tells Claude Code to show stderr to the model. Exit 0 does not block.

set -eu

HOOK_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH='' cd -- "$HOOK_DIR/.." && pwd)
CHECK="$ROOT/writing_check.py"

if ! command -v python3 >/dev/null 2>&1; then
  echo "writing-check: could not do it" >&2
  exit 0
fi
if [ ! -f "$CHECK" ]; then
  echo "writing-check: could not do it" >&2
  exit 0
fi

payload=$(cat || true)
parsed=$(printf '%s' "$payload" | python3 -c '
import json, sys
raw = sys.stdin.read()
try:
    data = json.loads(raw) if raw.strip() else {}
except Exception:
    sys.stdout.write("bad\n\n")
    raise SystemExit(0)
if not isinstance(data, dict):
    sys.stdout.write("bad\n\n")
    raise SystemExit(0)
flag = data.get("stop_hook_active")
active = flag is True or flag == 1 or flag == "true"
path = data.get("transcript_path") or ""
if not isinstance(path, str):
    path = ""
path = path.replace("\n", "").replace("\r", "")
sys.stdout.write(("1" if active else "0") + "\n" + path + "\n")
')

flag=$(printf '%s\n' "$parsed" | sed -n '1p')
path=$(printf '%s\n' "$parsed" | sed -n '2p')

if [ "$flag" = "bad" ]; then
  echo "writing-check: could not do it" >&2
  exit 0
fi

if [ "$flag" = "1" ]; then
  echo "writing-check: had no work" >&2
  exit 0
fi

if [ -z "$path" ]; then
  echo "writing-check: had no work" >&2
  exit 0
fi

max=${WRITING_CHECK_MAX:-15}
set +e
summary=$(python3 "$CHECK" --transcript "$path" --last 1 --max "$max" --quiet)
status=$?
set -e

if [ "$status" -eq 1 ]; then
  printf '%s\n' "$summary" >&2
  echo "writing-check: did the work" >&2
  exit 2
fi
if [ "$status" -eq 0 ]; then
  exit 0
fi
echo "writing-check: could not do it" >&2
exit 0
