"""最简数据采集脚本 — 5 类核心指标写入 daily_records 的 auto 字段。

指标口径（参考 vibe-astock：纯计算直出，不经过 AI）：
  1. 涨停家数        涨停池行数
  2. 连板高度/梯队   涨停池"连板数"列 → 最高板 + 各板家人数
  3. 炸板率          炸板池 / (涨停池 + 炸板池)
  4. 成交额          上证指数 + 深证综指 成交额之和（亿元）
  5. 板块前5         东财行业板块按当日涨跌幅排名前5

用法：
    python collector.py                    # 采集今日（非交易日会得到空数据）
    python collector.py --date 2026-08-21  # 指定日期
    python collector.py --mock             # 无网络时生成模拟数据（前端联调用）

单个指标失败不影响其他指标，错误记录在 meta.errors 里。
"""
import argparse
import datetime as dt
import json

import db


def _d8(date: str) -> str:
    return date.replace("-", "")


def _pct(a: float, b: float) -> float:
    return round((a - b) / b * 100, 2) if b else None


# ---------- 各指标采集（每个独立容错） ----------

def fetch_zt_and_zb(date8: str) -> dict:
    """涨停池 + 炸板池 → 涨停数 / 连板梯队 / 炸板数 / 炸板率。"""
    import akshare as ak

    zt = ak.stock_zt_pool_em(date=date8)
    zb = ak.stock_zt_pool_zbgc_em(date=date8)
    zt_count = len(zt)
    zb_count = len(zb)
    out = {"zt_count": zt_count, "zb_count": zb_count}
    if zb_count + zt_count > 0:
        out["zb_rate"] = round(zb_count / (zt_count + zb_count) * 100, 1)
    else:
        out["zb_rate"] = None
    if zt_count and "连板数" in zt.columns:
        lb = zt["连板数"].astype(int)
        out["lb_max"] = int(lb.max())
        ladder = {}
        for n in sorted(lb.unique()):
            if n >= 2:
                ladder[f"{n}板"] = int((lb == n).sum())
        out["lb_ladder"] = ladder
    return out


def fetch_amount_and_index(date8: str) -> dict:
    """指数收盘/涨跌幅 + 全市场成交额（亿元）。东财 → 新浪/同花顺 兜底。"""
    import akshare as ak

    out = {}
    # 指数：东财日线 → 新浪日线兜底（新浪无成交额，只有价格）
    for daily in (
        lambda: ak.stock_zh_index_daily_em(symbol="sh000001"),
        lambda: ak.stock_zh_index_daily(symbol="sh000001"),
    ):
        try:
            sh = daily()
            if len(sh) >= 2:
                last, prev = sh.iloc[-1], sh.iloc[-2]
                out["index"] = {
                    "name": "上证指数",
                    "close": round(float(last["close"]), 2),
                    "chg_pct": _pct(float(last["close"]), float(prev["close"])),
                }
            if "amount" in sh.columns:
                out["amount_yi"] = round(float(sh.iloc[-1]["amount"]) / 1e8, 0)
            break
        except Exception:
            continue
    return out


def fetch_ths_boards() -> "tuple[dict, list] | None":
    """同花顺行业板块汇总 → (成交额+涨跌家数, 板块前5)。作为东财板块接口的兜底。"""
    import akshare as ak

    df = ak.stock_board_industry_summary_ths()
    df = df.sort_values("涨跌幅", ascending=False)
    total = {
        "amount_yi": round(float(df["总成交额"].astype(float).sum()), 0),  # 该列单位已是亿元
        "up_count": int(df["上涨家数"].astype(int).sum()),
        "down_count": int(df["下跌家数"].astype(int).sum()),
    }
    top5 = [
        {"name": r["板块"], "pct": round(float(r["涨跌幅"]), 2)}
        for _, r in df.head(5).iterrows()
    ]
    return total, top5


def fetch_sectors(total: dict) -> list:
    """板块涨幅前5：东财行业板块 → 同花顺兜底（兜底时顺带补成交额/涨跌家数）。"""
    import akshare as ak

    try:
        df = ak.stock_board_industry_name_em()
        df = df.sort_values("涨跌幅", ascending=False).head(5)
        return [
            {"name": r["板块名称"], "pct": round(float(r["涨跌幅"]), 2)}
            for _, r in df.iterrows()
        ]
    except Exception:
        result = fetch_ths_boards()
        if result is None:
            raise
        ths_total, top5 = result
        total.update(ths_total)
        return top5


# ---------- 汇总 ----------

def collect(date: str, mock: bool = False, write: bool = True) -> dict:
    auto = {
        "date": date,
        "zt_count": None, "lb_max": None, "lb_ladder": None,
        "zb_count": None, "zb_rate": None,
        "amount_yi": None, "index": None, "sectors_top5": None,
        "up_count": None, "down_count": None,
        "meta": {"collected_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "source": "mock" if mock else "akshare", "errors": {}},
    }

    if mock:
        auto.update({
            "zt_count": 58, "zb_count": 12, "zb_rate": 17.1,
            "lb_max": 5, "lb_ladder": {"2板": 21, "3板": 8, "4板": 3, "5板": 1},
            "amount_yi": 16832,
            "index": {"name": "上证指数", "close": 3245.67, "chg_pct": 0.82},
            "sectors_top5": [
                {"name": "半导体", "pct": 3.42}, {"name": "算力租赁", "pct": 2.87},
                {"name": "消费电子", "pct": 2.15}, {"name": "券商", "pct": 1.63},
                {"name": "军工电子", "pct": 1.28},
            ],
            "up_count": 3205, "down_count": 1680,
        })
    else:
        date8 = _d8(date)
        extra_total: dict = {}
        for key, fn in [
            ("zt_zb", lambda: fetch_zt_and_zb(date8)),
            ("amount_index", lambda: fetch_amount_and_index(date8)),
            ("sectors", lambda: fetch_sectors(extra_total)),
        ]:
            try:
                data = fn()
                if key == "sectors":
                    auto["sectors_top5"] = data
                    auto.update(extra_total)   # 同花顺兜底时补的成交额/涨跌家数
                else:
                    auto.update(data)
            except Exception as e:
                auto["meta"]["errors"][key] = f"{type(e).__name__}: {e}"

    if write:
        db.upsert_day(date, auto, None)
    return auto


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A股复盘 · 最简数据采集")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--mock", action="store_true", help="生成模拟数据（无网络联调用）")
    parser.add_argument("--dry", action="store_true", help="只打印不写库")
    args = parser.parse_args()

    result = collect(args.date, mock=args.mock, write=not args.dry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
