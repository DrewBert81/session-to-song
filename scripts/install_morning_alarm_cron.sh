#!/usr/bin/env sh
set -eu

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TARGET_DIR="${1:-$HOME/sessiontosong/alarms}"
RUN_TIME="${2:-30 3}"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
LOG_DIR="$REPO_ROOT/content/output/morning-alarm/logs"

if [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3 || command -v python)"
fi

mkdir -p "$TARGET_DIR" "$LOG_DIR"

CRON_LINE="$RUN_TIME * * * cd '$REPO_ROOT' && '$PYTHON' -m session_to_song.cli morning-alarm --target-dir '$TARGET_DIR' >> '$LOG_DIR/cron.stdout.log' 2>> '$LOG_DIR/cron.stderr.log'"
MARKER="# session-to-song morning alarm"
TMP_FILE="$(mktemp)"

(crontab -l 2>/dev/null | grep -v "session_to_song.cli morning-alarm" | grep -v "$MARKER" || true) > "$TMP_FILE"
printf '%s\n%s\n' "$MARKER" "$CRON_LINE" >> "$TMP_FILE"
crontab "$TMP_FILE"
rm -f "$TMP_FILE"

echo "Installed session-to-song morning alarm cron."
echo "Schedule: $RUN_TIME * * *"
echo "Target folder: $TARGET_DIR"
