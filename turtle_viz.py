"""
海龟策略可视化模块 (Turtle Visualization)
=============================================
提供 4 张核心图表:
    1. 股价 + 唐奇安通道 + 交易信号
    2. N值(ATR)波动率曲线
    3. 持仓单位数量变化
    4. 资金权益曲线 vs 买入持有基准
    5. Wilder ATR 走势 (TR + ATR + 百分位分析)

颜色约定 (中国股市):
    涨/买入: 红色
    跌/卖出: 绿色
    通道上轨: 蓝色 (虚线)
    通道下轨: 蓝色 (虚线)
    通道带填充: 浅蓝色半透明
    权益曲线: 深红色
    基准曲线: 灰色
"""

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import pandas as pd
import numpy as np
from typing import Optional

# ── 中文字体设置 ─────────────────────────────────
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "WenQuanYi Micro Hei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False


def plot_price_channels_signals(
    df: pd.DataFrame,
    trades_df: pd.DataFrame,
    title: str = "海龟策略 — 价格通道与交易信号",
    figsize=(14, 7),
) -> plt.Figure:
    """
    图1: 股价 + 唐奇安通道 + 买卖信号

    参数:
        df: 行情数据 (含 close, channel_high, channel_low, n_value)
        trades_df: 交易记录 (含 entry_date, exit_date, entry_price, exit_price, reason)
        title: 图表标题
    """
    fig, ax = plt.subplots(figsize=figsize)

    # 将日期转为 matplotlib 可识别的格式
    dates = pd.to_datetime(df["trade_date"])

    # ── 绘制收盘价折线 ──
    ax.plot(dates, df["close"], color="#A32D2D", linewidth=1.5, alpha=0.8, label="收盘价")

    # ── 绘制唐奇安通道 ──
    if "channel_high" in df.columns and "channel_low" in df.columns:
        ax.plot(
            dates, df["channel_high"], color="#185FA5", linewidth=1,
            linestyle="--", alpha=0.7, label=f"通道上轨"
        )
        ax.plot(
            dates, df["channel_low"], color="#185FA5", linewidth=1,
            linestyle="--", alpha=0.7, label=f"通道下轨"
        )
        # 通道带填充
        ax.fill_between(
            dates, df["channel_high"], df["channel_low"],
            alpha=0.08, color="#185FA5", label="通道带"
        )

    # ── 标记买入信号 (入场 + 加仓) ──
    if not trades_df.empty:
        # 入场 (首次买入)
        first_entry = trades_df.groupby("entry_date").first().reset_index()
        entry_dates = pd.to_datetime(first_entry["entry_date"])
        entry_prices = first_entry["entry_price"]
        ax.scatter(
            entry_dates, entry_prices,
            color="#A32D2D", marker="^", s=120, zorder=5,
            label="入场买入", edgecolors="white", linewidth=0.5
        )

        # 加仓 (非首次且reason不是止损退出)
        add_trades = trades_df[
            trades_df["entry_date"].duplicated(keep=False)
        ]
        if not add_trades.empty:
            add_dates = pd.to_datetime(add_trades["entry_date"])
            add_prices = add_trades["entry_price"]
            ax.scatter(
                add_dates, add_prices,
                color="#D85A30", marker="^", s=80, zorder=5,
                label="加仓", edgecolors="white", linewidth=0.5, alpha=0.8
            )

        # 标记退出信号
        exit_dates = pd.to_datetime(trades_df["exit_date"])
        exit_prices = trades_df["exit_price"]

        # 止损退出 - 绿色倒三角
        stop_loss = trades_df[trades_df["reason"] == "stop_loss"]
        if not stop_loss.empty:
            sl_dates = pd.to_datetime(stop_loss["exit_date"])
            sl_prices = stop_loss["exit_price"]
            ax.scatter(
                sl_dates, sl_prices,
                color="#3B6D11", marker="v", s=100, zorder=5,
                label="止损", edgecolors="white", linewidth=0.5
            )

        # 趋势退出 - 绿色叉号
        trend_exit = trades_df[trades_df["reason"] == "trend_exit"]
        if not trend_exit.empty:
            te_dates = pd.to_datetime(trend_exit["exit_date"])
            te_prices = trend_exit["exit_price"]
            ax.scatter(
                te_dates, te_prices,
                color="#1D9E75", marker="x", s=100, zorder=5,
                label="趋势退出", linewidth=2
            )

    # ── 格式设置 ──
    ax.set_title(title, fontsize=14, fontweight="bold", pad=15)
    ax.set_xlabel("日期", fontsize=12)
    ax.set_ylabel("价格 (元)", fontsize=12)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=10, framealpha=0.9)
    fig.tight_layout()

    return fig


def plot_n_value_analysis(
    df: pd.DataFrame,
    equity_df: pd.DataFrame,
    title: str = "海龟策略 — N值(ATR)与持仓分析",
    figsize=(14, 6),
) -> plt.Figure:
    """
    图2: N值(ATR)波动率曲线 + 持仓单位数叠加

    参数:
        df: 行情数据 (含 n_value)
        equity_df: 权益曲线 (含 active_units)
    """
    fig, ax1 = plt.subplots(figsize=figsize)

    dates = pd.to_datetime(df["trade_date"])

    # ── 左轴: N 值 ──
    if "n_value" in df.columns:
        n_valid = df["n_value"].notna()
        ax1.plot(
            dates[n_valid], df.loc[n_valid, "n_value"],
            color="#185FA5", linewidth=1.5, alpha=0.8, label="N 值 (ATR)"
        )
        ax1.fill_between(
            dates[n_valid], df.loc[n_valid, "n_value"],
            alpha=0.1, color="#185FA5"
        )

    ax1.set_ylabel("N 值 (元)", fontsize=12, color="#185FA5")
    ax1.tick_params(axis="y", labelcolor="#185FA5")

    # ── 右轴: 持仓单位数 ──
    ax2 = ax1.twinx()
    if "active_units" in equity_df.columns:
        eq_dates = pd.to_datetime(equity_df["date"])
        ax2.fill_between(
            eq_dates, equity_df["active_units"],
            alpha=0.25, color="#D85A30", step="mid",
            label="持仓单位数"
        )
        ax2.step(
            eq_dates, equity_df["active_units"],
            color="#D85A30", linewidth=1.5, where="mid",
            label="持仓单位数"
        )

    ax2.set_ylabel("持仓单位数", fontsize=12, color="#D85A30")
    ax2.tick_params(axis="y", labelcolor="#D85A30")
    ax2.set_ylim(bottom=0)

    # ── 格式 ──
    ax1.set_title(title, fontsize=14, fontweight="bold", pad=15)
    ax1.set_xlabel("日期", fontsize=12)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha="right")
    ax1.grid(True, alpha=0.3)

    # 合并图例
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="best", fontsize=10, framealpha=0.9)

    fig.tight_layout()
    return fig


def plot_position_units(
    equity_df: pd.DataFrame,
    title: str = "海龟策略 — 持仓单位数量变化",
    figsize=(14, 4),
) -> plt.Figure:
    """
    图3: 持仓单位数量变化 (堆叠面积图)

    参数:
        equity_df: 权益曲线 (含 active_units)
    """
    fig, ax = plt.subplots(figsize=figsize)

    dates = pd.to_datetime(equity_df["date"])

    # 绘制持仓单位数
    ax.fill_between(
        dates, equity_df["active_units"],
        alpha=0.4, color="#534AB7", step="mid"
    )
    ax.step(
        dates, equity_df["active_units"],
        color="#534AB7", linewidth=2, where="mid"
    )

    # 标注最大持仓线
    max_units = equity_df["active_units"].max()
    ax.axhline(y=max_units, color="#534AB7", linewidth=1,
               linestyle="--", alpha=0.5)
    ax.text(
        dates.iloc[5], max_units + 0.2,
        f"最大持仓: {int(max_units)} 单位",
        fontsize=10, color="#534AB7", alpha=0.7
    )

    ax.set_title(title, fontsize=14, fontweight="bold", pad=15)
    ax.set_xlabel("日期", fontsize=12)
    ax.set_ylabel("活跃单位数", fontsize=12)
    ax.set_ylim(0, max(equity_df["active_units"].max() + 2, 5))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


def plot_equity_curve(
    equity_df: pd.DataFrame,
    df: pd.DataFrame,
    initial_capital: float = 1_000_000,
    title: str = "海龟策略 — 资金权益曲线",
    figsize=(14, 6),
) -> plt.Figure:
    """
    图4: 资金权益曲线 vs 买入持有基准 + 最大回撤

    参数:
        equity_df: 权益曲线 (含 equity, drawdown)
        df: 行情数据 (含 close, 用于计算买入持有)
        initial_capital: 初始资金
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize,
                                    gridspec_kw={"height_ratios": [3, 1]})

    dates = pd.to_datetime(equity_df["date"])

    # ── 上子图: 权益曲线 ──
    # 策略权益
    ax1.plot(
        dates, equity_df["equity"],
        color="#A32D2D", linewidth=2, label="海龟策略"
    )

    # 买入持有基准
    buy_hold_equity = df["close"] / df["close"].iloc[0] * initial_capital
    bh_dates = pd.to_datetime(df["trade_date"])
    ax1.plot(
        bh_dates, buy_hold_equity,
        color="#888780", linewidth=1.5, linestyle="--",
        alpha=0.7, label="买入持有"
    )

    # 初始资金线
    ax1.axhline(
        y=initial_capital, color="#888780", linewidth=1,
        linestyle=":", alpha=0.5
    )
    ax1.text(
        dates.iloc[5], initial_capital * 1.02,
        f"初始资金: {initial_capital:,.0f}",
        fontsize=10, color="#888780", alpha=0.7
    )

    ax1.set_title(title, fontsize=14, fontweight="bold", pad=15)
    ax1.set_ylabel("资金 (元)", fontsize=12)
    ax1.legend(loc="best", fontsize=10, framealpha=0.9)
    ax1.grid(True, alpha=0.3)

    # Y轴格式化
    ax1.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda x, p: f"{x:,.0f}")
    )

    # ── 下子图: 回撤曲线 ──
    ax2.fill_between(
        dates, 0, equity_df["drawdown"] * 100,
        color="#3B6D11", alpha=0.3
    )
    ax2.plot(
        dates, equity_df["drawdown"] * 100,
        color="#3B6D11", linewidth=1.5
    )

    max_dd = equity_df["drawdown"].min()
    ax2.axhline(
        y=max_dd * 100, color="#A32D2D", linewidth=1,
        linestyle="--", alpha=0.5
    )
    ax2.text(
        dates.iloc[int(len(dates) * 0.8)], max_dd * 100 - 1,
        f"最大回撤: {max_dd * 100:.2f}%",
        fontsize=10, color="#A32D2D", alpha=0.7
    )

    ax2.set_ylabel("回撤 (%)", fontsize=12, color="#3B6D11")
    ax2.set_xlabel("日期", fontsize=12)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha="right")
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(bottom=min(max_dd * 100 * 1.3, -5))

    fig.tight_layout()
    return fig


def plot_wilder_atr(
    df: pd.DataFrame,
    title: str = "Wilder ATR 走势 (N值)",
    figsize=(14, 8),
) -> plt.Figure:
    """
    图5: Wilder ATR 走势分析

    Wilder ATR = 前20日 N 的指数平滑均值（与 calc_n_value 一致）
    展示:
    - 上子图: TR(柱状) + ATR/N值(折线)
    - 下子图: ATR 滚动百分位 (判断波动率高低位)

    参数:
        df: 行情数据 (含 true_range, n_value)
    """
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=figsize, gridspec_kw={"height_ratios": [2, 1]}
    )

    dates = pd.to_datetime(df["trade_date"])

    # ── 上子图: TR + ATR ──
    # True Range 柱状图
    if "true_range" in df.columns:
        tr_valid = df["true_range"].notna()
        ax1.bar(
            dates[tr_valid],
            df.loc[tr_valid, "true_range"],
            color="#185FA5", alpha=0.2, width=1.0,
            label="TR (True Range)",
        )

    # ATR / N 值折线
    if "n_value" in df.columns:
        n_valid = df["n_value"].notna()
        ax1.plot(
            dates[n_valid], df.loc[n_valid, "n_value"],
            color="#A32D2D", linewidth=2,
            label=f"Wilder ATR (N值, {df['n_value'].notna().sum()}天均值)",
        )
        # N值均值参考线
        n_mean = df.loc[n_valid, "n_value"].mean()
        ax1.axhline(
            y=n_mean, color="#A32D2D", linewidth=1,
            linestyle="--", alpha=0.4,
        )
        ax1.text(
            dates.iloc[5], n_mean,
            f"均值: {n_mean:.2f}",
            fontsize=10, color="#A32D2D", alpha=0.6,
        )

    ax1.set_title(title, fontsize=14, fontweight="bold", pad=15)
    ax1.set_ylabel("波动率 (元)", fontsize=12)
    ax1.legend(loc="upper left", fontsize=10, framealpha=0.9)
    ax1.grid(True, alpha=0.3)

    # ── 下子图: ATR 百分位 ──
    if "n_value" in df.columns:
        n_valid = df["n_value"].notna()
        n_series = df.loc[n_valid, "n_value"]

        # 滚动百分位 (取过去252个交易日, 约1年)
        rolling_rank = n_series.rolling(252, min_periods=63).apply(
            lambda x: (n_series.loc[x.index[-1]] - x.min()) / (x.max() - x.min() + 1e-10) * 100
        )
        # 用更简单的分位数映射
        n_pct = n_series.rolling(252, min_periods=63).rank(pct=True) * 100

        ax2.fill_between(
            dates[n_valid], n_pct, 50,
            where=(n_pct >= 50),
            color="#A32D2D", alpha=0.3, label="高位区 (>50%)"
        )
        ax2.fill_between(
            dates[n_valid], n_pct, 50,
            where=(n_pct < 50),
            color="#3B6D11", alpha=0.3, label="低位区 (<50%)"
        )
        ax2.plot(
            dates[n_valid], n_pct,
            color="#534AB7", linewidth=1.5, alpha=0.8,
        )

        # 80% 和 20% 参考线
        ax2.axhline(y=80, color="#A32D2D", linewidth=1,
                    linestyle=":", alpha=0.5)
        ax2.text(dates.iloc[5], 81, "80% 高波动警戒", fontsize=9, color="#A32D2D", alpha=0.6)
        ax2.axhline(y=20, color="#3B6D11", linewidth=1,
                    linestyle=":", alpha=0.5)
        ax2.text(dates.iloc[5], 21, "20% 低波动警戒", fontsize=9, color="#3B6D11", alpha=0.6)
        ax2.axhline(y=50, color="#888780", linewidth=0.5,
                    linestyle="--", alpha=0.3)

    ax2.set_ylabel("ATR百分位 (%)", fontsize=12, color="#534AB7")
    ax2.set_xlabel("日期", fontsize=12)
    ax2.set_ylim(-5, 105)
    ax2.legend(loc="upper left", fontsize=10, framealpha=0.9)
    ax2.grid(True, alpha=0.3)

    # X轴统一
    for ax in [ax1, ax2]:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

    fig.tight_layout()
    return fig


def plot_all(
    df: pd.DataFrame,
    trades_df: pd.DataFrame,
    equity_df: pd.DataFrame,
    initial_capital: float = 1_000_000,
    system_name: str = "S1",
) -> plt.Figure:
    """
    绘制全部 4 张图，合并为一个 figure 展示

    返回:
        4 张图的列表
    """
    fig1 = plot_price_channels_signals(
        df, trades_df,
        title=f"海龟策略 ({system_name}) — 价格通道与交易信号"
    )
    fig2 = plot_n_value_analysis(
        df, equity_df,
        title=f"海龟策略 ({system_name}) — N值(ATR)与持仓分析"
    )
    fig3 = plot_position_units(
        equity_df,
        title=f"海龟策略 ({system_name}) — 持仓单位数量变化"
    )
    fig4 = plot_equity_curve(
        equity_df, df, initial_capital,
        title=f"海龟策略 ({system_name}) — 资金权益曲线"
    )
    fig5 = plot_wilder_atr(
        df,
        title=f"海龟策略 ({system_name}) — Wilder ATR 走势"
    )

    return [fig1, fig2, fig3, fig4, fig5]
