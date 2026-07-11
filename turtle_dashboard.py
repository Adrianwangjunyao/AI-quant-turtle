"""
海龟策略回测看板 — Flask 后端
================================
提供参数接收、回测计算、JSON 数据返回的 API。
"""
import sys, os, json
from flask import Flask, request, jsonify, render_template

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from turtle_strategy import TurtleStrategy
from turtle_backtest import TurtleBacktestEngine, PerformanceAnalyzer

app = Flask(__name__)

# 股票数据路径
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Task-3")
STOCK_FILES = {
    "兆易创新": "兆易创新_daily.csv",
    "贵州茅台": "贵州茅台_daily.csv",
    "中国平安": "中国平安_daily.csv",
    "宁德时代": "宁德时代_daily.csv",
    "隆基绿能": "隆基绿能_daily.csv",
}


def run_backtest(params: dict) -> dict:
    """执行回测并返回结果"""
    import pandas as pd
    import numpy as np

    stock_name = params.get("stock", "宁德时代")
    csv_path = os.path.join(DATA_DIR, STOCK_FILES[stock_name])
    df = pd.read_csv(csv_path)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date").reset_index(drop=True)

    # 时间过滤
    start_date = params.get("start_date", "2022-01-01")
    end_date = params.get("end_date", "2026-07-31")
    df = df[(df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)]
    if len(df) < 60:
        return {"error": "数据不足，请扩大时间范围"}

    # 策略参数
    system = params.get("system", "S1")
    entry_w = int(params.get("entry_window", 20))
    exit_w = int(params.get("exit_window", 10))
    atr_p = int(params.get("atr_period", 20))
    risk_p = float(params.get("risk_pct", 0.01))
    max_u = int(params.get("max_units", 4))
    step = float(params.get("add_step", 0.5))
    init_cap = float(params.get("initial_capital", 1_000_000))

    strategy = TurtleStrategy(
        system=system, entry_window=entry_w, exit_window=exit_w,
        atr_period=atr_p, risk_pct=risk_p, max_units=max_u, add_unit_step=step,
    )
    engine = TurtleBacktestEngine(
        initial_capital=init_cap, commission_rate=0.0003,
        slippage=0.0001, stamp_duty=0.001, risk_pct=risk_p,
    )
    trades, equity, units = engine.run(strategy, df)
    analyzer = PerformanceAnalyzer(equity, trades, init_cap)
    metrics = analyzer.summary()

    # ── 准备前端图表数据 ──
    dates = df["trade_date"].dt.strftime("%Y-%m-%d").tolist()
    close = df["close"].round(2).tolist()
    n_value_col = df["n_value"].where(df["n_value"].notna(), None).tolist()
    ch_high = df["channel_high"].where(df["channel_high"].notna(), None).tolist()
    ch_low = df["channel_low"].where(df["channel_low"].notna(), None).tolist()

    eq_dates = equity["date"].dt.strftime("%Y-%m-%d").tolist()
    eq_values = equity["equity"].round(2).tolist()
    buyhold = (df["close"] / df["close"].iloc[0] * init_cap).round(2).tolist()

    # 买入/卖出信号点
    buy_signals, sell_signals = [], []
    if not trades.empty:
        for _, t in trades.iterrows():
            entry_d = t["entry_date"]
            if hasattr(entry_d, "strftime"):
                entry_d = entry_d.strftime("%Y-%m-%d")
            exit_d = t["exit_date"]
            if hasattr(exit_d, "strftime"):
                exit_d = exit_d.strftime("%Y-%m-%d")
            if entry_d in dates:
                idx = dates.index(entry_d)
                buy_signals.append({"date": entry_d, "price": round(float(t["entry_price"]), 2)})
            if exit_d in dates:
                idx = dates.index(exit_d)
                sell_signals.append({"date": exit_d, "price": round(float(t["exit_price"]), 2)})

    # 止损信号
    stop_signals = []
    if not trades.empty:
        stop_trades = trades[trades["reason"] == "stop_loss"]
        for _, t in stop_trades.iterrows():
            ed = t["exit_date"]
            if hasattr(ed, "strftime"):
                ed = ed.strftime("%Y-%m-%d")
            stop_signals.append({"date": ed, "price": round(float(t["exit_price"]), 2)})

    # 持仓单位
    active_units = equity["active_units"].tolist()

    # 交易记录
    trade_records = []
    if not trades.empty:
        for _, t in trades.iterrows():
            ed = t["entry_date"]
            xd = t["exit_date"]
            if hasattr(ed, "strftime"):
                ed = ed.strftime("%Y-%m-%d")
            if hasattr(xd, "strftime"):
                xd = xd.strftime("%Y-%m-%d")
            trade_records.append({
                "entry_date": ed,
                "entry_price": round(float(t["entry_price"]), 2),
                "exit_date": xd,
                "exit_price": round(float(t["exit_price"]), 2),
                "shares": int(t["shares"]),
                "pnl": round(float(t["pnl"]), 2),
                "pnl_pct": round(float(t["pnl_pct"]), 2),
                "reason": t["reason"],
            })

    avg_units = round(equity["active_units"].mean(), 2)

    chart_data = {
        "dates": dates,
        "close": close,
        "n_value": n_value_col,
        "channel_high": ch_high,
        "channel_low": ch_low,
        "equity": {"dates": eq_dates, "values": eq_values},
        "buyhold": buyhold,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "stop_signals": stop_signals,
        "active_units": active_units,
        "trade_records": trade_records,
    }

    return {
        "metrics": metrics,
        "avg_units": avg_units,
        "chart_data": chart_data,
        "trades_count": len(trades),
    }


@app.route("/")
def index():
    return render_template("turtle_dashboard.html", stocks=list(STOCK_FILES.keys()))


@app.route("/api/run", methods=["POST"])
def api_run():
    params = request.json
    result = run_backtest(params)
    if "error" in result:
        return jsonify({"error": result["error"]}), 400
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
