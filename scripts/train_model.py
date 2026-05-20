"""
AI 模型训练脚本。

用法:
    python scripts/train_model.py --symbol RB --model xgb --start 2020-01-01
    python scripts/train_model.py --symbol RB --model lgb --params '{"n_estimators": 200}'
    python scripts/train_model.py --list-models    # 查看已保存的模型
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
import pandas as pd

from src.core.logger import setup_logger
from src.data.futures_collector import FuturesDataCollector
from src.ai.pipeline import AIPipeline
from src.ai.models import ModelManager


def load_data(symbol: str, start_date: str = "2020-01-01",
              end_date: str = None) -> pd.DataFrame:
    """加载连续合约日线数据。"""
    collector = FuturesDataCollector()
    df = collector.get_continuous_daily(f"{symbol}0")
    if df.empty:
        raise ValueError(f"获取 {symbol} 数据失败")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")

    if start_date:
        df = df[df["date"] >= start_date]
    if end_date:
        df = df[df["date"] <= end_date]

    df = df.set_index("date")
    return df


def list_models(model_dir: str):
    """列出所有已保存模型。"""
    mgr = ModelManager(model_dir=model_dir)
    models = mgr.list_models()
    if not models:
        print("暂无已保存模型")
        return

    print(f"\n{'=' * 80}")
    print(f"  已保存模型 ({len(models)} 个)")
    print(f"{'=' * 80}")
    print(f"  {'文件名':<30} {'品种':<8} {'类型':<6} {'评分':<8} {'训练日期'}")
    print(f"  {'-' * 30} {'-' * 8} {'-' * 6} {'-' * 8} {'-' * 19}")
    for m in models:
        score = f"{m['score']:.4f}" if m['score'] else "?"
        date_str = (m['train_date'][:19] if m['train_date'] != "?"
                    else "?")
        print(f"  {m['filename']:<30} {m['symbol']:<8} {m['model_type']:<6} "
              f"{score:<8} {date_str}")
    print(f"{'=' * 80}")


def main():
    parser = argparse.ArgumentParser(description="AI 模型训练")
    parser.add_argument("--symbol", type=str, default="RB", help="品种代码")
    parser.add_argument("--model", type=str, default="xgb",
                        choices=["xgb", "lgb"], help="模型类型")
    parser.add_argument("--params", type=str, default=None,
                        help='模型超参 JSON, 如 \'{"n_estimators": 200}\'')
    parser.add_argument("--start", type=str, default="2020-01-01",
                        help="数据起始日期")
    parser.add_argument("--end", type=str, default=None, help="数据截止日期")
    parser.add_argument("--forward", type=int, default=5, help="标签窗口期数")
    parser.add_argument("--threshold-low", type=float, default=0.3,
                        help="下跌阈值百分位")
    parser.add_argument("--threshold-high", type=float, default=0.7,
                        help="上涨阈值百分位")
    parser.add_argument("--model-dir", type=str, default="./models",
                        help="模型保存目录")
    parser.add_argument("--list-models", action="store_true",
                        help="列出已保存模型")
    args = parser.parse_args()

    setup_logger("INFO", "logs/train_model.log")

    if args.list_models:
        list_models(args.model_dir)
        return

    # 加载数据
    logger.info(f"加载 {args.symbol} 数据 (从 {args.start})...")
    df = load_data(args.symbol, args.start, args.end)
    logger.info(f"数据量: {len(df)} 条, "
                f"{df.index[0].date()} ~ {df.index[-1].date()}")

    # 模型参数
    model_params = None
    if args.params:
        model_params = json.loads(args.params)

    # 训练
    pipeline = AIPipeline(model_dir=args.model_dir)
    result = pipeline.train(
        df=df,
        symbol=args.symbol,
        model_type=args.model,
        model_params=model_params,
        forward_period=args.forward,
        low_threshold=args.threshold_low,
        high_threshold=args.threshold_high,
    )

    # 输出结果
    print(f"\n{'=' * 60}")
    print(f"  训练完成: {args.symbol} / {args.model}")
    print(f"{'=' * 60}")
    print(f"  准确率:      {result['accuracy']:.4f}")
    print(f"  训练样本:    {result['n_train']}")
    print(f"  验证样本:    {result['n_val']}")
    print(f"  测试样本:    {result['n_test']}")
    print(f"  模型文件:    {result['model_path']}")
    print()

    # 分类报告摘要
    report = result['report']
    for cls_name, metrics in report.items():
        if cls_name in ("accuracy", "macro avg", "weighted avg"):
            continue
        try:
            cls_label = {-1: "跌", 0: "横盘", 1: "涨"}.get(int(cls_name), cls_name)
            print(f"  {cls_label}: precision={metrics['precision']:.3f}, "
                  f"recall={metrics['recall']:.3f}, f1={metrics['f1-score']:.3f}")
        except (ValueError, KeyError):
            continue

    # 特征重要性 Top 10
    importance = result.get("feature_importance", {})
    if importance:
        print(f"\n  特征重要性 Top 10:")
        for name, imp in list(importance.items())[:10]:
            print(f"    {name}: {imp:.4f}")

    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
