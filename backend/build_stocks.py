#!/usr/bin/env python3
# 一次性构建：拉取全量 A 股代码表，计算拼音首字母，写入 data/stocks.json
# 运行时前端直接读取该 JSON 做联想，无需联网。
# 用法：python build_stocks.py   （venv 内）
import os
import json
import akshare as ak
from pypinyin import pinyin, Style


def initials(name: str) -> str:
    """取中文名的拼音首字母（大写），忽略非 ASCII 字母字符（如全角Ａ）。"""
    try:
        res = pinyin(name, style=Style.FIRST_LETTER, heteronym=False)
    except Exception:
        return ""
    out = []
    for item in res:
        ch = item[0] if item else ""
        if ch and ch.isascii() and ch.isalpha():
            out.append(ch.upper())
    return "".join(out)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(here, "data", "stocks.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    print("拉取 A 股代码表 ...")
    df = ak.stock_info_a_code_name()
    print(f"共 {len(df)} 行")

    stocks = []
    for _, row in df.iterrows():
        code = str(row["code"]).strip().zfill(6)
        name = str(row["name"]).strip()
        if not code or not name:
            continue
        stocks.append({"code": code, "name": name, "initials": initials(name)})

    # 按代码排序，便于调试
    stocks.sort(key=lambda s: s["code"])
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(stocks, f, ensure_ascii=False)
    print(f"已写入 {len(stocks)} 只 -> {out_path}")


if __name__ == "__main__":
    main()
