#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

TRANSCRIPT="$TMP_DIR/transcript.txt"
"$ROOT/scripts/demo.sh" > "$TRANSCRIPT"

FONT="/System/Library/Fonts/Menlo.ttc"
if [[ ! -f "$FONT" ]]; then
  FONT="/System/Library/Fonts/SFNSMono.ttf"
fi

line_count="$(wc -l < "$TRANSCRIPT" | tr -d ' ')"
frames=(1 3 6 9 13 "$line_count")

index=0
for line_limit in "${frames[@]}"; do
  index=$((index + 1))
  frame_text="$TMP_DIR/frame-${index}.txt"
  head -n "$line_limit" "$TRANSCRIPT" > "$frame_text"

  magick \
    -size 1100x720 xc:"#0f172a" \
    -fill "#111827" -draw "roundrectangle 16,16 1084,704 10,10" \
    -fill "#ef4444" -draw "circle 44,42 52,42" \
    -fill "#f59e0b" -draw "circle 70,42 78,42" \
    -fill "#22c55e" -draw "circle 96,42 104,42" \
    -fill "#94a3b8" -font "$FONT" -pointsize 16 -annotate +130+48 "pr-artifact-skills demo" \
    -fill "#e5e7eb" -font "$FONT" -pointsize 18 -interline-spacing 5 -annotate +36+92 "@$frame_text" \
    "$TMP_DIR/frame-${index}.png"
done

magick -delay 80 -loop 0 "$TMP_DIR"/frame-*.png "$ROOT/assets/demo.gif"

printf '%s\n' "$ROOT/assets/demo.gif"
