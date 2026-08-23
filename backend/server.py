"""A股周期复盘系统 · 服务端（FastAPI）。

启动：
    /Users/fy/.workbuddy/binaries/python/envs/default/bin/python -m uvicorn server:app --port 8765
访问：
    http://localhost:8765
"""
from pathlib import Path
import json
import os

from fastapi import FastAPI, File, HTTPException, UploadFile, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db

app = FastAPI(title="A股周期复盘系统")

# 允许跨源访问：手机通过 Mac 局域网地址(http://192.168.x.x:8765)打开页面时，
# 从该页面 fetch 本服务属于跨源请求，必须放开 CORS 否则被浏览器拦截。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

SHOTS_DIR = Path(__file__).parent / "data" / "shots"
SHOTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/shots", StaticFiles(directory=SHOTS_DIR), name="shots")

ALLOWED_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/m")
def mobile_mood():
    """手机专用盯盘情绪极简记录页。"""
    return FileResponse(STATIC_DIR / "m.html")


@app.get("/sw.js")
def service_worker():
    """PWA Service Worker（根路径，作用域为 /，仅缓存 /m 与 manifest）。"""
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")


@app.get("/api/health")
def health():
    return {"ok": True, "service": "astock-review", "version": "0.1.0"}


# ---------- 股票代码表（开仓表单联想用，构建期生成 data/stocks.json） ----------

_STOCKS_CACHE = None


@app.get("/api/stocks")
def get_stocks():
    global _STOCKS_CACHE
    if _STOCKS_CACHE is None:
        p = Path(__file__).parent / "data" / "stocks.json"
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                _STOCKS_CACHE = json.load(f)
        else:
            _STOCKS_CACHE = []
    return _STOCKS_CACHE


# ---------- 手机访问二维码 ----------

def _lan_ip() -> str:
    """取本机局域网 IP（不实际发包，仅让系统选路由）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


@app.get("/api/qrcode")
def api_qrcode():
    """当前局域网地址的二维码（SVG），IP 变化后自动更新。"""
    import io

    import qrcode
    import qrcode.image.svg

    url = f"http://{_lan_ip()}:8765"
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage,
                      box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    from fastapi.responses import Response
    return Response(content=buf.getvalue(), media_type="image/svg+xml",
                    headers={"X-Lan-Url": url})


# ---------- 每日记录 ----------

class DayPayload(BaseModel):
    auto: dict | None = None
    manual: dict | None = None


@app.get("/api/days")
def api_list_days(limit: int = 60):
    return db.list_days(limit)


@app.get("/api/days/{date}")
def api_get_day(date: str):
    day = db.get_day(date)
    if day is None:
        raise HTTPException(404, f"无 {date} 记录")
    day["yesterday_conditions"] = db.get_conditions(db.prev_trading_date(date) or "")
    return day


@app.put("/api/days/{date}")
def api_upsert_day(date: str, payload: DayPayload):
    if payload.auto is None and payload.manual is None:
        raise HTTPException(400, "auto 与 manual 至少传一个")
    result = db.upsert_day(date, payload.auto, payload.manual)
    db.sync_trade_cycles()   # 周期定位更新后，同步到持仓中的交易
    return result


@app.delete("/api/days/{date}")
def api_delete_day(date: str):
    if not db.delete_day(date):
        raise HTTPException(404, f"无 {date} 的复盘记录")
    return {"ok": True}


# ---------- 盯盘情绪记录 ----------

class MoodPayload(BaseModel):
    ts: str | None = None
    emotion: str = ""
    intensity: int = 0
    trigger: str = ""
    urge: str = ""
    position_pct: float | None = None
    pnl_pct: float | None = None
    plan: str = ""
    acted: bool = False
    note: str = ""


@app.get("/api/moods")
def api_list_moods():
    return db.list_moods()


@app.post("/api/moods")
def api_add_mood(payload: MoodPayload):
    return db.add_mood({
        "ts": payload.ts, "emotion": payload.emotion, "intensity": payload.intensity,
        "trigger": payload.trigger, "urge": payload.urge,
        "position_pct": payload.position_pct, "pnl_pct": payload.pnl_pct,
        "plan": payload.plan, "acted": payload.acted, "note": payload.note,
    })


@app.delete("/api/moods/{mid}")
def api_delete_mood(mid: int):
    if not db.delete_mood(mid):
        raise HTTPException(404, f"无 id={mid} 的情绪记录")
    return {"ok": True}


@app.post("/api/moods/import")
def api_import_moods(items: list = Body(...)):
    """导入手机 m.html 导出的 JSON（[{localId, payload}]），按 local_id 去重。"""
    if not isinstance(items, list):
        raise HTTPException(400, "body 须为数组")
    return db.bulk_import_moods(items)


@app.get("/api/moods/export")
def api_export_moods():
    """导出全部情绪记录（备份 / 迁移用）。"""
    return db.export_moods()


# ---------- 数据采集 ----------

@app.post("/api/collect")
def api_collect(date: str | None = None, mock: bool = False):
    """触发一次采集（页面上点按钮用）。date 缺省为今天。"""
    import datetime as dt

    import collector

    target = date or dt.date.today().isoformat()
    auto = collector.collect(target, mock=mock)
    return db.get_day(target)


# ---------- 交易记录（回合制） ----------

class TradePayload(BaseModel):
    stock_code: str = ""
    stock_name: str
    sector: str = ""
    open_date: str
    open_price: float
    shares: float
    position_pct: float | None = None
    strategy: str = "其他"
    emotion: str = ""
    open_reason: str = ""
    notes: str = ""


@app.get("/api/trades")
def api_list_trades(status: str | None = None):
    return db.list_trades(status)


@app.post("/api/trades")
def api_add_trade(payload: TradePayload):
    if payload.open_price <= 0 or payload.shares <= 0:
        raise HTTPException(400, "开仓价和股数必须大于 0")
    return db.add_trade(payload.model_dump())


@app.delete("/api/trades/{tid}")
def api_delete_trade(tid: int):
    if not db.delete_trade(tid):
        raise HTTPException(404, f"无 id={tid} 的交易")
    return {"ok": True}


class ClosePayload(BaseModel):
    close_date: str
    close_price: float
    close_reason: str = ""
    close_summary: str = ""
    close_emotion: str = ""


@app.post("/api/trades/{tid}/close")
def api_close_trade(tid: int, payload: ClosePayload):
    result = db.close_trade(tid, payload.close_date, payload.close_price, payload.close_reason,
                            payload.close_summary, payload.close_emotion)
    if result is None:
        raise HTTPException(404, f"无 id={tid} 的交易")
    return result


@app.post("/api/trades/{tid}/reopen")
def api_reopen_trade(tid: int):
    result = db.reopen_trade(tid)
    if result is None:
        raise HTTPException(404, f"无 id={tid} 的交易")
    return result


@app.get("/api/stats")
def api_stats():
    return db.trade_stats()


# ---------- 交易截图（买入点记录：分时 / 日K） ----------

@app.post("/api/trades/{tid}/shot")
async def api_upload_shot(tid: int, kind: str, file: UploadFile = File(...)):
    """上传买入点截图。kind: min=分时图, k=日K图。"""
    if kind not in ("min", "k"):
        raise HTTPException(400, "kind 必须是 min（分时）或 k（日K）")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_IMG_EXT:
        raise HTTPException(400, f"仅支持图片格式：{' '.join(sorted(ALLOWED_IMG_EXT))}")
    name = f"trade{tid}_{kind}{ext}"
    (SHOTS_DIR / name).write_bytes(await file.read())
    result = db.set_trade_shot(tid, kind, f"/shots/{name}")
    if result is None:
        raise HTTPException(404, f"无 id={tid} 的交易")
    return result


@app.delete("/api/trades/{tid}/shot")
def api_delete_shot(tid: int, kind: str):
    if kind not in ("min", "k"):
        raise HTTPException(400, "kind 必须是 min（分时）或 k（日K）")
    trade = db.get_trade(tid)
    if trade is None:
        raise HTTPException(404, f"无 id={tid} 的交易")
    old = trade.get(f"shot_{kind}")
    if old:
        f = SHOTS_DIR / Path(old).name
        if f.exists():
            f.unlink()
    return db.set_trade_shot(tid, kind, None)


# ---------- 验证条件 ----------

class Condition(BaseModel):
    metric: str
    base: str = ""
    threshold: str
    if_hit: str = ""
    direction: str = "中性"
    signal_type: str = "其他"


class ConditionsPayload(BaseModel):
    conditions: list[Condition]


@app.get("/api/verify/{written_date}")
def api_get_conditions(written_date: str):
    return db.get_conditions(written_date)


@app.post("/api/verify/{written_date}")
def api_save_conditions(written_date: str, payload: ConditionsPayload):
    return db.save_conditions(written_date, [c.model_dump() for c in payload.conditions])


class CheckPayload(BaseModel):
    actual: str
    final_result: str          # triggered / not_triggered / noise
    override_reason: str = ""


@app.post("/api/verify/check/{cond_id}")
def api_check_condition(cond_id: int, payload: CheckPayload):
    if payload.final_result not in ("triggered", "not_triggered", "noise"):
        raise HTTPException(400, "final_result 必须是 triggered / not_triggered / noise")
    result = db.check_condition(cond_id, payload.actual, payload.final_result, payload.override_reason)
    if result is None:
        raise HTTPException(404, f"无 id={cond_id} 的条件")
    return result
