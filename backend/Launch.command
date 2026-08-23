#!/bin/bash
# 双击即可启动 A股复盘系统（macOS）
# 服务器会在前台运行，终端窗口显示实时日志；关闭窗口或 Cmd+C 即停止。
cd "$(dirname "$0")"
PY=~/.workbuddy/binaries/python/envs/default/bin/python
PORT=8765

IP=$(ifconfig 2>/dev/null | grep -Eo '192\.168\.[0-9]+\.[0-9]+' | head -1)
[ -z "$IP" ] && IP=$(ipconfig getifaddr en0 2>/dev/null)

echo "========================================="
echo " A股复盘系统"
echo " 本地访问:   http://localhost:$PORT"
if [ -n "$IP" ]; then
  echo " 手机访问:   http://$IP:$PORT  (交易记录页顶部扫二维码)"
fi
echo " 关闭: 关闭本窗口 或 Cmd+C"
echo "========================================="
echo ""
exec "$PY" -m uvicorn server:app --host 0.0.0.0 --port $PORT
