#!/usr/bin/env bash
# 把若干时间窗的渲染帧 + 原曲音频，拼成一条「字幕设计样片」。
#
#   tools/build_demo_reel.sh out.mp4 "1.5:7.5:announce" "44.9:52.0:hype" ...
#
# 每段：/tmp/demo/<name>/f%04d.png 由 tools/render_chunks.py 或临时窗渲染产出；
# 音频从 --audio-src（默认成片预览）按同一时间窗切片，保证和成片一致。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:?usage: build_demo_reel.sh out.mp4 a:b:name ...}"
shift
AUDIO_SRC="${AUDIO_SRC:-$ROOT/out/preview-full-naturalrate-720p.mp4}"
FPS="${FPS:-24}"
mkdir -p /tmp/demo_seg
rm -f /tmp/demo_seg/*.mp4 /tmp/demo_seg/list.txt
i=0
for spec in "$@"; do
  a="${spec%%:*}"; rest="${spec#*:}"; b="${rest%%:*}"; name="${rest#*:}"
  dur=$(python3 -c "print($b-$a)")
  ffmpeg -y -loglevel error \
    -framerate "$FPS" -i "/tmp/demo/$name/f%04d.png" \
    -ss "$a" -t "$dur" -i "$AUDIO_SRC" \
    -map 0:v:0 -map 1:a:0 -c:v libx264 -crf 16 -pix_fmt yuv420p -r "$FPS" \
    -c:a aac -b:a 192k "/tmp/demo_seg/$(printf '%02d' $i)-$name.mp4"
  echo "file '/tmp/demo_seg/$(printf '%02d' $i)-$name.mp4'" >> /tmp/demo_seg/list.txt
  i=$((i+1))
done
ffmpeg -y -loglevel error -f concat -safe 0 -i /tmp/demo_seg/list.txt -c copy "$OUT"
echo "wrote $OUT"
