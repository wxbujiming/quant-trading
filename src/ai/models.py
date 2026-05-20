"""
模型管理模块。

提供统一的模型创建、保存、加载、集成功能。
"""
from typing import Any, Dict, List, Optional
from pathlib import Path
import json
from datetime import datetime

import numpy as np
import joblib

from .features import FeatureEngineer


class ModelFactory:
    """统一模型工厂 — 创建 XGBoost / LightGBM 分类器。"""

    @staticmethod
    def create_model(model_type: str = "xgb",
                     params: Optional[Dict] = None) -> Any:
        """创建分类器。

        Args:
            model_type: "xgb" 或 "lgb"
            params: 模型超参（覆盖默认值）

        Returns:
            未训练的模型实例
        """
        base_params = {
            "n_estimators": 100,
            "max_depth": 6,
            "learning_rate": 0.1,
            "random_state": 42,
            "verbosity": 0,
        }
        if params:
            base_params.update(params)

        if model_type == "xgb":
            try:
                import xgboost as xgb
            except ImportError:
                raise ImportError("请安装 xgboost: pip install xgboost")
            return xgb.XGBClassifier(
                **base_params,
                eval_metric="mlogloss",
                early_stopping_rounds=10,
            )

        elif model_type == "lgb":
            try:
                import lightgbm as lgb
            except ImportError:
                raise ImportError("请安装 lightgbm: pip install lightgbm")
            return lgb.LGBMClassifier(**base_params)

        else:
            raise ValueError(f"不支持的模型类型: {model_type}")


class ModelManager:
    """模型包管理器 — 保存/加载含元数据的完整模型包。

    模型包结构 (joblib):
        {
            "model":       训练好的分类器
            "scaler":      FeatureEngineer 参数 (dict)
            "feature_names": 特征列名列表
            "metadata":    {
                "symbol":      品种代码
                "model_type":  模型类型
                "train_date":  训练日期
                "score":       测试集评分
                "params":      训练参数
            }
        }
    """

    def __init__(self, model_dir: str = "./models"):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

    def save(self, model: Any, engineer: FeatureEngineer,
             metadata: Dict[str, Any]) -> str:
        """保存模型包。

        Args:
            model: 训练好的模型
            engineer: 已 fit 的 FeatureEngineer
            metadata: 元数据（symbol, model_type, score 等）

        Returns:
            模型文件路径
        """
        symbol = metadata.get("symbol", "unknown")
        model_type = metadata.get("model_type", "xgb")
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{symbol}_{model_type}_{date_str}.joblib"
        filepath = self.model_dir / filename

        pkg = {
            "model": model,
            "scaler": engineer.get_fitted_params(),
            "feature_names": engineer.feature_names,
            "metadata": {
                **metadata,
                "train_date": datetime.now().isoformat(),
            },
        }
        joblib.dump(pkg, filepath)
        return str(filepath)

    def load(self, path: str) -> Dict[str, Any]:
        """加载模型包。

        Args:
            path: .joblib 文件路径（绝对或相对）

        Returns:
            {"model": ..., "metadata": ..., "feature_names": ..., "scaler_params": ...}
        """
        filepath = Path(path)
        if not filepath.is_absolute() and not filepath.exists():
            # 尝试从 model_dir 拼接
            candidate = self.model_dir / filepath
            if candidate.exists():
                filepath = candidate

        if not filepath.exists():
            raise FileNotFoundError(f"模型文件不存在: {filepath}")

        pkg = joblib.load(filepath)
        return {
            "model": pkg["model"],
            "metadata": pkg.get("metadata", {}),
            "feature_names": pkg.get("feature_names", []),
            "scaler_params": pkg.get("scaler", {}),
        }

    def list_models(self) -> List[Dict[str, Any]]:
        """列出所有已保存的模型包。

        Returns:
            [{filename, symbol, model_type, train_date, score}, ...]
        """
        results = []
        for f in sorted(self.model_dir.glob("*.joblib"), reverse=True):
            try:
                pkg = joblib.load(f)
                meta = pkg.get("metadata", {})
                results.append({
                    "filename": f.name,
                    "path": str(f),
                    "symbol": meta.get("symbol", "?"),
                    "model_type": meta.get("model_type", "?"),
                    "train_date": meta.get("train_date", "?"),
                    "score": meta.get("score"),
                })
            except Exception:
                continue
        return results


class EnsembleModel:
    """集成模型 — 多模型投票/平均。"""

    def __init__(self, models: List[Any], weights: Optional[List[float]] = None):
        self.models = models
        self.weights = weights or [1.0 / len(models)] * len(models)

    def predict(self, X: np.ndarray) -> np.ndarray:
        """硬投票。"""
        preds = np.array([m.predict(X) for m in self.models])
        # 带权投票
        weighted = np.zeros((X.shape[0],))
        for i, p in enumerate(preds):
            weighted += self.weights[i] * p
        return np.sign(weighted)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """概率平均。"""
        probas = np.array([m.predict_proba(X) for m in self.models])
        return np.average(probas, axis=0, weights=self.weights)
