#!/usr/bin/env sh
set -eu

TMP_FILE="$(mktemp)"
(crontab -l 2>/dev/null | grep -v "session_to_song.cli morning-alarm" | grep -v "# session-to-song morning alarm" || true) > "$TMP_FILE"
crontab "$TMP_FILE"
rm -f "$TMP_FILE"
echo "Removed session-to-song morning alarm cron entries."
