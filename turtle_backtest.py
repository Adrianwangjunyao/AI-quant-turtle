"""
海龟策略回测引擎 (Turtle Backtest Engine)
============================================
支持多单位持仓台账、逐单位 2N 止损、金字塔加仓、通道趋势退出。

与 Task-3 回测引擎的关键差异:
    - 持仓不再是单一的 shares, 而是多单位台账 (position_units)
    - 支持信号 1(入场) / 2(加仓) / -1(趋势退出) / -2(止损)
    - 各单位独立计算止损价并独立平仓
"""

import pandas as pd
import numpy as np
from typing import Tuple, List, Dict, Any


class PositionUnit:
    """持仓单位"""

    def __init__(self, unit_id: int, entry_date, entry_price: float,
                 stop_price: float, shares: int):
        self.unit_id = unit_id
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.stop_price = stop_price
        self.shares = shares
        self.active = True
        self.exit_date = None
        self.exit_price = None
        self.exit_reason = ""  # "stop_loss" or "trend_exit"

    def to_dict(self) -> Dict:
        return {
            "unit_id": self.unit_id,
            "entry_date": self.entry_date,
            "entry_price": round(self.entry_price, 2),
            "stop_price": round(self.stop_price, 2),
            "shares": self.shares,
            "active": self.active,
            "exit_date": self.exit_date,
            "exit_price": round(self.exit_price, 2) if self.exit_price else None,
            "exit_reason": self.exit_reason,
        }


class TurtleBacktestEngine:
    """
    海龟策略回测引擎

    参数:
        initial_capital: 初始资金 (元)
        commission_rate: 手续费率 (双边)
        slippage: 滑点率
        stamp_duty: 印花税 (仅卖出单边)
        risk_pct: 每单位风险比例 (与策略一致)
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000,
        commission_rate: float = 0.0003,
        slippage: float = 0.0001,
        stamp_duty: float = 0.001,
        min_commission: float = 5.0,
        risk_pct: float = 0.01,
    ):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.stamp_duty = stamp_duty
        self.min_commission = min_commission
        self.risk_pct = risk_pct

    def _calc_unit_shares(self, equity: float, n_value: float) -> int:
        """
        计算一个单位的股数

        公式: floor( (总权益 × risk_pct) / N / 100 ) × 100
        """
        if n_value <= 0 or np.isnan(n_value):
            return 0
        raw_shares = (equity * self.risk_pct) / n_value
        shares = int(raw_shares / 100) * 100
        return shares

    def _calc_commission(self, amount: float) -> float:
        """计算佣金 (最低 5 元)"""
        comm = amount * self.commission_rate
        return max(comm, self.min_commission)

    def run(
        self, strategy, df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.DataFrame, List[Dict]]:
        """
        执行回测。

        参数:
            strategy: TurtleStrategy 实例
            df: 行情数据 (必须含 trade_date, open, high, low, close)

        返回:
            trades_df:  交易记录 (每行一次完整买卖)
            equity_df:  权益曲线 (每行一天)
            units_log:  各单位持仓变化日志
        """
        # 生成基础信号 (入场 + 趋势退出)
        df = strategy.generate_signals(df)
        n = len(df)

        # 状态变量
        cash = self.initial_capital
        position_units: List[PositionUnit] = []
        next_unit_id = 1

        # 记录器
        equity_records: List[Dict] = []
        trades: List[Dict] = []

        for i in range(n):
            date = df.iloc[i]["trade_date"]
            signal = df.iloc[i]["signal"]
            close = df.iloc[i]["close"]
            open_price = df.iloc[i]["open"]
            high = df.iloc[i]["high"]
            n_value = df.iloc[i]["n_value"]
            channel_low = df.iloc[i]["channel_low"]
            channel_high = df.iloc[i]["channel_high"]

            # 有效 N 值和通道数据才处理交易
            has_valid_data = (
                not pd.isna(n_value)
                and n_value > 0
                and not pd.isna(channel_low)
                and not pd.isna(channel_high)
            )

            # 计算当前总权益
            active_shares = sum(u.shares for u in position_units if u.active)
            position_value = active_shares * close
            total_equity = cash + position_value

            # ─────────────────────────────────────────────
            # 步骤 1: 检查各单位的 2N 止损 (使用收盘价判断)
            # ─────────────────────────────────────────────
            if has_valid_data:
                for unit in position_units:
                    if unit.active and close <= unit.stop_price:
                        # 止损触发 - 以开盘价卖出 (加滑点)
                        sell_price = open_price * (1 - self.slippage)
                        revenue = unit.shares * sell_price
                        commission = self._calc_commission(revenue)
                        stamp = revenue * self.stamp_duty
                        cash += revenue - commission - stamp

                        unit.active = False
                        unit.exit_date = date
                        unit.exit_price = sell_price
                        unit.exit_reason = "stop_loss"

                        pnl = (
                            revenue
                            - unit.shares * unit.entry_price
                            - unit.shares * unit.entry_price * self.commission_rate
                            - commission
                            - stamp
                        )

                        trades.append({
                            "entry_date": unit.entry_date,
                            "entry_price": round(unit.entry_price, 2),
                            "exit_date": date,
                            "exit_price": round(sell_price, 2),
                            "shares": unit.shares,
                            "pnl": round(pnl, 2),
                            "pnl_pct": round(
                                pnl / (unit.shares * unit.entry_price) * 100, 2
                            ),
                            "reason": "stop_loss",
                            "unit_id": unit.unit_id,
                        })

            # ─────────────────────────────────────────────
            # 步骤 2: 检查趋势退出 (跌破通道下轨)
            # ─────────────────────────────────────────────
            if has_valid_data and signal == -1:
                # 全部活跃单位平仓
                for unit in position_units:
                    if unit.active:
                        sell_price = open_price * (1 - self.slippage)
                        revenue = unit.shares * sell_price
                        commission = self._calc_commission(revenue)
                        stamp = revenue * self.stamp_duty
                        cash += revenue - commission - stamp

                        unit.active = False
                        unit.exit_date = date
                        unit.exit_price = sell_price
                        unit.exit_reason = "trend_exit"

                        pnl = (
                            revenue
                            - unit.shares * unit.entry_price
                            - unit.shares * unit.entry_price * self.commission_rate
                            - commission
                            - stamp
                        )

                        trades.append({
                            "entry_date": unit.entry_date,
                            "entry_price": round(unit.entry_price, 2),
                            "exit_date": date,
                            "exit_price": round(sell_price, 2),
                            "shares": unit.shares,
                            "pnl": round(pnl, 2),
                            "pnl_pct": round(
                                pnl / (unit.shares * unit.entry_price) * 100, 2
                            ),
                            "reason": "trend_exit",
                            "unit_id": unit.unit_id,
                        })

            # ─────────────────────────────────────────────
            # 步骤 3: 检查入场条件 (首次开仓)
            # ─────────────────────────────────────────────
            active_count = sum(1 for u in position_units if u.active)

            if has_valid_data and active_count == 0 and signal == 1:
                # 计算头寸
                shares = self._calc_unit_shares(total_equity, n_value)

                if shares > 0:
                    buy_price = open_price * (1 + self.slippage)
                    cost = shares * buy_price
                    commission = self._calc_commission(cost)
                    total_cost = cost + commission

                    if total_cost <= cash:
                        stop_price = buy_price - 2 * n_value
                        unit = PositionUnit(
                            unit_id=next_unit_id,
                            entry_date=date,
                            entry_price=buy_price,
                            stop_price=stop_price,
                            shares=shares,
                        )
                        position_units.append(unit)
                        next_unit_id += 1
                        cash -= total_cost

            # ─────────────────────────────────────────────
            # 步骤 4: 检查加仓条件 (金字塔加仓)
            # ─────────────────────────────────────────────
            if has_valid_data and active_count > 0 and active_count < strategy.max_units:
                # 找到最近一个活跃单位的入场价
                last_entry = None
                for u in reversed(position_units):
                    if u.active:
                        last_entry = u.entry_price
                        break

                if last_entry is not None:
                    # 加仓条件: 当日最高价 >= 上一单位入场价 + add_unit_step × N
                    add_threshold = last_entry + strategy.add_unit_step * n_value
                    if high >= add_threshold:
                        # 计算新单位的头寸
                        shares = self._calc_unit_shares(total_equity, n_value)
                        if shares > 0:
                            buy_price = open_price * (1 + self.slippage)
                            cost = shares * buy_price
                            commission = self._calc_commission(cost)
                            total_cost = cost + commission

                            if total_cost <= cash:
                                stop_price = buy_price - 2 * n_value
                                unit = PositionUnit(
                                    unit_id=next_unit_id,
                                    entry_date=date,
                                    entry_price=buy_price,
                                    stop_price=stop_price,
                                    shares=shares,
                                )
                                position_units.append(unit)
                                next_unit_id += 1
                                cash -= total_cost

            # ─────────────────────────────────────────────
            # 步骤 5: 记录当日权益
            # ─────────────────────────────────────────────
            active_shares = sum(u.shares for u in position_units if u.active)
            position_value = active_shares * close
            equity = cash + position_value
            active_units = sum(1 for u in position_units if u.active)

            equity_records.append({
                "date": date,
                "equity": round(equity, 2),
                "cash": round(cash, 2),
                "position_value": round(position_value, 2),
                "active_units": active_units,
                "total_units": len([u for u in position_units if u.active or u.exit_date is not None]),
                "n_value": round(n_value, 2) if not pd.isna(n_value) else None,
                "channel_high": round(channel_high, 2) if not pd.isna(channel_high) else None,
                "channel_low": round(channel_low, 2) if not pd.isna(channel_low) else None,
            })

        # ─────────────────────────────────────────────
        # 最后一日: 强制平仓所有活跃单位
        # ─────────────────────────────────────────────
        last_close = df.iloc[-1]["close"]
        last_date = df.iloc[-1]["trade_date"]
        for unit in position_units:
            if unit.active:
                revenue = unit.shares * last_close
                commission = self._calc_commission(revenue)
                stamp = revenue * self.stamp_duty
                cash += revenue - commission - stamp

                unit.active = False
                unit.exit_date = last_date
                unit.exit_price = last_close
                unit.exit_reason = "force_liquidate"

                pnl = (
                    revenue
                    - unit.shares * unit.entry_price
                    - unit.shares * unit.entry_price * self.commission_rate
                    - commission
                    - stamp
                )

                trades.append({
                    "entry_date": unit.entry_date,
                    "entry_price": round(unit.entry_price, 2),
                    "exit_date": last_date,
                    "exit_price": round(last_close, 2),
                    "shares": unit.shares,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(
                        pnl / (unit.shares * unit.entry_price) * 100, 2
                    ),
                    "reason": "force_liquidate",
                    "unit_id": unit.unit_id,
                })

        # ─────────────────────────────────────────────
        # 整理输出
        # ─────────────────────────────────────────────
        trades_df = pd.DataFrame(trades) if trades else pd.DataFrame(
            columns=["entry_date", "entry_price", "exit_date", "exit_price",
                     "shares", "pnl", "pnl_pct", "reason", "unit_id"]
        )

        equity_df = pd.DataFrame(equity_records)
        equity_df["daily_return"] = equity_df["equity"].pct_change().fillna(0)
        equity_df["cum_return"] = (1 + equity_df["daily_return"]).cumprod() - 1

        # 最大回撤
        peak = equity_df["equity"].expanding().max()
        equity_df["drawdown"] = (equity_df["equity"] - peak) / peak

        # 单位日志
        units_log = [u.to_dict() for u in position_units]

        return trades_df, equity_df, units_log


class PerformanceAnalyzer:
    """绩效分析器"""

    def __init__(self, equity_df: pd.DataFrame, trades_df: pd.DataFrame,
                 initial_capital: float = 1_000_000):
        self.equity_df = equity_df
        self.trades_df = trades_df
        self.initial_capital = initial_capital

    def summary(self) -> Dict[str, Any]:
        """生成绩效摘要"""
        eq = self.equity_df
        tr = self.trades_df

        final_equity = eq["equity"].iloc[-1]
        total_return = (final_equity - self.initial_capital) / self.initial_capital

        n_days = len(eq)
        annual_return = (1 + total_return) ** (252 / max(n_days, 1)) - 1

        max_drawdown = eq["drawdown"].min()

        # 夏普比率
        rf_daily = 0.02 / 252
        excess_returns = eq["daily_return"] - rf_daily
        sharpe = (
            excess_returns.mean() / excess_returns.std() * (252 ** 0.5)
            if excess_returns.std() > 0
            else 0
        )

        # 交易统计
        total_trades = len(tr)
        if total_trades > 0:
            win_trades = (tr["pnl"] > 0).sum()
            win_rate = win_trades / total_trades
            avg_win = tr[tr["pnl"] > 0]["pnl"].mean() if win_trades > 0 else 0
            avg_loss = (
                abs(tr[tr["pnl"] < 0]["pnl"].mean())
                if win_trades < total_trades
                else 0
            )
            profit_factor = (
                abs(
                    tr[tr["pnl"] > 0]["pnl"].sum()
                    / tr[tr["pnl"] < 0]["pnl"].sum()
                )
                if (tr["pnl"] < 0).sum() > 0
                else float("inf")
            )
            total_pnl = tr["pnl"].sum()

            # 按退出原因分组统计
            stop_loss_count = (tr["reason"] == "stop_loss").sum()
            trend_exit_count = (tr["reason"] == "trend_exit").sum()
            force_liquidate_count = (tr["reason"] == "force_liquidate").sum()
        else:
            win_rate = 0
            avg_win = 0
            avg_loss = 0
            profit_factor = 0
            total_pnl = 0
            stop_loss_count = 0
            trend_exit_count = 0
            force_liquidate_count = 0

        return {
            "total_return": round(total_return * 100, 2),
            "annual_return": round(annual_return * 100, 2),
            "max_drawdown": round(max_drawdown * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "total_trades": total_trades,
            "win_rate": round(win_rate * 100, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": (
                round(profit_factor, 2) if profit_factor != float("inf") else "inf"
            ),
            "total_pnl": round(total_pnl, 2),
            "final_equity": round(final_equity, 2),
            "stop_loss_trades": stop_loss_count,
            "trend_exit_trades": trend_exit_count,
            "force_liquidate_trades": force_liquidate_count,
        }
