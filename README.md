# A股盯盘复盘 · 云端版

A股盯盘情绪记录 + 交易记录工具。数据全部存 **Supabase 云端**，Mac / 手机 / 任意设备通过 GitHub Pages 访问，三端自动同步。

## 在线访问
- 看板（交易记录 / 盯盘情绪 / 复盘）：https://fangyang123.github.io/astock-mood/
- 手机快速记录（盯盘情绪）：https://fangyang123.github.io/astock-mood/m.html

## 架构
- **前端**：纯静态（Vue 3 + Supabase JS，均本地打包，不依赖 CDN），由 GitHub Pages 托管。
- **数据库**：Supabase Postgres，表：`mood_log`（盯盘情绪）、`trades`（交易记录）、`daily_records`（每日复盘）、`verify_conditions`（验证条件）。
- **截图存储**：Supabase Storage 公开 bucket `trade-shots`，交易买卖点截图直传云端（匿名可写、公开可读），字段 `shot_min`/`shot_k` 存完整公开 URL。
- **本地服务（可选兜底）**：`backend/server.py` 是 Mac 本地 Flask 服务，仅在本地局域网（`http://<IP>:8765`）使用；云端页面优先走 Supabase，本地服务不可用也不影响。

## 仓库结构
```
/                     网站根（GitHub Pages 读取此处）
  index.html          看板页
  m.html              手机情绪记录页
  static/             JS/CSS/配置（supabase-js、vue、supabase_config.js）
  sw.js               PWA Service Worker
  .nojekyll           跳过 Jekyll 构建
backend/              Python 后端源码与脚本（本地服务用，非网站必需）
  server.py           Flask 服务
  db.py               SQLite 存储层（本地兜底）
  collector.py        自动采集
  supabase_create_tables.sql   云端建表 SQL
```

## 云端配置
`static/supabase_config.js` 中：
```
window.SUPABASE_URL = "https://ulgoozjkbngiqtovhfbf.supabase.co";
window.SUPABASE_KEY = "sb_publishable_-ua0XPCaZhI1pgaG7cJdxw_himPm8KI";
```
publishable key 是公开的，可安全放在前端。

## 本地运行（可选）
```bash
cd backend
pip install fastapi uvicorn supabase
python server.py
# 浏览器打开 http://localhost:8765/
```
