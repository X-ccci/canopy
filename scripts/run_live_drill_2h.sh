#!/bin/bash
# ============================================================
# Canopy 2-Hour Live Drill Launcher
# 运行方式：在终端中执行
#   chmod +x /Users/cccc/Desktop/canopy/scripts/run_live_drill_2h.sh
#   /Users/cccc/Desktop/canopy/scripts/run_live_drill_2h.sh
#
# 或直接用 python 运行：
#   python /Users/cccc/Desktop/canopy/scripts/live_drill.py --duration 7200 --report-interval 300
# ============================================================

cd /Users/cccc/Desktop/canopy

echo "============================================"
echo " Canopy Live Drill — 2-Hour Session"
echo " Duration : 7200s (2h)"
echo " Report   : every 300s (5 min)"
echo " Start    : $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"
echo ""

python scripts/live_drill.py --duration 7200 --report-interval 300

echo ""
echo "============================================"
echo " Drill finished at $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"
