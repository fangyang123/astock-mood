#!/bin/bash
PIDFILE=/tmp/astock-review.pid
if [ -f "$PIDFILE" ]; then
  PID=$(cat "$PIDFILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" && echo "✅ 已停止 (PID $PID)"
  else
    echo "进程 $PID 已不存在"
  fi
  rm -f "$PIDFILE"
else
  echo "未找到 PID 文件，可能未在运行。"
  # 兜底：按端口查找并杀掉
  P=$(lsof -ti tcp:8765 2>/dev/null || true)
  if [ -n "$P" ]; then kill $P && echo "已按端口停止 $P"; fi
fi
