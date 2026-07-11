"""
海龟交易策略模块 (Turtle Trading Strategy)
=============================================
基于经典海龟交易法则，包含：
- N值(ATR)计算
- 唐奇安通道(Donchian Channel)突破入场/退出
- 2N 止损
- 金字塔加仓

信号编码:
    0  = 无操作
    1  = 首次入场买入（开第一单位）
    2  = 金字塔加仓（开第2~4单位）
   -1  = 趋势退出（跌破通道下轨，全部平仓）
   -2  = 止损触发（跌破 2N 止损线，触发单位平仓）
"""

import pandas as pd
import numpy as np


class TurtleStrategy:
    """
    海龟交易策略

    参数:
        system: 系统名称 "S1" 或 "S2"
        entry_window: 入场突破周期 (S1=20, S2=55)
        exit_window: 退出突破周期 (S1=10, S2=20)
        atr_period: N 值计算周期 (默认 20)
        risk_pct: 每单位风险比例 (默认 0.01 = 1%)
        max_units: 最大持仓单位数 (默认 4)
        add_unit_step: 加仓步长, N 的倍数 (默认 0.5)
    """

    def __init__(
        self,
        system: str = "S1",
        entry_window: int = 20,
        exit_window: int = 10,
        atr_period: int = 20,
        risk_pct: float = 0.01,
        max_units: int = 4,
        add_unit_step: float = 0.5,
    ):
        self.system = system.upper()
        self.entry_window = entry_window
        self.exit_window = exit_window
        self.atr_period = atr_period
        self.risk_pct = risk_pct
        self.max_units = max_units
        self.add_unit_step = add_unit_step
        self.name = f"Turtle-{self.system}({entry_window}x{exit_window})"

    def calc_true_range(self, df: pd.DataFrame) -> pd.Series:
        """
        计算 True Range (TR)

        TR = max(high - low, |high - prev_close|, |low - prev_close|)
        """
        prev_close = df["close"].shift(1)
        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - prev_close).abs()
        tr3 = (df["low"] - prev_close).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return true_range

    def calc_n_value(self, df: pd.DataFrame, true_range: pd.Series) -> pd.Series:
        """
        计算 N 值 (指数平滑 ATR)

        N = (前一日 N × (atr_period - 1) + 当日 TR) / atr_period
        首日 N = TR 的简单均值（前 atr_period 天）
        """
        n_value = pd.Series(np.nan, index=df.index)

        # 前 atr_period 天用简单平均初始化
        n_value.iloc[self.atr_period - 1] = (
            true_range.iloc[: self.atr_period].mean()
        )

        # 后续用指数平滑
        for i in range(self.atr_period, len(df)):
            prev_n = n_value.iloc[i - 1]
            tr = true_range.iloc[i]
            n_value.iloc[i] = (prev_n * (self.atr_period - 1) + tr) / self.atr_period

        return n_value

    def calc_donchian_channel(
        self, df: pd.DataFrame, window: int
    ) -> pd.DataFrame:
        """
        计算唐奇安通道

        返回:
            DataFrame 包含:
            - channel_high: 过去 window 日最高价
            - channel_low: 过去 window 日最低价
        """
        # 排除当天: 过去 window 日的最高/最低 (不含当日)
        # 这样才能让今天的价格突破过去的范围
        prev_high = df["high"].shift(1)
        prev_low = df["low"].shift(1)
        channel_high = prev_high.rolling(window=window, min_periods=window).max()
        channel_low = prev_low.rolling(window=window, min_periods=window).min()
        return pd.DataFrame({"channel_high": channel_high, "channel_low": channel_low})

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号。

        参数:
            df: 必须包含 trade_date, open, high, low, close, vol

        返回:
            df 的副本，新增列:
            - true_range: 当日 True Range
            - n_value: N 值 (ATR)
            - channel_high: 入场通道上轨
            - channel_low: 退出通道下轨
            - signal: 交易信号 (0/1/2/-1/-2)
        """
        df = df.copy()
        df = df.sort_values("trade_date").reset_index(drop=True)

        n = len(df)

        # 1. 计算 TR 和 N 值
        df["true_range"] = self.calc_true_range(df)
        df["n_value"] = self.calc_n_value(df, df["true_range"])

        # 2. 计算唐奇安通道
        channel = self.calc_donchian_channel(df, self.entry_window)
        df["channel_high"] = channel["channel_high"]

        exit_channel = self.calc_donchian_channel(df, self.exit_window)
        df["channel_low"] = exit_channel["channel_low"]

        # 3. 生成信号
        df["signal"] = 0

        # 当天有 N 值和通道数据时才考虑交易
        valid_n = df["n_value"].notna()
        valid_channel = df["channel_high"].notna() & df["channel_low"].notna()
        valid = valid_n & valid_channel

        # ─── 入场信号 ───
        # 原版海龟: 价格突破通道上轨 (用 high/close 均可, 这里采用 high 更敏感)
        # 当日最高价突破通道上轨 → 触发入场
        entry_cond = valid & (df["high"] > df["channel_high"])
        df.loc[entry_cond, "signal"] = 1

        # ─── 退出信号 ───
        # 当日最低价跌破通道下轨 → 触发趋势退出
        exit_cond = valid & (df["low"] < df["channel_low"])
        df.loc[exit_cond, "signal"] = -1

        # 注意: 同一天可能同时满足入场和退出 (极端行情),
        # 优先处理退出 (保护资金安全)
        both = entry_cond & exit_cond
        df.loc[both, "signal"] = -1

        # 注意: 加仓(signal=2)和止损(signal=-2)在回测引擎中动态判断,
        # 因为需要持仓台账信息, 策略层只标记首次入场和趋势退出

        return df

    def __repr__(self):
        return (
            f"{self.name}(entry={self.entry_window}, exit={self.exit_window}, "
            f"atr={self.atr_period}, risk={self.risk_pct}, max_units={self.max_units})"
        )
