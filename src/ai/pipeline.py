"""
AI 训练/推理流水线。

端到端流程：
1. 加载 OHLCV 数据
2. 因子计算
3. 特征标准化 + 标签生成
4. 时间序列切分
5. 模型训练与评估
6. 模型包保存
"""
from typing import Any, Dict, Optional, Tuple
from pathlib import Path
import json

import pandas as pd
import numpy as np
from loguru import logger
from sklearn.metrics import (accuracy_score, classification_report,
                             confusion_matrix)

from .factors import FactorComputer
from .features import FeatureEngineer
from .models import ModelFactory, ModelManager


class AIPipeline:
    """AI 训练/推理流水线。"""

    def __init__(self, model_dir: str = "./models"):
        self.factor_computer = FactorComputer()
        self.engineer = FeatureEngineer()
        self.model_manager = ModelManager(model_dir=model_dir)
        self._factor_cache: Optional[pd.DataFrame] = None

    # ──────────────────────── 因子与特征 ────────────────────────

    def compute_factors(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算全部因子（带缓存）。"""
        self._factor_cache = self.factor_computer.compute_all(df)
        return self._factor_cache

    # ──────────────────────── 训练 ────────────────────────

    def train(self, df: pd.DataFrame, symbol: str,
              model_type: str = "xgb",
              model_params: Optional[Dict] = None,
              forward_period: int = 5,
              low_threshold: float = 0.3,
              high_threshold: float = 0.7,
              train_ratio: float = 0.7,
              val_ratio: float = 0.15,
              test_ratio: float = 0.15,
              ):
        """训练模型。

        Args:
            df: OHLCV DataFrame
            symbol: 品种代码（用于元数据）
            model_type: "xgb" 或 "lgb"
            model_params: 模型超参
            forward_period: 标签窗口
            low_threshold: 下跌阈值百分位
            high_threshold: 上涨阈值百分位
            train_ratio: 训练集比例
            val_ratio: 验证集比例
            test_ratio: 测试集比例

        Returns:
            {"model": ..., "report": ..., "feature_importance": ..., "model_path": ...}
        """
        # 因子计算
        factors = self.compute_factors(df)

        # 构建数据集（标准化 + 标签）
        X, y = self.engineer.build_dataset(
            df,
            forward_period=forward_period,
            low_threshold=low_threshold,
            high_threshold=high_threshold,
        )

        if len(X) < 100:
            raise ValueError(f"有效样本不足 ({len(X)}), 请检查数据量")

        # 时间序列切分（严格按顺序）
        n = len(X)
        train_end = int(n * train_ratio)
        val_end = train_end + int(n * val_ratio)

        X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
        X_val, y_val = X.iloc[train_end:val_end], y.iloc[train_end:val_end]
        X_test, y_test = X.iloc[val_end:], y.iloc[val_end:]

        logger.info(f"数据集: 训练={len(X_train)}, 验证={len(X_val)}, 测试={len(X_test)}")
        logger.info(f"标签分布: {pd.Series(y_train).value_counts().to_dict()}")

        # 创建并训练模型
        # XGBoost 需要标签从 0 开始，映射 -1→0, 0→1, 1→2
        _label_map = {-1: 0, 0: 1, 1: 2}
        _label_inv = {0: -1, 1: 0, 2: 1}

        y_train_mapped = y_train.map(_label_map)
        y_val_mapped = y_val.map(_label_map)
        y_test_mapped = y_test.map(_label_map)

        model = ModelFactory.create_model(model_type, model_params)
        model.fit(
            X_train.values, y_train_mapped.values,
            eval_set=[(X_val.values, y_val_mapped.values)],
            verbose=False,
        )

        # 测试集评估（映射回 -1/0/1）
        y_pred_mapped = model.predict(X_test.values)
        y_pred = np.array([_label_inv.get(int(p), 0) for p in y_pred_mapped])
        accuracy = accuracy_score(y_test, y_pred)
        report = classification_report(y_test, y_pred, output_dict=True,
                                       zero_division=0)
        cm = confusion_matrix(y_test, y_pred).tolist()

        logger.info(f"测试集准确率: {accuracy:.4f}")
        logger.info(f"分类报告:\n{classification_report(y_test, y_pred, zero_division=0)}")

        # 特征重要性
        importance = self._get_importance(model, X.columns)

        # 保存模型包
        model_path = self.model_manager.save(
            model, self.engineer,
            metadata={
                "symbol": symbol,
                "model_type": model_type,
                "score": accuracy,
                "params": {
                    "forward_period": forward_period,
                    "low_threshold": low_threshold,
                    "high_threshold": high_threshold,
                    "model_params": model_params,
                },
                "dataset_size": len(X),
                "feature_count": X.shape[1],
            },
        )
        logger.info(f"模型已保存: {model_path}")

        return {
            "model": model,
            "model_path": model_path,
            "accuracy": accuracy,
            "report": report,
            "confusion_matrix": cm,
            "feature_importance": importance,
            "n_train": len(X_train),
            "n_val": len(X_val),
            "n_test": len(X_test),
        }

    # ──────────────────────── 推理 ────────────────────────

    def predict(self, df: pd.DataFrame, model_path: str) -> np.ndarray:
        """使用已训练模型预测。

        Args:
            df: OHLCV DataFrame
            model_path: .joblib 模型文件路径

        Returns:
            预测标签数组 (-1 / 0 / 1)
        """
        pkg = self.model_manager.load(model_path)
        model = pkg["model"]
        feature_names = pkg["feature_names"]

        # 恢复 scaler
        self.engineer.set_fitted_params(
            pkg["scaler_params"].get("mean", []),
            pkg["scaler_params"].get("std", []),
            feature_names,
        )

        # 因子计算
        factors = self.compute_factors(df)

        # 仅取模型需要的特征列
        available = [c for c in feature_names if c in factors.columns]
        if len(available) != len(feature_names):
            missing = set(feature_names) - set(available)
            logger.warning(f"缺少特征: {missing}, 用 0 填充")

        X = pd.DataFrame(0.0, index=factors.index, columns=feature_names)
        X[available] = factors[available].fillna(0)

        X_scaled = self.engineer.transform(X, fill_value=0.0)
        raw_preds = model.predict(X_scaled.values)
        # 映射回 -1/0/1
        _inv = {0: -1, 1: 0, 2: 1}
        return np.array([_inv.get(int(p), 0) for p in raw_preds])

    def predict_proba(self, df: pd.DataFrame, model_path: str) -> np.ndarray:
        """预测概率，返回形状 (n, 3) 对应 [-1, 0, 1] 类的概率。"""
        pkg = self.model_manager.load(model_path)
        model = pkg["model"]
        feature_names = pkg["feature_names"]

        self.engineer.set_fitted_params(
            pkg["scaler_params"].get("mean", []),
            pkg["scaler_params"].get("std", []),
            feature_names,
        )

        factors = self.compute_factors(df)
        available = [c for c in feature_names if c in factors.columns]

        X = pd.DataFrame(0.0, index=factors.index, columns=feature_names)
        X[available] = factors[available].fillna(0)

        X_scaled = self.engineer.transform(X, fill_value=0.0)
        raw_probas = model.predict_proba(X_scaled.values)  # (n, 3) 对应 0/1/2
        # 重排为 [-1, 0, 1] 顺序
        return raw_probas[:, [0, 1, 2]]  # 已是对应顺序

    # ──────────────────────── 回测信号生成 ────────────────────────

    def generate_signals(self, df: pd.DataFrame, model_path: str,
                         score_threshold: float = 0.6) -> pd.Series:
        """生成交易信号（带概率阈值过滤）。

        Args:
            df: OHLCV DataFrame
            model_path: 模型路径
            score_threshold: 最小预测概率阈值（0~1）

        Returns:
            信号 Series: 1=做多, -1=做空, 0=观望
        """
        probas = self.predict_proba(df, model_path)
        preds = self.predict(df, model_path)

        # probas shape: (n, 3) 对应 [-1, 0, 1] 类
        max_proba = probas.max(axis=1)
        signals = np.where(max_proba >= score_threshold, preds, 0)

        return pd.Series(signals, index=df.index)

    @staticmethod
    def _get_importance(model: Any, feature_names: pd.Index) -> Dict:
        """提取特征重要性。"""
        if hasattr(model, "feature_importances_"):
            imp = model.feature_importances_.tolist()
            return dict(sorted(
                zip(feature_names, imp),
                key=lambda x: x[1],
                reverse=True,
            )[:20])
        return {}
