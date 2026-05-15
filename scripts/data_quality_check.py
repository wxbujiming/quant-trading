"""
数据质量检查脚本
用法:
    python scripts/data_quality_check.py                     # 检查所有缓存股票
    python scripts/data_quality_check.py --symbols 000001     # 检查指定股票
    python scripts/data_quality_check.py --html               # 输出HTML报告
    python scripts/data_quality_check.py --alert              # 高亮告警项

功能:
  1. 逐只检查缓存数据完整性
  2. 检查项: 日期连续性、缺失率、异常值、停牌天数、收益分布等
  3. 生成综合评分(A-F等级)
  4. 输出JSON/HTML/控制台三种报告格式
  5. 数据更新提醒
"""
import sys
import json
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple, Union

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from loguru import logger

from src.core.logger import setup_logger
from src.core.config import get_config
from src.data.collector import DataCollector
from src.data.cleaner import DataCleaner


# ──────────────── 检查规则配置 ────────────────

class QualityThresholds:
    """质量检查阈值"""
    MAX_NULL_RATIO = 0.05         # 最大允许缺失率 5%
    MAX_DUPLICATE_RATIO = 0.01    # 最大允许重复率 1%
    MIN_TRADING_DAYS = 100        # 最少交易日数
    MAX_STALLED_RATIO = 0.10      # 最大允许停牌率 10%
    MAX_PRICE_JUMP = 0.20         # 日涨跌幅超过20%告警
    MIN_ANNUAL_DAYS = 200         # 年均最少交易日
    OUTLIER_IQR_MULT = 5.0        # 异常值IQR倍数（检查用，比清洗宽松）
    MIN_DATA_YEARS = 0.5          # 最少数据年份
    MAX_NORMAL_GAP = 8            # 正常间距上限（含周末3天+节假日）


def _grade_score(score: float) -> str:
    """将分数转为等级"""
    if score >= 95:
        return "A+"
    elif score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    elif score >= 60:
        return "D"
    else:
        return "F"


def _grade_color(grade: str) -> str:
    colors = {"A+": "#00cc66", "A": "#33cc33", "B": "#99cc00",
              "C": "#ffcc00", "D": "#ff6600", "F": "#ff3333"}
    return colors.get(grade, "#999999")


# ──────────────── 检查器 ────────────────

class DataQualityChecker:
    """
    数据质量检查器
    
    对单只股票进行全面的数据质量检查，生成评分和告警。
    """

    def __init__(self, thresholds: Optional[QualityThresholds] = None):
        self.thresholds = thresholds or QualityThresholds()
        self._results: List[Dict] = []

    def _has_vol_column(self, df: pd.DataFrame) -> bool:
        """检查是否有成交量相关列（腾讯数据用amount替代volume）"""
        return "volume" in df.columns or "amount" in df.columns

    def _get_vol_series(self, df: pd.DataFrame) -> pd.Series:
        """获取成交量序列（兼容腾讯数据）"""
        if "volume" in df.columns:
            return pd.to_numeric(df["volume"], errors="coerce")
        if "amount" in df.columns:
            return pd.to_numeric(df["amount"], errors="coerce")
        return pd.Series([0] * len(df), index=df.index)

    def check_symbol(self, df: pd.DataFrame, symbol: str) -> Dict:
        """
        检查单只股票数据质量

        Returns:
            dict: 包含所有检查指标和评分
        """
        result = {
            "symbol": symbol,
            "check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rows": len(df),
            "alerts": [],
            "passed": True,
        }

        if df.empty:
            result["alerts"].append({"level": "error", "item": "数据为空", "detail": "DataFrame无数据行"})
            result["grade"] = "F"
            result["score"] = 0
            result["passed"] = False
            self._results.append(result)
            return result

        data = df.copy()
        deductions = 0.0  # 扣分累计

        # ── 1. 列完整性 ──
        required_cols = ["date", "open", "close", "high", "low"]
        # volume 或 amount 二选一
        if not self._has_vol_column(data):
            required_cols.append("volume_or_amount")
        missing_cols = [c for c in required_cols if c not in data.columns]
        if missing_cols:
            deductions += len(missing_cols) * 10
            result["alerts"].append({
                "level": "error",
                "item": "缺少必要列",
                "detail": f"缺失: {missing_cols}",
                "deduction": len(missing_cols) * 10,
            })

        # ── 2. 日期检查 ──
        if "date" in data.columns:
            dates = pd.to_datetime(data["date"], errors="coerce")
            valid_dates = dates.notna()
            invalid_dates = (~valid_dates).sum()

            if invalid_dates > 0:
                deductions += invalid_dates * 2
                result["alerts"].append({
                    "level": "warning", "item": "无效日期",
                    "detail": f"{invalid_dates} 行日期解析失败",
                    "deduction": invalid_dates * 2,
                })

            # 日期范围
            if valid_dates.any():
                result["date_start"] = str(dates.min().date())
                result["date_end"] = str(dates.max().date())
                span_days = (dates.max() - dates.min()).days
                result["span_days"] = span_days
                result["span_years"] = round(span_days / 365.25, 1)

                if span_days < self.thresholds.MIN_DATA_YEARS * 365:
                    deductions += 15
                    result["alerts"].append({
                        "level": "error", "item": "数据跨度不足",
                        "detail": f"仅 {span_days} 天 (< {self.thresholds.MIN_DATA_YEARS*365:.0f})",
                        "deduction": 15,
                    })

            # 交易日数量
            if valid_dates.any():
                trading_days = len(dates[valid_dates].unique())
                result["trading_days"] = trading_days
                if trading_days < self.thresholds.MIN_TRADING_DAYS:
                    deductions += 10
                    result["alerts"].append({
                        "level": "warning", "item": "交易日太少",
                        "detail": f"{trading_days} 天 (< {self.thresholds.MIN_TRADING_DAYS})",
                        "deduction": 10,
                    })

                # 年均交易日
                if span_days > 0:
                    annual_days = trading_days / (span_days / 365.25)
                    result["annual_trading_days"] = round(annual_days, 0)
                    if annual_days < self.thresholds.MIN_ANNUAL_DAYS * 0.7:
                        deductions += 5
                        result["alerts"].append({
                            "level": "warning", "item": "年均交易日偏低",
                            "detail": f"{annual_days:.0f} 天/年",
                            "deduction": 5,
                        })

            # 日期间隔检查（考虑A股周末和节假日）
            if valid_dates.any():
                sorted_dates = dates[valid_dates].sort_values()
                gaps = sorted_dates.diff().dt.days
                # 找出超过正常范围的间隔（含周末+节假日)
                large_gaps = gaps[gaps > self.thresholds.MAX_NORMAL_GAP]
                if len(large_gaps) > 0:
                    gap_count = len(large_gaps)
                    result["large_gaps"] = gap_count
                    max_gap = int(large_gaps.max())
                    result["max_gap_days"] = max_gap
                    if gap_count > 5:
                        deductions += min(gap_count * 2, 10)
                        result["alerts"].append({
                            "level": "warning", "item": "数据间隔过大",
                            "detail": f"{gap_count} 处间隔>{self.thresholds.MAX_NORMAL_GAP}天, 最大{max_gap}天",
                            "deduction": min(gap_count * 2, 10),
                        })

            # 重复日期
            if valid_dates.any():
                dup_dates = data[valid_dates].duplicated(subset=["date"]).sum()
                result["duplicate_dates"] = dup_dates
                if dup_dates > 0:
                    ded = min(dup_dates * 3, 15)
                    deductions += ded
                    result["alerts"].append({
                        "level": "error", "item": "重复日期",
                        "detail": f"{dup_dates} 个重复日期",
                        "deduction": ded,
                    })

        # ── 3. 缺失值检查 ──
        null_counts = data.isnull().sum()
        total_null = int(null_counts.sum())
        result["total_null"] = total_null
        null_ratio = total_null / (len(data) * len(data.columns)) if len(data) > 0 else 0
        result["null_ratio"] = round(null_ratio, 4)

        if null_ratio > self.thresholds.MAX_NULL_RATIO:
            deductions += 15
            result["alerts"].append({
                "level": "error", "item": "缺失率过高",
                "detail": f"{null_ratio:.1%} (> {self.thresholds.MAX_NULL_RATIO:.0%})",
                "deduction": 15,
            })

        # 逐列检查缺失
        null_cols = null_counts[null_counts > 0]
        high_null_cols = null_cols[null_cols / len(data) > 0.1]
        for col in high_null_cols.index:
            deductions += 5
            result["alerts"].append({
                "level": "warning", "item": f"列缺失: {col}",
                "detail": f"{int(null_counts[col])}/{len(data)} ({null_counts[col]/len(data):.1%})",
                "deduction": 5,
            })

        # ── 4. 价格合理性 ──
        price_cols = ["open", "close", "high", "low"]
        for col in price_cols:
            if col not in data.columns:
                continue
            vals = pd.to_numeric(data[col], errors="coerce")

            neg_count = (vals < 0).sum()
            if neg_count > 0:
                deductions += neg_count * 5
                result["alerts"].append({
                    "level": "error", "item": f"负价格: {col}",
                    "detail": f"{neg_count} 行价格为负",
                    "deduction": neg_count * 5,
                })

            zero_count = (vals == 0).sum()
            if zero_count > 0:
                result[f"{col}_zeros"] = zero_count

            # 价格异常值
            q1 = vals.quantile(0.25)
            q3 = vals.quantile(0.75)
            iqr = q3 - q1
            if iqr > 0:
                lower = q1 - self.thresholds.OUTLIER_IQR_MULT * iqr
                upper = q3 + self.thresholds.OUTLIER_IQR_MULT * iqr
                outlier_count = ((vals < lower) | (vals > upper)).sum()
                if outlier_count > len(vals) * 0.02:  # >2%
                    deductions += 5
                    result["alerts"].append({
                        "level": "warning", "item": f"价格异常值: {col}",
                        "detail": f"{outlier_count} 行 ({outlier_count/len(vals):.1%})",
                        "deduction": 5,
                    })

        # 价格关系检查 (high >= low, etc.)
        if all(c in data.columns for c in ["high", "low", "open", "close"]):
            high_lt_low = (data["high"] < data["low"]).sum()
            if high_lt_low > 0:
                deductions += high_lt_low * 3
                result["alerts"].append({
                    "level": "error", "item": "最高<最低",
                    "detail": f"{high_lt_low} 行",
                    "deduction": high_lt_low * 3,
                })

            # 价格超出范围
            outside_range = ((data["close"] > data["high"]) | (data["close"] < data["low"])).sum()
            if outside_range > 0:
                result["price_outside_range"] = outside_range

        # ── 5. 成交量检查（兼容腾讯数据：amount替代volume） ──
        col_vol = "volume" if "volume" in data.columns else "amount"
        has_vol_data = col_vol in data.columns

        if has_vol_data:
            vol_series = self._get_vol_series(data)
            zero_vol = (vol_series == 0).sum()
            stalled_ratio = zero_vol / len(data) if len(data) > 0 else 0
            result["zero_volume_days"] = zero_vol
            result["stalled_ratio"] = round(stalled_ratio, 4)

            if stalled_ratio > self.thresholds.MAX_STALLED_RATIO:
                deductions += 10
                result["alerts"].append({
                    "level": "warning", "item": "停牌率过高",
                    "detail": f"{zero_vol} 天 ({stalled_ratio:.1%})",
                    "deduction": 10,
                })

            # 成交量异常值（用成交额替代）
            vol_q1 = vol_series.quantile(0.25)
            vol_q3 = vol_series.quantile(0.75)
            vol_iqr = vol_q3 - vol_q1
            if vol_iqr > 0:
                vol_outliers = ((vol_series < vol_q1 - 5 * vol_iqr) | (vol_series > vol_q3 + 5 * vol_iqr)).sum()
                if vol_outliers > len(vol_series) * 0.03:
                    result["volume_outliers"] = vol_outliers

        # ── 6. 涨跌幅检查 ──
        if "close" in data.columns:
            if "pct_change" not in data.columns:
                pct = data["close"].pct_change(fill_method=None)
            else:
                pct = data["pct_change"]

            pct = pd.to_numeric(pct, errors="coerce")

            # 涨跌幅超过20%
            jump_mask = pct.abs() > self.thresholds.MAX_PRICE_JUMP
            jump_count = jump_mask.sum()
            result["price_jumps"] = jump_count
            if jump_count > 0:
                max_pct = pct[jump_mask].max() if jump_mask.any() else 0
                min_pct = pct[jump_mask].min() if jump_mask.any() else 0
                result["max_daily_change"] = round(max_pct, 4) if not pd.isna(max_pct) else 0
                result["min_daily_change"] = round(min_pct, 4) if not pd.isna(min_pct) else 0
                if jump_count > 3:
                    deductions += 5
                    result["alerts"].append({
                        "level": "warning", "item": "异常涨跌",
                        "detail": f"{jump_count} 次超{self.thresholds.MAX_PRICE_JUMP:.0%}, 最大{pct.max():.1%}",
                        "deduction": 5,
                    })

        # ── 7. 数据新鲜度 ──
        if "date" in data.columns:
            last_date = pd.to_datetime(data["date"]).max()
            days_since_update = (datetime.now() - last_date.to_pydatetime()).days
            result["days_since_update"] = days_since_update

            if days_since_update > 5:
                deductions += 5
                result["alerts"].append({
                    "level": "info", "item": "数据需要更新",
                    "detail": f"最后更新: {last_date.date()}, 距今{days_since_update}天",
                    "deduction": 5,
                })
            elif days_since_update > 30:
                deductions += 10
                result["alerts"].append({
                    "level": "warning", "item": "数据严重过期",
                    "detail": f"最后更新: {last_date.date()}, 距今{days_since_update}天",
                    "deduction": 10,
                })

        # ── 计算最终评分 ──
        score = max(0, 100 - deductions)
        grade = _grade_score(score)
        result["score"] = score
        result["grade"] = grade
        result["deductions"] = deductions
        result["passed"] = grade not in ("D", "F")

        self._results.append(result)
        return result

    def check_all(self, data_dict: Dict[str, pd.DataFrame]) -> List[Dict]:
        """批量检查所有股票"""
        self._results = []
        for symbol, df in data_dict.items():
            self.check_symbol(df, symbol)
        return self._results

    def get_results(self) -> List[Dict]:
        return list(self._results)

    def get_summary(self) -> Dict:
        """生成汇总统计"""
        if not self._results:
            return {}

        scores = [r.get("score", 0) for r in self._results]
        grades = [r.get("grade", "F") for r in self._results]
        passed = [r.get("passed", False) for r in self._results]

        grade_counts = {}
        for g in grades:
            grade_counts[g] = grade_counts.get(g, 0) + 1

        return {
            "total": len(self._results),
            "passed": sum(passed),
            "failed": sum(1 for p in passed if not p),
            "pass_rate": f"{sum(passed)/len(passed):.1%}" if passed else "0%",
            "avg_score": round(np.mean(scores), 1) if scores else 0,
            "min_score": min(scores) if scores else 0,
            "max_score": max(scores) if scores else 0,
            "grade_distribution": grade_counts,
            "total_alerts": sum(len(r.get("alerts", [])) for r in self._results),
            "check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


# ──────────────── 报告输出 ────────────────

def print_console_report(results: List[Dict], summary: Dict):
    """打印控制台报告（带颜色标记）"""
    print("\n" + "=" * 72)
    print("           数据质量检查报告")
    print("=" * 72)

    # 汇总
    print(f"\n  检查时间: {summary.get('check_time', 'N/A')}")
    print(f"  检查股票: {summary.get('total', 0)} 只")
    print(f"  通过: {summary.get('passed', 0)} / 失败: {summary.get('failed', 0)}")
    print(f"  通过率: {summary.get('pass_rate', '0%')}")
    print(f"  平均分: {summary.get('avg_score', 0)}")
    print(f"  等级分布: {summary.get('grade_distribution', {})}")

    print("\n" + "-" * 72)
    print(f"  {'代码':<8} {'评分':<6} {'等级':<4} {'行数':<6} {'日期范围':<24} {'告警':<6}")
    print("-" * 72)

    for r in sorted(results, key=lambda x: x.get("score", 0)):
        symbol = r.get("symbol", "?")
        score = r.get("score", 0)
        grade = r.get("grade", "?")
        rows = r.get("rows", 0)
        dr = f"{r.get('date_start', '?')}~{r.get('date_end', '?')}"
        alerts = len(r.get("alerts", []))
        passed = r.get("passed", True)
        marker = "[OK]" if passed else "[!!]"
        print(f"  {marker} {symbol:<8} {score:<6} {grade:<4} {rows:<6} {dr:<24} {alerts:<6}")

    print("-" * 72)

    # 告警详情
    alert_results = [r for r in results if r.get("alerts")]
    if alert_results:
        print(f"\n  告警详情 ({summary.get('total_alerts', 0)} 条):")
        for r in alert_results:
            for alert in r.get("alerts", []):
                level = alert.get("level", "info").ljust(7)
                item = alert.get("item", "?")
                detail = alert.get("detail", "")
                ded = alert.get("deduction", 0)
                print(f"    [{level}] {r['symbol']} - {item}: {detail} (扣{ded}分)")

    print("=" * 72 + "\n")


def generate_html_report(results: List[Dict], summary: Dict) -> str:
    """生成HTML格式的检查报告"""
    from datetime import datetime as dt

    now = dt.now().strftime("%Y-%m-%d %H:%M")

    # 表格行
    rows_html = ""
    for r in sorted(results, key=lambda x: x.get("score", 0)):
        symbol = r.get("symbol", "?")
        score = r.get("score", 0)
        grade = r.get("grade", "?")
        rows = r.get("rows", 0)
        dr = f"{r.get('date_start', '?')} ~ {r.get('date_end', '?')}"
        alerts_count = len(r.get("alerts", []))
        passed = r.get("passed", True)
        color = _grade_color(grade)
        status = "pass" if passed else "fail"

        # 告警tooltip
        alert_details = ""
        for alert in r.get("alerts", []):
            lvl = alert.get("level", "info")
            item = alert.get("item", "")
            detail = alert.get("detail", "")
            ded = alert.get("deduction", 0)
            icon = {"error": "X", "warning": "!", "info": "i"}.get(lvl, "?")
            alert_details += f'<tr class="alert-{lvl}"><td>{icon}</td><td>{item}</td><td>{detail}</td><td>-{ded}</td></tr>'

        if alert_details:
            alert_details = f'<table class="alert-table"><tr><th></th><th>项目</th><th>详情</th><th>扣分</th></tr>{alert_details}</table>'

        rows_html += f"""
        <tr class="grade-{status}">
            <td><strong>{symbol}</strong></td>
            <td style="text-align:right">{score}</td>
            <td style="color:{color};font-weight:bold">{grade}</td>
            <td style="text-align:right">{rows}</td>
            <td style="font-size:0.85em">{dr}</td>
            <td style="text-align:center">{alerts_count}</td>
            <td><div class="alert-tooltip">{'有告警' if alerts_count > 0 else '无'}
                {alert_details}
            </div></td>
        </tr>"""

    # 等级分布
    grade_dist = summary.get("grade_distribution", {})
    grade_bars = ""
    for g in ["A+", "A", "B", "C", "D", "F"]:
        count = grade_dist.get(g, 0)
        if count > 0:
            pct = count / summary["total"] * 100
            color = _grade_color(g)
            grade_bars += f"""
            <div style="margin:4px 0">
                <span style="display:inline-block;width:30px">{g}</span>
                <div style="display:inline-block;width:200px;height:20px;background:#eee;border-radius:3px;vertical-align:middle">
                    <div style="width:{pct}%;height:100%;background:{color};border-radius:3px"></div>
                </div>
                <span style="margin-left:8px">{count}只 ({pct:.0f}%)</span>
            </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>数据质量检查报告</title>
<style>
body {{ font-family: -apple-system, 'Segoe UI', sans-serif; margin: 20px; background: #f5f5f5; color: #333; }}
.container {{ max-width: 1200px; margin: auto; }}
.header {{ background: linear-gradient(135deg, #1a73e8, #0d47a1); color: white; padding: 24px; border-radius: 8px; margin-bottom: 20px; }}
.header h1 {{ margin: 0; font-size: 24px; }}
.header .meta {{ margin-top: 8px; opacity: 0.9; font-size: 14px; }}
.summary-cards {{ display: flex; gap: 16px; margin-bottom: 20px; }}
.card {{ background: white; padding: 16px 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); flex: 1; text-align: center; }}
.card .value {{ font-size: 28px; font-weight: bold; }}
.card .label {{ font-size: 12px; color: #666; margin-top: 4px; }}
.card.green .value {{ color: #00cc66; }}
.card.red .value {{ color: #ff3333; }}
.card.blue .value {{ color: #1a73e8; }}
table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
th {{ background: #f8f9fa; padding: 10px 8px; text-align: left; font-size: 12px; text-transform: uppercase; color: #666; border-bottom: 2px solid #dee2e6; }}
td {{ padding: 8px; border-bottom: 1px solid #eee; font-size: 14px; }}
tr.grade-fail {{ background: #fff5f5; }}
.alert-table {{ font-size: 12px; margin-top: 4px; background: #f8f9fa; border-radius: 4px; width: 100%; }}
.alert-table th {{ font-size: 11px; padding: 4px 6px; }}
.alert-table td {{ padding: 3px 6px; }}
.alert-error td {{ color: #cc0000; }}
.alert-warning td {{ color: #cc6600; }}
.alert-info td {{ color: #0066cc; }}
.alert-tooltip {{ position: relative; cursor: pointer; }}
.section {{ background: white; border-radius: 8px; padding: 16px 20px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.section h2 {{ margin: 0 0 12px 0; font-size: 18px; }}
.grade-dist {{ margin: 10px 0; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
    <h1>数据质量检查报告</h1>
    <div class="meta">检查时间: {now} | 报告生成: {dt.now().strftime('%Y-%m-%d %H:%M')}</div>
</div>

<div class="summary-cards">
    <div class="card blue">
        <div class="value">{summary.get('total', 0)}</div>
        <div class="label">检查股票数</div>
    </div>
    <div class="card green">
        <div class="value">{summary.get('passed', 0)}</div>
        <div class="label">通过</div>
    </div>
    <div class="card red">
        <div class="value">{summary.get('failed', 0)}</div>
        <div class="label">未通过</div>
    </div>
    <div class="card blue">
        <div class="value">{summary.get('avg_score', 0)}</div>
        <div class="label">平均分</div>
    </div>
    <div class="card blue">
        <div class="value">{summary.get('pass_rate', '0%')}</div>
        <div class="label">通过率</div>
    </div>
</div>

<div class="section">
    <h2>等级分布</h2>
    <div class="grade-dist">{grade_bars}</div>
</div>

<div class="section">
    <h2>逐只股票详情</h2>
    <table>
        <thead>
            <tr>
                <th>代码</th>
                <th>评分</th>
                <th>等级</th>
                <th>行数</th>
                <th>日期范围</th>
                <th>告警数</th>
                <th>详情</th>
            </tr>
        </thead>
        <tbody>{rows_html}</tbody>
    </table>
</div>

</div>
</body>
</html>"""
    return html


def save_json_report(results: List[Dict], summary: Dict, output_dir: str = "./reports"):
    """保存JSON格式报告"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "summary": summary,
        "results": results,
    }

    filepath = output_dir / "data_quality_report.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info(f"JSON报告已保存: {filepath}")
    return filepath


# ──────────────── 主入口 ────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="数据质量检查工具")
    parser.add_argument("--symbols", type=str, nargs="*", help="指定股票代码")
    parser.add_argument("--html", action="store_true", help="生成HTML报告")
    parser.add_argument("--json", action="store_true", help="生成JSON报告")
    parser.add_argument("--alert", action="store_true", help="仅显示告警项")
    parser.add_argument("--output", type=str, default="./reports", help="报告输出目录")
    args = parser.parse_args()

    setup_logger()
    config = get_config()
    collector = DataCollector(raw_dir=config.data.raw_dir)
    checker = DataQualityChecker()

    # 确定检查列表
    if args.symbols:
        symbols = args.symbols
    else:
        symbols = []
        for f in Path(collector.raw_dir).glob("*.parquet"):
            stem = f.stem
            if not stem.startswith("index_"):
                symbols.append(stem)
        symbols.sort()

    if not symbols:
        print("没有缓存数据，请先运行采集脚本")
        return

    print(f"\n开始检查 {len(symbols)} 只股票数据质量...\n")

    # 逐只检查
    results = []
    for symbol in symbols:
        df = collector.load_from_parquet(symbol)
        result = checker.check_symbol(df, symbol)
        results.append(result)

        # 控制台输出每只结果
        score = result.get("score", 0)
        grade = result.get("grade", "?")
        alerts = len(result.get("alerts", []))
        passed = result.get("passed", True)
        marker = "[OK]" if passed else "[!!]"
        print(f"  {marker} {symbol:<8} 评分={score:<5} 等级={grade:<2} 行数={result.get('rows', 0):<6} "
              f"告警={alerts} 日期={result.get('date_start','?')}")

    summary = checker.get_summary()

    # 输出汇总
    print_console_report(results, summary)

    # 可选：产出HTML报告
    if args.html:
        html = generate_html_report(results, summary)
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        filepath = output_dir / "data_quality_report.html"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  HTML报告已保存: {filepath}")

    if args.json:
        save_json_report(results, summary, args.output)

    # 退出码
    if summary.get("failed", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
