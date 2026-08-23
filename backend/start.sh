#!/bin/bash
set -e
cd "$(dirname "$0")"

PY=~/.workbuddy/binaries/python/envs/default/bin/python
PORT=8765
LOG=/tmp/astock-review.log
PIDFILE=/tmp/astock-review.pid

# 若已在运行，先提示
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "已在运行 (PID $(cat "$PIDFILE"))，无需重复启动。"
  exit 0
fi

# 取局域网 IP（用于手机扫码）
IP=$(ifconfig 2>/dev/null | grep -Eo '192\.168\.[0-9]+\.[0-9]+' | head -1)
[ -z "$IP" ] && IP=$(ipconfig getifaddr en0 2>/dev/null || true)

echo "================================================"
echo "  A股复盘系统 启动中…"
echo "  本地访问:  http://localhost:$PORT"
if [ -n "$IP" ]; then
  echo "  手机访问:  http://$IP:$PORT  (扫交易记录页顶部二维码)"
else
  echo "  手机访问:  未能自动获取局域网IP，请用 ifconfig 查看"
fi
echo "  远程访问:  Tailscale 连上后手机开 http://<tailscale-ip>:$PORT/m"
echo "  防睡眠:    已用 caffeinate 保持 Mac 不睡眠（接电源时，停服即恢复）"
echo "================================================"

# 用 caffeinate -s 包住 uvicorn：只要服务在跑，Mac 就不深度睡眠（需接电源）；
# 停服(caffeinate 随子进程退出)后 Mac 可正常睡眠。避免出门后 Mac 睡眠导致远程连不上。
nohup caffeinate -s "$PY" -m uvicorn server:app --host 0.0.0.0 --port "$PORT" > "$LOG" 2>&1 &
echo $! > "$PIDFILE"
sleep 1
if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "✅ 已启动 (PID $(cat "$PIDFILE"))"
  echo "   日志: $LOG"
  echo "   停止: bash stop.sh"
else
  echo "❌ 启动失败，查看日志: $LOG"
  cat "$LOG"
  exit 1
fi
