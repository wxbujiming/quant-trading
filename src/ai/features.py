"""
特征工程模块。

职责：
1. 因子标准化（z-score）
2. 训练标签生成（三分类）
3. 端到端数据集构建
"""
from typing import Dict, Optional, Tuple
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler

from .factors import FactorComputer


class FeatureEngineer:
    """特征工程：标准化 + 标签生成。

    用法:
        fe = FeatureEngineer()
        fe.fit(factor_df)            # 学习均值/标准差
        X = fe.transform(factor_df)  # z-score 标准化

        labels = fe.make_labels(df)  # 生成三分类标签
    """

    def __init__(self):
        self.scaler = StandardScaler()
        self._fitted = False
        self._feature_names: list = []

    def fit(self, df_factors: pd.DataFrame):
        """学习各因子的均值/标准差。

        Args:
            df_factors: 因子 DataFrame
        """
        self._feature_names = [c for c in df_factors.columns
                               if df_factors[c].nunique() > 1]
        valid = df_factors[self._feature_names]\
            .fillna(0)\
            .replace([np.inf, -np.inf], np.nan)\
            .fillna(0)
        self.scaler.fit(valid.values)
        self._fitted = True

    def transform(self, df_factors: pd.DataFrame,
                  fill_value: float = 0.0) -> pd.DataFrame:
        """z-score 标准化因子。

        Args:
            df_factors: 因子 DataFrame
            fill_value: NaN 填充值（推理时用 0，训练时用 NaN 以便 dropna）

        Returns:
            标准化后的 DataFrame
        """
        if not self._fitted:
            raise RuntimeError("请先调用 fit()")

        # 只保留 fit 时见过的列
        cols = [c for c in self._feature_names if c in df_factors]
        if not cols:
            return pd.DataFrame(index=df_factors.index)

        X = df_factors[cols]\
            .fillna(fill_value)\
            .replace([np.inf, -np.inf], 0.0)
        scaled = self.scaler.transform(X.values)
        return pd.DataFrame(scaled, index=df_factors.index, columns=cols)

    def make_labels(self, df: pd.DataFrame,
                    forward_period: int = 5,
                    low_threshold: float = 0.3,
                    high_threshold: float = 0.7) -> pd.Series:
        """生成三分类标签。

        计算未来 forward_period 期的收益率，按百分位分三档：
        -1 (跌):  < low_threshold 百分位
         0 (横盘): [low_threshold, high_threshold] 百分位
         1 (涨):  > high_threshold 百分位

        Args:
            df: OHLCV DataFrame（需含 close 列）
            forward_period: 未来 N 期
            low_threshold: 下跌阈值百分位
            high_threshold: 上涨阈值百分位

        Returns:
            标签 Series: -1 / 0 / 1，尾部 NaN（未来数据不足）
        """
        # 未来收益率 — 唯一一处使用 shift(-N)，仅用于标签
        future_ret = df["close"].shift(-forward_period) / df["close"] - 1

        # 用分位数确定阈值
        valid = future_ret.dropna()
        if len(valid) < 10:
            return pd.Series(0, index=df.index)

        low_val = valid.quantile(low_threshold)
        high_val = valid.quantile(high_threshold)

        labels = pd.Series(0, index=future_ret.index, dtype=int)
        labels[future_ret < low_val] = -1
        labels[future_ret > high_val] = 1
        labels[future_ret.isna()] = np.nan

        return labels

    def build_dataset(self, df_ohlcv: pd.DataFrame,
                      forward_period: int = 5,
                      low_threshold: float = 0.3,
                      high_threshold: float = 0.7) -> Tuple[pd.DataFrame, pd.Series]:
        """端到端构建训练数据集。

        Args:
            df_ohlcv: OHLCV DataFrame
            forward_period: 标签窗口
            low_threshold: 下跌阈值
            high_threshold: 上涨阈值

        Returns:
            (X, y) — 因子已标准化，NaN 行已去除
        """
        fc = FactorComputer()
        factors = fc.compute_all(df_ohlcv)

        # 初始化标签（临时，仅用于 fit 时做标签统计）
        self.fit(factors)

        labels = self.make_labels(
            df_ohlcv,
            forward_period=forward_period,
            low_threshold=low_threshold,
            high_threshold=high_threshold,
        )

        X = self.transform(factors, fill_value=np.nan)

        # 去掉含 NaN 的行（训练时）
        valid_mask = (~X.isna().any(axis=1)) & labels.notna()
        return X[valid_mask], labels[valid_mask]

    @property
    def feature_names(self) -> list:
        return list(self._feature_names)

    def get_fitted_params(self) -> Dict:
        """获取标准化参数（用于序列化）。"""
        if not self._fitted:
            return {}
        return {
            "mean": self.scaler.mean_.tolist(),
            "std": self.scaler.scale_.tolist(),
            "feature_names": self._feature_names,
        }

    def set_fitted_params(self, mean: list, std: list,
                          feature_names: list):
        """恢复标准化参数。"""
        self._feature_names = feature_names
        self.scaler.mean_ = np.array(mean)
        self.scaler.scale_ = np.array(std)
        self.scaler.n_features_in_ = len(feature_names)
        self._fitted = True
