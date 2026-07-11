"""
GitHub Actions 数据刷新脚本
读取 tushare 最新行情 → 重建 index.html（含嵌入式行情数据）
"""
import os, sys, json, re, time

TOKEN = os.environ.get("TUSHARE_TOKEN", "")
if not TOKEN:
    print("❌ TUSHARE_TOKEN 环境变量未设置")
    sys.exit(1)

print(f"✅ TUSHARE_TOKEN 已读取 (前8位: {TOKEN[:8]}...)")

# 项目根目录 = 脚本位置向上2层 (.github/workflows/ → 项目根)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
INDEX_PATH = os.path.join(PROJECT_ROOT, "index.html")
print(f"📁 项目根目录: {PROJECT_ROOT}")
print(f"📄 index.html: {INDEX_PATH}")
print(f"📂 index.html 是否存在: {os.path.exists(INDEX_PATH)}")

# 先安装 tushare
print("\n📦 安装 tushare...")
os.system(f"{sys.executable} -m pip install tushare pandas numpy -q")
print("✅ 安装完成")

# 延迟导入 (确保 tushare 已安装)
try:
    import tushare as ts
    ts.set_token(TOKEN)
    pro = ts.pro_api()
    print(f"✅ tushare 版本: {ts.__version__}")
except Exception as e:
    print(f"❌ tushare 导入失败: {e}")
    sys.exit(1)

STOCKS = {
    "兆易创新": "603986.SH",
    "贵州茅台": "600519.SH",
    "中国平安": "601318.SH",
    "宁德时代": "300750.SZ",
    "隆基绿能": "601012.SH",
}

# 一次性获取所有股票的复权因子（tushare adj_factor 限制 1次/分钟）
ADJ_FACTOR_MAP = {}
try:
    all_codes = ",".join(STOCKS.values())
    print(f"📦 批量获取复权因子: {all_codes}")
    adj_df = pro.adj_factor(ts_code=all_codes, start_date="20200101", end_date="20260731")
    if adj_df is not None and not adj_df.empty:
        adj_df["trade_date"] = adj_df["trade_date"].astype(str)
        for code in STOCKS.values():
            sub = adj_df[adj_df["ts_code"] == code].copy()
            if not sub.empty:
                sub = sub.sort_values("trade_date").reset_index(drop=True)
                ADJ_FACTOR_MAP[code] = sub[["trade_date", "adj_factor"]]
        print(f"  ✅ 获取到 {len(ADJ_FACTOR_MAP)} 只股票的复权因子")
    else:
        print("  ⚠️ 复权因子返回为空")
except Exception as e:
    print(f"  ❌ 批量获取复权因子失败: {e}")


def fetch_stock(ts_code: str, name: str) -> list:
    """获取单只股票的前复权日线数据"""
    try:
        df = pro.daily(
            ts_code=ts_code,
            start_date="20200101",
            end_date="20260731",
            fields="trade_date,open,high,low,close,vol",
        )
        if df is None or df.empty:
            print(f"  ⚠️ {name} ({ts_code}): 无数据")
            return []

        df = df.sort_values("trade_date").reset_index(drop=True)
        df["trade_date"] = df["trade_date"].astype(str)

        # 合并预获取的复权因子
        if ts_code in ADJ_FACTOR_MAP:
            adj = ADJ_FACTOR_MAP[ts_code]
            df = df.merge(adj[["trade_date", "adj_factor"]], on="trade_date", how="left")
            df["adj_factor"] = df["adj_factor"].ffill()
            if df["adj_factor"].notna().any():
                last_adj = df["adj_factor"].dropna().iloc[-1]
                for col in ["open", "high", "low", "close"]:
                    df[col] = (df[col] * df["adj_factor"] / last_adj).round(2)
        else:
            print(f"  ⚠️ {name} ({ts_code}): 无复权因子")

        rows = []
        for _, r in df.iterrows():
            rows.append([
                r["trade_date"],
                float(round(r["open"], 2)),
                float(round(r["high"], 2)),
                float(round(r["low"], 2)),
                float(round(r["close"], 2)),
                int(r["vol"]),
            ])
        print(f"  ✅ {name} ({ts_code}): {len(rows)} 条记录")
        return rows
    except Exception as e:
        print(f"  ❌ {name} ({ts_code}): {e}")
        return []


def main():
    print("=" * 50)
    print("🐢 海龟策略看板 — 行情数据刷新")
    print("=" * 50)

    # 获取所有股票数据
    all_data = {}
    for name, code in STOCKS.items():
        rows = fetch_stock(code, name)
        if rows:
            all_data[name] = rows
        else:
            # 如果拿不到实时数据，保留旧数据（不覆盖）
            print(f"  ℹ️ {name}: 将保留旧数据")

    if not all_data:
        print("❌ 未获取到任何数据，跳过更新")
        sys.exit(1)

    # 构建新的 JS 数据
    new_js = "var STOCK_DATA = " + json.dumps(all_data, ensure_ascii=False) + ";\n"

    # 读取 index.html
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # 替换 STOCK_DATA 部分
    pattern = r'var STOCK_DATA\s*=\s*\{[\s\S]*?\};'
    match = re.search(pattern, html)
    if not match:
        # 尝试另一种格式（带空格和换行）
        pattern = r'var STOCK_DATA\s*=\s*\{[\s\S]*?\}\s*;'
        match = re.search(pattern, html)

    if match:
        html = html.replace(match.group(0), new_js.strip().rstrip(";"))
        with open(INDEX_PATH, "w", encoding="utf-8") as f:
            f.write(html)
        total = sum(len(v) for v in all_data.values())
        print(f"\n✅ index.html 已更新 ({total} 条记录, {len(all_data)} 只股票)")
    else:
        print("❌ 无法在 index.html 中找到 STOCK_DATA 变量定义")
        print("   请检查 index.html 中数据格式是否为: var STOCK_DATA = {...};")
        sys.exit(1)


if __name__ == "__main__":
    main()
