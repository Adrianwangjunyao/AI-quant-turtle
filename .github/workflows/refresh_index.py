"""
GitHub Actions 数据刷新脚本
读取 tushare 最新行情 → 重建 index.html（含嵌入式行情数据）
"""
import os, json, base64

TOKEN = os.environ.get("TUSHARE_TOKEN", "")
if not TOKEN:
    raise ValueError("请设置 TUSHARE_TOKEN Secrets")

import tushare as ts
ts.set_token(TOKEN)
pro = ts.pro_api()

STOCKS = {
    "兆易创新": "603986.SH",
    "贵州茅台": "600519.SH",
    "中国平安": "601318.SH",
    "宁德时代": "300750.SZ",
    "隆基绿能": "601012.SH",
}

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(DATA_DIR, "..", "..")
INDEX_PATH = os.path.join(PROJECT_ROOT, "index.html")


def fetch_stock_data(ts_code: str, name: str) -> list:
    """
    从 tushare 获取日线行情，返回 [{date, open, high, low, close, vol}] 格式
    """
    # 获取复权因子
    adj = pro.adj_factor(ts_code=ts_code, start_date="20200101", end_date="20260731")
    if adj.empty:
        print(f"  ⚠️ {name} 未获取到复权因子")
        return []

    df = pro.daily(
        ts_code=ts_code,
        start_date="20200101",
        end_date="20260731",
        fields="trade_date,open,high,low,close,vol",
    )
    if df.empty:
        print(f"  ⚠️ {name} 未获取到行情数据")
        return []

    df = df.sort_values("trade_date").reset_index(drop=True)

    # 合并复权因子并计算前复权价格
    adj = adj[["trade_date", "adj_factor"]]
    adj["trade_date"] = adj["trade_date"].astype(str)
    df["trade_date"] = df["trade_date"].astype(str)
    df = df.merge(adj, on="trade_date", how="left")
    last_adj = df["adj_factor"].iloc[-1]
    for col in ["open", "high", "low", "close"]:
        df[col] = (df[col] * df["adj_factor"] / last_adj).round(2)

    rows = []
    for _, r in df.iterrows():
        rows.append([
            r["trade_date"],
            float(r["open"]),
            float(r["high"]),
            float(r["low"]),
            float(r["close"]),
            int(r["vol"]),
        ])
    print(f"  ✅ {name} ({ts_code}): {len(rows)} 行")
    return rows


def build_stock_data_js(data: dict) -> str:
    """构建 JS 赋值语句"""
    js = "var STOCK_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n"
    return js


def main():
    print("=" * 50)
    print("海龟策略看板 — 行情数据刷新")
    print("=" * 50)

    all_data = {}
    for name, code in STOCKS.items():
        rows = fetch_stock_data(code, name)
        if rows:
            all_data[name] = rows

    if not all_data:
        print("❌ 未获取到任何有效数据，跳过更新")
        return

    # 读取当前的 index.html
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # 替换 STOCK_DATA 部分
    new_data_js = build_stock_data_js(all_data)
    import re
    # 找 var STOCK_DATA = {...} 或 var STOCK_DATA =  {...};
    pattern = r"var STOCK_DATA\s*=\s*\{[\s\S]*?\};"
    if re.search(pattern, html):
        html = re.sub(pattern, new_data_js.strip().rstrip(";"), html)
    else:
        print("❌ 未在 index.html 中找到 STOCK_DATA，请在文件中确认格式")
        return

    # 写回
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ index.html 已更新 ({sum(len(v) for v in all_data.values())} 条记录)")
    print(f"   涉及 {len(all_data)} 只股票")


if __name__ == "__main__":
    main()
