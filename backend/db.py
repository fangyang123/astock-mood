"""SQLite 存储层：每日复盘记录 + 明日验证条件。"""
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "review.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_records (
    date         TEXT PRIMARY KEY,          -- 交易日 YYYY-MM-DD
    auto_json    TEXT,                      -- 自动采集数据（脚本写入）
    manual_json  TEXT,                      -- 人工复盘数据（表单写入）
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verify_conditions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    written_date  TEXT NOT NULL,            -- 写下条件的日期
    metric        TEXT NOT NULL,            -- 指标（如 炸板率）
    base          TEXT,                     -- 今日基准值
    threshold     TEXT NOT NULL,            -- 阈值（如 >30%）
    if_hit        TEXT,                     -- 触发后动作/含义
    direction     TEXT,                     -- 看多 / 看空 / 中性
    signal_type   TEXT,                     -- 量价 / 连板 / 资金 / 政策 / 其他
    actual        TEXT,                     -- 次日实际值
    auto_result   TEXT DEFAULT 'pending',   -- pending / triggered / not_triggered
    final_result  TEXT,                     -- 人工确认结果 triggered / not_triggered / noise
    override_reason TEXT,                   -- 改判理由
    confirmed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_verify_written ON verify_conditions(written_date);

CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code    TEXT,
    stock_name    TEXT NOT NULL,
    sector        TEXT,                 -- 题材/板块
    open_date     TEXT NOT NULL,        -- 开仓日
    open_price    REAL NOT NULL,        -- 开仓均价
    shares        REAL NOT NULL,        -- 股数
    position_pct  REAL,                 -- 开仓时占总资金 %
    strategy      TEXT,                 -- 打板 / 半路 / 低吸 / 趋势 / 其他
    emotion       TEXT,                 -- 开仓时情绪：冷静 / 犹豫 / 恐踏空 / 恐慌
    open_reason   TEXT,                 -- 买入逻辑
    close_date    TEXT,
    close_price   REAL,
    close_reason  TEXT,                 -- 止盈 / 止损 / 逻辑破坏 / 情绪化卖出 / 其他
    pnl           REAL,                 -- 毛利 (close-open)*shares，平仓时计算
    pnl_pct       REAL,                 -- (close-open)/open*100
    status        TEXT DEFAULT 'open',  -- open / closed
    cycle_phase   TEXT,                 -- 开仓当日的周期阶段（自动从每日复盘带出）
    notes         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);

CREATE TABLE IF NOT EXISTS mood_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT NOT NULL,             -- 交易日 YYYY-MM-DD（由 ts 派生）
    ts            TEXT NOT NULL,             -- 盯盘检查时间 YYYY-MM-DD HH:MM
    emotion       TEXT NOT NULL,            -- 冷静/犹豫/恐踏空/贪婪/恐慌/后悔/兴奋/麻木
    intensity     INTEGER DEFAULT 0,        -- 强度 1-5
    trigger       TEXT,                     -- 触发：大盘拉升/持仓跳水/看到消息…
    urge          TEXT,                     -- 冲动：想买/想加仓/想卖/想割肉/想观望
    position_pct  REAL,                     -- 当时仓位 %
    pnl_pct       REAL,                     -- 当时持仓浮盈浮亏 %
    plan          TEXT,                     -- 原计划动作
    acted         INTEGER DEFAULT 0,        -- 是否按情绪操作了：1=是 0=否
    note          TEXT,                     -- 备注
    created_at    TEXT NOT NULL,
    local_id      TEXT                      -- 手机端 localId（导入去重用，可为空）
);
CREATE INDEX IF NOT EXISTS idx_mood_ts ON mood_log(ts DESC);
"""

# 兼容老库：补加 local_id 列（已存在则忽略报错）
_ALTER_MOOD_LOCALID = "ALTER TABLE mood_log ADD COLUMN local_id TEXT;"


def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # 迁移：老库补截图字段
        cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
        if cols and "shot_min" not in cols:
            conn.execute("ALTER TABLE trades ADD COLUMN shot_min TEXT")   # 分时截图路径
        if cols and "shot_k" not in cols:
            conn.execute("ALTER TABLE trades ADD COLUMN shot_k TEXT")     # 日K截图路径
        if cols and "close_summary" not in cols:
            conn.execute("ALTER TABLE trades ADD COLUMN close_summary TEXT")  # 平仓总结（教训/经验）
        if cols and "close_emotion" not in cols:
            conn.execute("ALTER TABLE trades ADD COLUMN close_emotion TEXT")  # 平仓时心态
        # 迁移：mood_log 补 local_id 列（手机导入去重用）
        mcols = [r[1] for r in conn.execute("PRAGMA table_info(mood_log)").fetchall()]
        if mcols and "local_id" not in mcols:
            conn.execute("ALTER TABLE mood_log ADD COLUMN local_id TEXT")
        # local_id 索引（列刚加完，安全创建）
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mood_local ON mood_log(local_id)")
        except Exception:
            pass


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------- 每日记录 ----------

def upsert_day(date: str, auto: dict | None, manual: dict | None) -> dict:
    """写入/更新某日记录。auto 与 manual 传 None 表示不改动该部分。"""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM daily_records WHERE date=?", (date,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO daily_records(date, auto_json, manual_json, created_at, updated_at) VALUES(?,?,?,?,?)",
                (date, json.dumps(auto, ensure_ascii=False) if auto else None,
                 json.dumps(manual, ensure_ascii=False) if manual else None, now(), now()),
            )
        else:
            new_auto = json.dumps(auto, ensure_ascii=False) if auto is not None else row["auto_json"]
            new_manual = json.dumps(manual, ensure_ascii=False) if manual is not None else row["manual_json"]
            conn.execute(
                "UPDATE daily_records SET auto_json=?, manual_json=?, updated_at=? WHERE date=?",
                (new_auto, new_manual, now(), date),
            )
    return get_day(date)


def _row_to_day(row: sqlite3.Row) -> dict:
    return {
        "date": row["date"],
        "auto": json.loads(row["auto_json"]) if row["auto_json"] else None,
        "manual": json.loads(row["manual_json"]) if row["manual_json"] else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_day(date: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM daily_records WHERE date=?", (date,)).fetchone()
    return _row_to_day(row) if row else None


def list_days(limit: int = 60) -> list[dict]:
    """近 N 条记录摘要（最新在前）。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT date, manual_json, updated_at FROM daily_records
               ORDER BY date DESC LIMIT ?""", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        m = json.loads(r["manual_json"]) if r["manual_json"] else {}
        out.append({
            "date": r["date"],
            "cycle_phase": m.get("cycle_phase"),
            "sentiment": (m.get("sentiment") or {}).get("score"),
            "position": (m.get("position") or {}).get("total"),
            "updated_at": r["updated_at"],
        })
    return out


def delete_day(date: str) -> bool:
    """彻底删除某天的复盘记录（含自动行情数据）。"""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM daily_records WHERE date=?", (date,))
    return cur.rowcount > 0


# ---------- 盯盘情绪记录 ----------

def add_mood(m: dict) -> dict:
    ts = (m.get("ts") or now()[:16]).strip()
    date = ts[:10]
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO mood_log(date, ts, emotion, intensity, trigger, urge,
                   position_pct, pnl_pct, plan, acted, note, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (date, ts, (m.get("emotion") or "").strip(), int(m.get("intensity") or 0),
             (m.get("trigger") or "").strip(), (m.get("urge") or "").strip(),
             m.get("position_pct"), m.get("pnl_pct"), (m.get("plan") or "").strip(),
             1 if m.get("acted") else 0, (m.get("note") or "").strip(), now()),
        )
        mid = cur.lastrowid
    return get_mood(mid)


def get_mood(mid: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM mood_log WHERE id=?", (mid,)).fetchone()
    return dict(row) if row else None


def list_moods(limit: int = 3000) -> list[dict]:
    """全部盯盘情绪记录（时间倒序），前端按日分组与统计。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM mood_log ORDER BY ts DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_mood(mid: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM mood_log WHERE id=?", (mid,))
    return cur.rowcount > 0


def bulk_import_moods(items: list[dict]) -> dict:
    """批量导入手机导出的情绪记录（m.html 导出格式：[{localId, payload}]）。
    按 local_id 去重：已存在相同 local_id 的跳过；返回 {inserted, skipped, total}。
    """
    inserted = 0
    skipped = 0
    with get_conn() as conn:
        existing = set()
        for r in conn.execute("SELECT local_id FROM mood_log WHERE local_id IS NOT NULL").fetchall():
            existing.add(r["local_id"])
        for it in items:
            if not isinstance(it, dict):
                continue
            lid = it.get("localId") or it.get("local_id")
            payload = it.get("payload") or it  # 兼容直接传 payload 的情况
            if lid and lid in existing:
                skipped += 1
                continue
            ts = (payload.get("ts") or now()[:16]).strip()
            date = ts[:10]
            conn.execute(
                """INSERT INTO mood_log(date, ts, emotion, intensity, trigger, urge,
                       position_pct, pnl_pct, plan, acted, note, created_at, local_id)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (date, ts, (payload.get("emotion") or "").strip(), int(payload.get("intensity") or 0),
                 (payload.get("trigger") or "").strip(), (payload.get("urge") or "").strip(),
                 payload.get("position_pct"), payload.get("pnl_pct"), (payload.get("plan") or "").strip(),
                 1 if payload.get("acted") else 0, (payload.get("note") or "").strip(), now(), lid),
            )
            if lid:
                existing.add(lid)
            inserted += 1
    return {"inserted": inserted, "skipped": skipped, "total": inserted + skipped}


def export_moods() -> list[dict]:
    """导出全部情绪记录（含 local_id），供备份 / 迁移。"""
    rows = list_moods(limit=100000)
    for r in rows:
        r.pop("id", None)
    return rows


def prev_trading_date(date: str) -> str | None:
    """库中有记录的上一交易日（用于取昨日验证条件）。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT date FROM daily_records WHERE date<? ORDER BY date DESC LIMIT 1", (date,)
        ).fetchone()
    return row["date"] if row else None


# ---------- 验证条件 ----------

def save_conditions(written_date: str, conditions: list[dict]) -> list[dict]:
    """覆盖式保存某日写下的验证条件（保留已有对账结果的条件除外：简单起见全部重建）。"""
    with get_conn() as conn:
        conn.execute("DELETE FROM verify_conditions WHERE written_date=? AND confirmed_at IS NULL", (written_date,))
        for c in conditions:
            conn.execute(
                """INSERT INTO verify_conditions
                   (written_date, metric, base, threshold, if_hit, direction, signal_type)
                   VALUES(?,?,?,?,?,?,?)""",
                (written_date, c.get("metric", ""), c.get("base", ""), c.get("threshold", ""),
                 c.get("if_hit", ""), c.get("direction", "中性"), c.get("signal_type", "其他")),
            )
    return get_conditions(written_date)


def _row_to_cond(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def get_conditions(written_date: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM verify_conditions WHERE written_date=? ORDER BY id", (written_date,)
        ).fetchall()
    return [_row_to_cond(r) for r in rows]


def check_condition(cond_id: int, actual: str, final_result: str, override_reason: str = "") -> dict | None:
    """记录某条验证条件的对账结果。"""
    with get_conn() as conn:
        conn.execute(
            """UPDATE verify_conditions
               SET actual=?, final_result=?, override_reason=?, confirmed_at=?
               WHERE id=?""",
            (actual, final_result, override_reason, now(), cond_id),
        )
        row = conn.execute("SELECT * FROM verify_conditions WHERE id=?", (cond_id,)).fetchone()
    return _row_to_cond(row) if row else None


# ---------- 交易记录（回合制：开仓 → 平仓） ----------

def _cycle_phase_of(date: str) -> str | None:
    """取某日复盘中的周期阶段（无记录返回 None）。"""
    with get_conn() as conn:
        row = conn.execute("SELECT manual_json FROM daily_records WHERE date=?", (date,)).fetchone()
    if row and row["manual_json"]:
        m = json.loads(row["manual_json"])
        return m.get("cycle_phase")
    return None


def add_trade(t: dict) -> dict:
    cols = ["stock_code", "stock_name", "sector", "open_date", "open_price", "shares",
            "position_pct", "strategy", "emotion", "open_reason", "notes"]
    vals = [t.get(c) for c in cols]
    with get_conn() as conn:
        cur = conn.execute(
            f"""INSERT INTO trades({", ".join(cols)}, cycle_phase, status, created_at, updated_at)
                VALUES({", ".join("?" * len(cols))}, ?, 'open', ?, ?)""",
            (*vals, _cycle_phase_of(t["open_date"]), now(), now()),
        )
        tid = cur.lastrowid
    return get_trade(tid)


def _row_to_trade(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def get_trade(tid: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
    return _row_to_trade(row) if row else None


def list_trades(status: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if status in ("open", "closed"):
            rows = conn.execute("SELECT * FROM trades WHERE status=? ORDER BY open_date DESC, id DESC", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM trades ORDER BY open_date DESC, id DESC").fetchall()
    return [_row_to_trade(r) for r in rows]


def close_trade(tid: int, close_date: str, close_price: float, close_reason: str = "",
                close_summary: str = "", close_emotion: str = "") -> dict | None:
    t = get_trade(tid)
    if t is None or t["status"] == "closed":
        return t
    pnl = round((close_price - t["open_price"]) * t["shares"], 2)
    pnl_pct = round((close_price - t["open_price"]) / t["open_price"] * 100, 2)
    with get_conn() as conn:
        conn.execute(
            """UPDATE trades SET close_date=?, close_price=?, close_reason=?,
               close_summary=?, close_emotion=?,
               pnl=?, pnl_pct=?, status='closed', updated_at=? WHERE id=?""",
            (close_date, close_price, close_reason, close_summary, close_emotion,
             pnl, pnl_pct, now(), tid),
        )
    return get_trade(tid)


def reopen_trade(tid: int) -> dict | None:
    """撤销平仓（填错重填用）。"""
    with get_conn() as conn:
        conn.execute(
            """UPDATE trades SET close_date=NULL, close_price=NULL, close_reason=NULL,
               close_summary=NULL, close_emotion=NULL,
               pnl=NULL, pnl_pct=NULL, status='open', updated_at=? WHERE id=?""",
            (now(), tid),
        )
    return get_trade(tid)


def delete_trade(tid: int) -> bool:
    t = get_trade(tid)
    if t is None:
        return False
    # 同步删除关联截图文件，避免磁盘残留
    shots_dir = Path(__file__).parent / "data" / "shots"
    for f in (t.get("shot_min"), t.get("shot_k")):
        if f:
            try:
                (shots_dir / Path(f).name).unlink(missing_ok=True)
            except OSError:
                pass
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM trades WHERE id=?", (tid,))
    return cur.rowcount > 0


def set_trade_shot(tid: int, kind: str, path: str | None) -> dict | None:
    """设置/删除某笔交易的截图。kind: min=分时, k=日K。path=None 表示删除。"""
    col = {"min": "shot_min", "k": "shot_k"}.get(kind)
    if col is None:
        return None
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE trades SET {col}=?, updated_at=? WHERE id=?", (path, now(), tid))
        if cur.rowcount == 0:
            return None
    return get_trade(tid)


def sync_trade_cycles() -> int:
    """每日复盘补填/修改周期定位后，重算所有持仓中交易对应的周期阶段。"""
    n = 0
    with get_conn() as conn:
        rows = conn.execute("SELECT id, open_date FROM trades WHERE status='open'").fetchall()
        for r in rows:
            phase = _cycle_phase_of(r["open_date"])
            if phase:
                conn.execute("UPDATE trades SET cycle_phase=? WHERE id=?", (phase, r["id"]))
                n += 1
    return n


# ---------- 胜率统计 ----------

def _bucket_hold_days(d1: str, d2: str) -> str:
    try:
        days = (datetime.strptime(d2, "%Y-%m-%d") - datetime.strptime(d1, "%Y-%m-%d")).days
    except Exception:
        return "未知"
    if days <= 0:
        return "当日"
    if days <= 3:
        return "1-3天"
    if days <= 7:
        return "4-7天"
    if days <= 15:
        return "8-15天"
    return ">15天"


def _group_stats(closed: list[dict], key_fn) -> list[dict]:
    groups: dict[str, list] = {}
    for t in closed:
        k = key_fn(t) or "未填"
        groups.setdefault(k, []).append(t)
    out = []
    for k, ts in groups.items():
        wins = [t for t in ts if t["pnl"] > 0]
        win_pnls = [t["pnl"] for t in wins]
        loss_pnls = [abs(t["pnl"]) for t in ts if t["pnl"] <= 0]
        out.append({
            "group": k, "count": len(ts),
            "win_count": len(wins),
            "win_rate": round(len(wins) / len(ts) * 100, 1),
            "total_pnl": round(sum(t["pnl"] for t in ts), 0),
            "avg_pnl_pct": round(sum(t["pnl_pct"] for t in ts) / len(ts), 2),
            "avg_win": round(sum(win_pnls) / len(win_pnls), 0) if win_pnls else 0,
            "avg_loss": round(sum(loss_pnls) / len(loss_pnls), 0) if loss_pnls else 0,
        })
    return sorted(out, key=lambda x: -x["total_pnl"])


def trade_stats() -> dict:
    closed = [t for t in list_trades("closed") if t["pnl"] is not None]
    closed = sorted(closed, key=lambda t: t["close_date"] or t["open_date"])
    overall = {"count": 0}
    if closed:
        wins = [t for t in closed if t["pnl"] > 0]
        win_pnls = [t["pnl"] for t in wins]
        loss_pnls = [abs(t["pnl"]) for t in closed if t["pnl"] <= 0]
        # 最大连亏 / 连盈
        max_loss_streak = max_win_streak = cl = cw = 0
        for t in closed:
            if t["pnl"] <= 0:
                cl += 1; cw = 0
            else:
                cw += 1; cl = 0
            max_loss_streak = max(max_loss_streak, cl)
            max_win_streak = max(max_win_streak, cw)
        avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0
        avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0
        overall = {
            "count": len(closed),
            "win_count": len(wins),
            "win_rate": round(len(wins) / len(closed) * 100, 1),
            "total_pnl": round(sum(t["pnl"] for t in closed), 0),
            "avg_pnl_pct": round(sum(t["pnl_pct"] for t in closed) / len(closed), 2),
            "avg_win": round(avg_win, 0),
            "avg_loss": round(avg_loss, 0),
            "profit_ratio": round(avg_win / avg_loss, 2) if avg_loss else None,  # 盈亏比
            "expectancy": round(sum(t["pnl"] for t in closed) / len(closed), 0),  # 单笔期望
            "max_loss_streak": max_loss_streak,
            "max_win_streak": max_win_streak,
            "best": max(closed, key=lambda t: t["pnl"]),
            "worst": min(closed, key=lambda t: t["pnl"]),
        }
    # 月度
    monthly: dict[str, dict] = {}
    for t in closed:
        m = (t["close_date"] or t["open_date"])[:7]
        d = monthly.setdefault(m, {"count": 0, "win_count": 0, "pnl": 0.0})
        d["count"] += 1
        d["win_count"] += 1 if t["pnl"] > 0 else 0
        d["pnl"] += t["pnl"]
    return {
        "overall": overall,
        "open_count": len(list_trades("open")),
        "by_strategy": _group_stats(closed, lambda t: t["strategy"]),
        "by_sector": _group_stats(closed, lambda t: t["sector"]),
        "by_cycle": _group_stats(closed, lambda t: t["cycle_phase"]),
        "by_emotion": _group_stats(closed, lambda t: t["emotion"]),
        "by_close_emotion": _group_stats(closed, lambda t: t.get("close_emotion")),
        "by_hold": _group_stats(closed, lambda t: _bucket_hold_days(t["open_date"], t["close_date"] or t["open_date"])),
        "by_close_reason": _group_stats(closed, lambda t: t["close_reason"]),
        "monthly": [{"month": m, **{k: (round(v, 0) if k == "pnl" else v) for k, v in d.items()}}
                    for m, d in sorted(monthly.items(), reverse=True)],
    }


init_db()
