#!/bin/bash
# 把当前剪贴板里的 PNG 存成 README 界面截图。
# 用法: ./save-clip.sh <序号 1-7>
#   1 concept  -> 01-overview.png          概览
#   2          -> 02-story-beats.png       故事正片
#   3          -> 03-story-arcs.png        故事脉络
#   4          -> 04-character-relations.png 人物关系
#   5          -> 05-qa.png                问答
#   6          -> 06-setting-cards.png     设定卡
#   7          -> 07-full-graph.png        完整图谱
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

case "${1:-}" in
  1) NAME="01-overview.png" ;;
  2) NAME="02-story-beats.png" ;;
  3) NAME="03-story-arcs.png" ;;
  4) NAME="04-character-relations.png" ;;
  5) NAME="05-qa.png" ;;
  6) NAME="06-setting-cards.png" ;;
  7) NAME="07-full-graph.png" ;;
  *) echo "用法: $0 <1-7>  (1概览 2故事正片 3故事脉络 4人物关系 5问答 6设定卡 7完整图谱)"; exit 1 ;;
esac

OUT="$DIR/$NAME"
if ! osascript -e 'the clipboard as «class PNGf»' > /dev/null 2>&1; then
  echo "剪贴板里没有 PNG 图片。请先截图/复制图片再运行。"; exit 1
fi
osascript \
  -e 'set thePng to (the clipboard as «class PNGf»)' \
  -e "set fp to open for access POSIX file \"$OUT\" with write permission" \
  -e 'set eof fp to 0' \
  -e 'write thePng to fp' \
  -e 'close access fp'
echo "已保存: $OUT"
file "$OUT"
