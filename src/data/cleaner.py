"""
数据清洗模块
提供缺失值处理、异常值过滤、标准化等数据清洗功能
"""
from typing import Optional, List, Dict, Union, Callable
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from loguru import logger


class DataCleaner:
    """
    数据清洗器
    
    包含缺失值处理、异常值检测、列名标准化、重复值处理、
    停牌/涨跌停过滤、数据质量报告等通用清洗流程。
    
    用法:
        cleaner = DataCleaner()
        df = cleaner.clean(df, stock_code="000001")
    """

    # 标准列名映射（中→英）
    CN_COLUMN_MAP = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "振幅": "amplitude",
        "涨跌幅": "pct_change",
        "涨跌额": "change",
        "换手率": "turnover",
        "开盘价": "open",
        "收盘价": "close",
        "最高价": "high",
        "最低价": "low",
        "股票代码": "symbol",
        "代码": "symbol",
        "名称": "name",
    }

    def __init__(
        self,
        fill_method: str = "ffill",
        outlier_method: str = "iqr",
        outlier_iqr_mult: float = 3.0,
        max_null_ratio: float = 0.2,
        min_days: int = 20,
    ):
        """
        初始化清洗器

        Args:
            fill_method: 缺失值填充方法 ("ffill"|"bfill"|"interpolate"|"drop"|"mean")
            outlier_method: 异常值检测方法 ("iqr"|"zscore"|"percentile")
            outlier_iqr_mult: IQR倍数阈值 (默认3.0)
            max_null_ratio: 单列最大允许缺失率 (默认20%)
            min_days: 最小有效交易日数 (默认20天)
        """
        self.fill_method = fill_method
        self.outlier_method = outlier_method
        self.outlier_iqr_mult = outlier_iqr_mult
        self.max_null_ratio = max_null_ratio
        self.min_days = min_days

        self._report: Dict[str, Union[int, float, str]] = {}

    # ──────────────── 主入口 ────────────────

    def clean(
        self,
        df: pd.DataFrame,
        stock_code: Optional[str] = None,
        standardize_columns: bool = True,
        remove_duplicates: bool = True,
        sort_by_date: bool = True,
        fill_missing: bool = True,
        remove_outliers: bool = True,
        filter_trading_days: bool = True,
        filter_stalled: bool = True,
    ) -> pd.DataFrame:
        """
        全流程数据清洗

        Args:
            df: 原始DataFrame
            stock_code: 股票代码（用于日志）
            standardize_columns: 是否标准化列名
            remove_duplicates: 是否去重
            sort_by_date: 是否按日期排序
            fill_missing: 是否填充缺失值
            remove_outliers: 是否过滤异常值
            filter_trading_days: 是否过滤非交易日
            filter_stalled: 是否过滤停牌段

        Returns:
            清洗后的DataFrame
        """
        code = stock_code or df.get("symbol", [""])[0] if "symbol" in df.columns else "unknown"
        original_rows = len(df)
        self._report = {"股票代码": code, "原始行数": original_rows}

        if df.empty:
            logger.warning(f"[{code}] 数据为空，跳过清洗")
            return df

        data = df.copy()

        # 1. 标准化列名
        if standardize_columns:
            data = self.standardize_columns(data)

        # 2. 去重
        if remove_duplicates:
            data = self.remove_duplicates(data)

        # 3. 按日期排序
        if sort_by_date and "date" in data.columns:
            data = self.sort_by_date(data)

        # 4. 过滤非交易日
        if filter_trading_days and "date" in data.columns and "volume" in data.columns:
            data = self.filter_non_trading_days(data)

        # 5. 过滤停牌段
        if filter_stalled and "volume" in data.columns and "close" in data.columns:
            data = self.filter_stalled_periods(data)

        # 6. 填充缺失值
        if fill_missing:
            data = self.fill_missing_values(data)

        # 7. 过滤异常值
        if remove_outliers:
            data = self.remove_outliers(data)

        # 8. 最终检查
        data = self._final_cleanup(data)

        cleaned_rows = len(data)
        self._report["清洗后行数"] = cleaned_rows
        self._report["删除行数"] = original_rows - cleaned_rows
        self._report["删除比例"] = f"{(original_rows - cleaned_rows) / original_rows:.1%}" if original_rows > 0 else "0%"

        logger.info(
            f"[{code}] 清洗完成: {original_rows} → {cleaned_rows} 行 "
            f"(删除 {original_rows - cleaned_rows} 行, "
            f"{self._report['删除比例']})"
        )
        return data

    # ──────────────── 单步清洗 ────────────────

    def standardize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化列名为英文"""
        data = df.copy()
        rename_map = {k: v for k, v in self.CN_COLUMN_MAP.items() if k in data.columns}
        if rename_map:
            data = data.rename(columns=rename_map)
            logger.debug(f"列名标准化: {list(rename_map.keys())} → {list(rename_map.values())}")
        return data

    def remove_duplicates(self, df: pd.DataFrame) -> pd.DataFrame:
        """去除重复行（基于日期+代码）"""
        before = len(df)
        if "date" in df.columns:
            subset = ["date"]
            if "symbol" in df.columns:
                subset.append("symbol")
            data = df.drop_duplicates(subset=subset, keep="first")
        else:
            data = df.drop_duplicates()

        removed = before - len(data)
        if removed > 0:
            logger.debug(f"去重: 删除 {removed} 条重复数据")
        return data

    def sort_by_date(self, df: pd.DataFrame) -> pd.DataFrame:
        """按日期升序排序"""
        if "date" not in df.columns:
            return df
        data = df.copy()
        data["date"] = pd.to_datetime(data["date"])
        data = data.sort_values("date").reset_index(drop=True)
        return data

    def filter_non_trading_days(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        过滤非交易日（成交量为0或NaN的日期）
        但保留数据两端的前后非交易日以维持连续性
        """
        if "volume" not in df.columns:
            return df

        data = df.copy()
        before = len(data)

        # 将成交量转换为数值
        data["volume"] = pd.to_numeric(data["volume"], errors="coerce")

        # 找出成交量>0的有效交易日
        valid_mask = data["volume"] > 0

        # 如果有效数据太少，不做过滤
        if valid_mask.sum() < self.min_days:
            logger.warning(f"有效交易日 {valid_mask.sum()} < {self.min_days}，跳过过滤非交易日")
            return data

        # 找到第一个和最后一个有效交易日，只剔除中间的零成交日
        first_valid = valid_mask.idxmax() if valid_mask.any() else 0
        last_valid = data.index[valid_mask].max() if valid_mask.any() else len(data) - 1

        # 在首尾有效交易日之间，剔除零成交日
        mask = pd.Series(True, index=data.index)
        mask.iloc[first_valid : last_valid + 1] = valid_mask.iloc[first_valid : last_valid + 1]

        data = data[mask].reset_index(drop=True)
        removed = before - len(data)

        if removed > 0:
            logger.debug(f"过滤非交易日: 删除 {removed} 条零成交记录")
        return data

    def filter_stalled_periods(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        过滤停牌期（连续多日成交量极低或价格不变）
        
        规则:
        - 连续5个以上交易日成交量为0 → 视为停牌，整段删除
        - 连续3个以上交易日涨跌幅为0且成交量<10手 → 视为流动性枯竭，整段删除
        """
        if "volume" not in df.columns or "close" not in df.columns:
            return df

        data = df.copy()
        before = len(data)

        # 标记可能的停牌日
        stalled = pd.Series(False, index=data.index)

        if "pct_change" not in data.columns:
            data["pct_change"] = data["close"].pct_change(fill_method=None)

        # 条件1: 成交量为0或NaN
        vol_zero = data["volume"].fillna(0) <= 0

        # 条件2: 涨跌幅为0且成交量<1000股(10手)
        low_liquidity = (
            data["pct_change"].fillna(0).abs() < 0.0001
        ) & (data["volume"].fillna(0) < 1000)

        # 查找连续停牌段
        for condition, min_streak in [(vol_zero, 5), (low_liquidity, 3)]:
            streak = 0
            for i in range(len(data)):
                if condition.iloc[i]:
                    streak += 1
                    if streak >= min_streak:
                        # 标记整个停牌段
                        stalled.iloc[i - streak + 1 : i + 1] = True
                else:
                    streak = 0

        # 但保留数据首尾各20个交易日（确保回测有足够预热数据）
        keep_head = min(20, len(data) // 4)
        keep_tail = min(20, len(data) // 4)
        if keep_head > 0:
            stalled.iloc[:keep_head] = False
        if keep_tail > 0:
            stalled.iloc[-keep_tail:] = False

        data = data[~stalled].reset_index(drop=True)
        removed = before - len(data)

        if removed > 0:
            logger.debug(f"过滤停牌期: 删除 {removed} 条停牌/流动性枯竭记录")

        return data

    def fill_missing_values(self, df: pd.DataFrame) -> pd.DataFrame:
        """填充缺失值"""
        data = df.copy()
        report_before = data.isnull().sum().sum()

        # 获取数值列
        numeric_cols = data.select_dtypes(include=[np.number]).columns.tolist()
        # 排除某些列不做填充
        skip_cols = {"year", "month", "day"}
        target_cols = [c for c in numeric_cols if c not in skip_cols]

        for col in target_cols:
            null_count = data[col].isnull().sum()
            if null_count == 0:
                continue

            null_ratio = null_count / len(data)
            if null_ratio > self.max_null_ratio:
                logger.warning(f"  列 '{col}' 缺失率 {null_ratio:.1%} > {self.max_null_ratio:.0%}，整列填充为0")
                data[col] = data[col].fillna(0)
                continue

            if self.fill_method == "ffill":
                data[col] = data[col].ffill()
                # 如果开头还有缺失，用bfill
                if data[col].isnull().any():
                    data[col] = data[col].bfill()
            elif self.fill_method == "bfill":
                data[col] = data[col].bfill()
                if data[col].isnull().any():
                    data[col] = data[col].ffill()
            elif self.fill_method == "interpolate":
                data[col] = data[col].interpolate(method="linear")
                data[col] = data[col].ffill().bfill()
            elif self.fill_method == "mean":
                data[col] = data[col].fillna(data[col].mean())
            elif self.fill_method == "drop":
                data = data.dropna(subset=[col])

        report_after = data.isnull().sum().sum()
        filled = report_before - report_after
        if filled > 0:
            logger.debug(f"缺失值填充: 共填充 {filled} 个缺失值")

        return data

    def remove_outliers(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        过滤异常值
        
        对 price/volume/amount 等列进行异常值检测
        """
        data = df.copy()
        before = len(data)

        outlier_cols = ["open", "close", "high", "low", "volume", "amount"]
        target_cols = [c for c in outlier_cols if c in data.columns]

        outlier_mask = pd.Series(False, index=data.index)

        for col in target_cols:
            col_data = pd.to_numeric(data[col], errors="coerce")
            col_data = col_data.fillna(col_data.median())

            if self.outlier_method == "iqr":
                q1 = col_data.quantile(0.25)
                q3 = col_data.quantile(0.75)
                iqr = q3 - q1
                lower = q1 - self.outlier_iqr_mult * iqr
                upper = q3 + self.outlier_iqr_mult * iqr
                col_outliers = (col_data < lower) | (col_data > upper)

            elif self.outlier_method == "zscore":
                mean = col_data.mean()
                std = col_data.std()
                if std > 0:
                    zscores = (col_data - mean) / std
                    col_outliers = zscores.abs() > 3
                else:
                    col_outliers = pd.Series(False, index=data.index)

            elif self.outlier_method == "percentile":
                p01 = col_data.quantile(0.01)
                p99 = col_data.quantile(0.99)
                col_outliers = (col_data < p01) | (col_data > p99)

            else:
                col_outliers = pd.Series(False, index=data.index)

            outlier_mask = outlier_mask | col_outliers

        data = data[~outlier_mask].reset_index(drop=True)
        removed = before - len(data)
        if removed > 0:
            logger.debug(f"异常值过滤: 删除 {removed} 条异常记录")

        return data

    def _final_cleanup(self, df: pd.DataFrame) -> pd.DataFrame:
        """最终清理：确保数据类型正确"""
        data = df.copy()

        # 确保日期列是datetime
        if "date" in data.columns:
            data["date"] = pd.to_datetime(data["date"], errors="coerce")
            # 删除日期解析失败的行
            bad_dates = data["date"].isnull()
            if bad_dates.any():
                data = data[~bad_dates].reset_index(drop=True)
                logger.debug(f"删除 {bad_dates.sum()} 条日期无效记录")

        # 确保数值列是数值类型
        numeric_cols = ["open", "close", "high", "low", "volume", "amount",
                        "pct_change", "amplitude", "turnover"]
        for col in numeric_cols:
            if col in data.columns:
                data[col] = pd.to_numeric(data[col], errors="coerce")

        # 确保收盘价>0，无效则删除
        if "close" in data.columns:
            invalid_price = data["close"].isnull() | (data["close"] <= 0)
            if invalid_price.any():
                data = data[~invalid_price].reset_index(drop=True)
                logger.debug(f"删除 {invalid_price.sum()} 条无效价格记录")

        return data

    # ──────────────── 报告 ────────────────

    def get_report(self) -> Dict[str, Union[int, float, str]]:
        """获取最近一次清洗报告"""
        return dict(self._report)

    def print_report(self):
        """打印清洗报告"""
        if not self._report:
            print("暂无清洗报告，请先运行 clean()")
            return
        print("\n" + "=" * 50)
        print(f"         数据清洗报告 - {self._report.get('股票代码', 'N/A')}")
        print("=" * 50)
        for k, v in self._report.items():
            print(f"  {k}: {v}")
        print("=" * 50 + "\n")

    # ──────────────── 数据质量检查工具 ────────────────

    def quality_report(self, df: pd.DataFrame) -> Dict[str, Union[int, float, str]]:
        """
        生成数据质量报告（不修改数据）

        Returns:
            包含各项质量指标的字典
        """
        if df.empty:
            return {"error": "数据为空"}

        report = {
            "总行数": len(df),
            "总列数": len(df.columns),
            "列名": list(df.columns),
        }

        # 缺失值统计
        null_counts = df.isnull().sum()
        null_cols = null_counts[null_counts > 0]
        report["缺失值总数"] = int(null_counts.sum())
        if not null_cols.empty:
            report["缺失列详情"] = {
                col: {"缺失数": int(null_counts[col]), "缺失率": f"{null_counts[col] / len(df):.1%}"}
                for col in null_cols.index
            }

        # 日期范围
        if "date" in df.columns:
            dates = pd.to_datetime(df["date"], errors="coerce")
            report["日期范围"] = f"{dates.min().date()} ~ {dates.max().date()}"
            report["交易日数"] = len(dates.unique())

        # 重复值
        if "date" in df.columns:
            dup = df.duplicated(subset=["date"]).sum()
            report["重复日期数"] = int(dup)

        # 价格检查
        for col in ["open", "close", "high", "low"]:
            if col in df.columns:
                vals = pd.to_numeric(df[col], errors="coerce")
                report[f"{col}_最小值"] = round(vals.min(), 2)
                report[f"{col}_最大值"] = round(vals.max(), 2)
                report[f"{col}_NaN数"] = int(vals.isnull().sum())

        # 停牌天数
        if "volume" in df.columns:
            vol = pd.to_numeric(df["volume"], errors="coerce")
            zero_vol = (vol == 0).sum()
            report["零成交天数"] = int(zero_vol)

        # 涨跌幅范围
        if "pct_change" in df.columns:
            pct = pd.to_numeric(df["pct_change"], errors="coerce")
            report["涨跌幅范围"] = f"{pct.min():.2%} ~ {pct.max():.2%}"

        return report

    # ──────────────── 批量清洗 ────────────────

    def clean_batch(
        self,
        data_dict: Dict[str, pd.DataFrame],
        **kwargs,
    ) -> Dict[str, pd.DataFrame]:
        """
        批量清洗多只股票数据

        Args:
            data_dict: {股票代码: DataFrame}
            **kwargs: 传递给 clean() 的参数

        Returns:
            {股票代码: 清洗后DataFrame}
        """
        results = {}
        total = len(data_dict)

        logger.info(f"开始批量清洗 {total} 只股票...")
        for i, (code, df) in enumerate(data_dict.items(), 1):
            results[code] = self.clean(df, stock_code=code, **kwargs)
            if i % 10 == 0:
                logger.info(f"批量清洗进度: [{i}/{total}]")

        logger.success(f"批量清洗完成: {total} 只")
        return results


def quick_clean(df: pd.DataFrame, stock_code: Optional[str] = None) -> pd.DataFrame:
    """
    快速清洗（使用默认参数）

    Args:
        df: 原始DataFrame
        stock_code: 股票代码

    Returns:
        清洗后的DataFrame
    """
    cleaner = DataCleaner()
    return cleaner.clean(df, stock_code=stock_code)
