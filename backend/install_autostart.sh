#!/bin/bash
# 安装 A股复盘系统 为 macOS 开机自启（launchd 用户代理）
# 用法：在终端里运行
#   bash /Users/fy/WorkBuddy/2026-08-21-20-23-08/astock-review/install_autostart.sh
#
# 说明：
# - 把 plist 软链/拷到 ~/Library/LaunchAgents，并用 launchctl bootstrap+load 加载
# - 登录后自动启动 uvicorn(:8765)，KeepAlive 崩溃自动重启，caffeinate -s 防深度睡眠（需接电源）
# - 卸载：launchctl bootout gui/$(id -u)/com.astock-review.server

set -e
PLIST_SRC="/Users/fy/WorkBuddy/2026-08-21-20-23-08/astock-review/com.astock-review.server.plist"
AGENTS_DIR="$HOME/Library/LaunchAgents"
DEST="$AGENTS_DIR/com.astock-review.server.plist"
LABEL="com.astock-review.server"

mkdir -p "$AGENTS_DIR"

# 先卸旧（若存在）
if launchctl list | grep -q "$LABEL"; then
  echo "发现已加载的旧服务，先卸载…"
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  sleep 1
fi

# 复制（不用软链，避免路径权限问题）
cp "$PLIST_SRC" "$DEST"
echo "已写入: $DEST"

# 加载（用户域，登录即起）
launchctl bootstrap "gui/$(id -u)" "$DEST"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null || true

sleep 2
if launchctl list | grep -q "$LABEL"; then
  echo "✅ 自启服务已安装并启动"
  echo "   查看状态: launchctl list | grep astock-review"
  echo "   本地访问: http://localhost:8765"
  echo "   手机访问: http://$(ipconfig getifaddr en0 2>/dev/null || echo '你的局域网IP'):8765/m"
else
  echo "❌ 加载似乎未完成，请检查: launchctl error"
fi
