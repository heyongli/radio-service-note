#!/bin/bash
# 远程从机扫描脚本 (10.0.0.121, 14 CPU) - 部署在 /opt/pcbocr/
# 用法: ./slave_remote.sh top600 | bot600 | smoke | check | pull
cd /opt/pcbocr
TASK="$1"
case "$TASK" in
  top600)
    mkdir -p runs/top600
    setsid /opt/ocrvenv/bin/python3 tools/ai_ocr_eval/ai_refdes_ocr.py \
      --img render/pcb-top-600-1.png --img-dpi 600 --out-dpi 600 \
      --preset full --stage1-engines v4,v5s --stage2-engines v4,v6 \
      --stages 1,2 --tile 900 --overlap 350 --stage1-upscale 1.5 \
      --stage1-rots 0,90,270 \
      --out runs/top600/result.json --runs-dir runs/top600 \
      --tag top600 --only-refdes > runs/top600/log.txt 2>&1 < /dev/null &
    echo "top600 launched pid=$!";;
  bot600)
    mkdir -p runs/bot600
    setsid /opt/ocrvenv/bin/python3 tools/ai_ocr_eval/ai_refdes_ocr.py \
      --img render/pcb-bot-600-1.png --img-dpi 600 --out-dpi 600 \
      --preset full --stage1-engines v4,v5s --stage2-engines v4,v6 \
      --stages 1,2 --tile 900 --overlap 350 --stage1-upscale 1.5 \
      --stage1-rots 0,90,270 \
      --out runs/bot600/result.json --runs-dir runs/bot600 \
      --tag bot600 --only-refdes > runs/bot600/log.txt 2>&1 < /dev/null &
    echo "bot600 launched pid=$!";;
  smoke)
    /opt/ocrvenv/bin/python3 tools/ai_ocr_eval/ai_refdes_ocr.py \
      --img render/pcb-top-300-1.png --img-dpi 300 --preset fast \
      --stage1-engines v4 --stages 1 --tile 1000 --overlap 200 \
      --out runs/smoke.json --runs-dir runs --tag smoke --only-refdes 2>&1 \
      | grep -vE "INFO|WARNING" | tail -2;;
  check)
    echo "== running: $(ps aux | grep ai_refdes_ocr | grep -v grep | wc -l)";;
  pull)
    for d in top600 bot600; do
      [ -f "runs/$d/result.json" ] && echo "  $d: $(python3 -c "import json;d=json.load(open('runs/$d/result.json'));print(len(d['hits']),'hits')" 2>/dev/null)"
    done;;
  *)
    echo "usage: $0 top600|bot600|smoke|check|pull";;
esac
