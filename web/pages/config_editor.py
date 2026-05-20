"""
Web 配置管理页面 — 查看和编辑系统全部配置。

配置存储在后端 SQLite (app_config 表)，敏感字段使用 Fernet 加密。
"""
from typing import Any, Dict
import json

import streamlit as st

# ────────── 字段元数据 ──────────

FIELD_META: Dict[str, Dict] = {
    # ── 交易网关 ──
    "live.gateway_name": {"tab": "🔌 交易网关", "label": "网关名称", "type": "text",
                          "help": "CTP 网关标识"},
    "live.environment": {"tab": "🔌 交易网关", "label": "CTP 环境", "type": "select",
                         "options": ["simnow", "simnow_7x24"],
                         "help": "simnow=交易时段, simnow_7x24=全天"},
    "live.broker_id": {"tab": "🔌 交易网关", "label": "Broker ID", "type": "text",
                       "help": "期货公司编号"},
    "live.user_id": {"tab": "🔌 交易网关", "label": "用户 ID", "type": "text"},
    "live.password": {"tab": "🔌 交易网关", "label": "密码", "type": "password"},
    "live.app_id": {"tab": "🔌 交易网关", "label": "App ID", "type": "text"},
    "live.auth_code": {"tab": "🔌 交易网关", "label": "认证码", "type": "password"},
    "live.td_address": {"tab": "🔌 交易网关", "label": "交易前置地址", "type": "text",
                        "help": "tcp://ip:port"},
    "live.md_address": {"tab": "🔌 交易网关", "label": "行情前置地址", "type": "text",
                        "help": "tcp://ip:port"},
    "live.real_mode": {"tab": "🔌 交易网关", "label": "实盘模式", "type": "boolean",
                       "help": "开启后连接真实 CTP，否则使用模拟模式"},

    # ── 交易参数 ──
    "live.initial_capital": {"tab": "📊 交易参数", "label": "初始资金 (¥)", "type": "number",
                             "format": "%.0f", "step": 100000},
    "live.contract_multiplier": {"tab": "📊 交易参数", "label": "合约乘数", "type": "number",
                                 "step": 1},
    "live.margin_rate": {"tab": "📊 交易参数", "label": "保证金比例", "type": "number",
                         "format": "%.4f"},
    "live.commission_open": {"tab": "📊 交易参数", "label": "开仓手续费率", "type": "number",
                             "format": "%.6f"},
    "live.commission_close": {"tab": "📊 交易参数", "label": "平仓手续费率", "type": "number",
                              "format": "%.6f"},
    "live.commission_close_today": {"tab": "📊 交易参数", "label": "平今手续费率", "type": "number",
                                    "format": "%.6f"},
    "live.slippage": {"tab": "📊 交易参数", "label": "滑点", "type": "number",
                      "format": "%.4f"},
    "live.bar_interval_minutes": {"tab": "📊 交易参数", "label": "K 线聚合间隔 (分钟)", "type": "number",
                                  "step": 1},
    "live.order_timeout_seconds": {"tab": "📊 交易参数", "label": "订单超时 (秒)", "type": "number",
                                   "step": 1},
    "live.max_retries": {"tab": "📊 交易参数", "label": "最大重试次数", "type": "number",
                         "step": 1},
    "live.reconnect_enabled": {"tab": "📊 交易参数", "label": "启用断线重连", "type": "boolean"},
    "live.reconnect_initial_delay": {"tab": "📊 交易参数", "label": "重连初始延迟 (秒)", "type": "number"},
    "live.reconnect_max_delay": {"tab": "📊 交易参数", "label": "重连最大延迟 (秒)", "type": "number"},
    "live.reconnect_max_attempts": {"tab": "📊 交易参数", "label": "最大重连次数 (0=无限)", "type": "number",
                                    "step": 1},
    "live.strategy_name": {"tab": "📊 交易参数", "label": "策略名称", "type": "select",
                          "options": ["DualMaCrossStrategy", "SimpleTrendStrategy",
                                      "MLTradingStrategy"]},
    "live.symbols": {"tab": "📊 交易参数", "label": "交易合约", "type": "text",
                     "help": "多个合约用逗号分隔, 如 RB2610,CU2606"},
    "backtest.initial_cash": {"tab": "📊 交易参数", "label": "回测初始资金 (¥)", "type": "number",
                              "format": "%.0f", "step": 100000},

    # ── 风控设置 ──
    "live.auto_reduce_enabled": {"tab": "🛡️ 风控设置", "label": "启用自动减仓", "type": "boolean"},
    "live.auto_reduce_trigger_ratio": {"tab": "🛡️ 风控设置", "label": "减仓触发风险度", "type": "number",
                                       "format": "%.2f"},
    "live.auto_reduce_target_ratio": {"tab": "🛡️ 风控设置", "label": "减仓目标风险度", "type": "number",
                                      "format": "%.2f"},
    "live.flat_all_trigger_ratio": {"tab": "🛡️ 风控设置", "label": "全平触发风险度", "type": "number",
                                    "format": "%.2f"},
    "live.cancel_monitor_enabled": {"tab": "🛡️ 风控设置", "label": "启用报撤单监控", "type": "boolean"},
    "live.max_cancels_per_minute": {"tab": "🛡️ 风控设置", "label": "每分钟最大撤单数", "type": "number",
                                    "step": 1},
    "live.max_cancel_ratio": {"tab": "🛡️ 风控设置", "label": "报撤比阈值", "type": "number",
                              "format": "%.2f"},
    "live.cancel_ratio_window_minutes": {"tab": "🛡️ 风控设置", "label": "报撤比统计窗口 (分钟)", "type": "number",
                                         "step": 1},
    "live.large_order_volume": {"tab": "🛡️ 风控设置", "label": "大额定单手数阈值", "type": "number",
                                "step": 1},
    "strategy.stop_loss": {"tab": "🛡️ 风控设置", "label": "策略止损比例", "type": "number",
                           "format": "%.2f"},
    "strategy.take_profit": {"tab": "🛡️ 风控设置", "label": "策略止盈比例", "type": "number",
                             "format": "%.2f"},
    "strategy.max_position": {"tab": "🛡️ 风控设置", "label": "最大仓位比例", "type": "number",
                              "format": "%.2f"},

    # ── OI 主力追踪 ──
    "live.oi_tracker_enabled": {"tab": "🛡️ 风控设置", "label": "启用主力合约追踪", "type": "boolean"},
    "live.oi_threshold_ratio": {"tab": "🛡️ 风控设置", "label": "OI 领先阈值", "type": "number",
                                "format": "%.2f"},
    "live.oi_confirmation_count": {"tab": "🛡️ 风控设置", "label": "OI 确认次数", "type": "number",
                                   "step": 1},
    "live.oi_check_interval_seconds": {"tab": "🛡️ 风控设置", "label": "OI 检测间隔 (秒)", "type": "number",
                                       "step": 1},
    "live.oi_snapshot_interval_seconds": {"tab": "🛡️ 风控设置", "label": "OI 快照间隔 (秒)", "type": "number",
                                          "step": 1},

    # ── 通知 ──
    "notify.enabled": {"tab": "🔔 通知与调度", "label": "启用通知", "type": "boolean"},
    "notify.dingtalk_webhook": {"tab": "🔔 通知与调度", "label": "钉钉 Webhook URL", "type": "password"},
    "notify.dingtalk_secret": {"tab": "🔔 通知与调度", "label": "钉钉签名 Secret", "type": "password"},
    "notify.notify_on_error": {"tab": "🔔 通知与调度", "label": "错误时通知", "type": "boolean"},
    "notify.notify_on_success": {"tab": "🔔 通知与调度", "label": "成功时通知", "type": "boolean"},

    # ── 调度 ──
    "schedule.enabled": {"tab": "🔔 通知与调度", "label": "启用定时任务", "type": "boolean"},
    "schedule.run_time": {"tab": "🔔 通知与调度", "label": "每日执行时间", "type": "text",
                          "help": "HH:MM 格式"},
    "schedule.max_workers": {"tab": "🔔 通知与调度", "label": "并发采集数", "type": "number",
                             "step": 1},
    "schedule.incremental": {"tab": "🔔 通知与调度", "label": "增量更新", "type": "boolean"},

    # ── 系统设置 ──
    "ai.model_dir": {"tab": "🔧 系统设置", "label": "AI 模型目录", "type": "text"},
    "ai.train_test_split": {"tab": "🔧 系统设置", "label": "AI 训练集比例", "type": "number",
                            "format": "%.2f"},
    "ai.random_state": {"tab": "🔧 系统设置", "label": "AI 随机种子", "type": "number",
                        "step": 1},
    "data.source": {"tab": "🔧 系统设置", "label": "数据源", "type": "text"},
    "data.cache_dir": {"tab": "🔧 系统设置", "label": "缓存目录", "type": "text"},
    "data.default_start_date": {"tab": "🔧 系统设置", "label": "默认起始日期", "type": "text"},
    "data.default_end_date": {"tab": "🔧 系统设置", "label": "默认截止日期", "type": "text"},
    "logging.level": {"tab": "🔧 系统设置", "label": "日志级别", "type": "select",
                      "options": ["DEBUG", "INFO", "WARNING", "ERROR"]},
}

# 按 tab 分组
_TABS = ["🔌 交易网关", "📊 交易参数", "🛡️ 风控设置", "🔔 通知与调度", "🔧 系统设置"]
_FIELDS_BY_TAB = {tab: [] for tab in _TABS}
for key, meta in FIELD_META.items():
    _FIELDS_BY_TAB[meta["tab"]].append(key)


def _render_field(key: str, meta: Dict, current_value: Any):
    """渲染单个配置字段的编辑控件。"""
    label = f"{meta['label']} (`{key}`)"
    default_help = meta.get("help", "")

    ftype = meta["type"]

    if ftype == "boolean":
        bool_val = bool(current_value) if current_value is not None else False
        return st.checkbox(label, value=bool_val, key=key, help=default_help)

    if ftype == "select":
        options = meta.get("options", [])
        str_val = str(current_value) if current_value is not None else options[0]
        current_idx = options.index(str_val) if str_val in options else 0
        return st.selectbox(label, options=options, index=current_idx,
                            key=key, help=default_help)

    if ftype == "password":
        str_val = str(current_value) if current_value is not None else ""
        return st.text_input(label, value=str_val, key=key, type="password",
                             help=default_help)

    if ftype == "number":
        fmt = meta.get("format", "%.4f")
        step = float(meta.get("step", 0.01))
        float_val = float(current_value) if current_value is not None else 0.0
        min_val = meta.get("min", None)
        max_val = meta.get("max", None)
        return st.number_input(label, value=float_val, format=fmt, step=step,
                               min_value=float(min_val) if min_val is not None else None,
                               max_value=float(max_val) if max_val is not None else None,
                               key=key, help=default_help)

    # 默认：text
    str_val = str(current_value) if current_value is not None else ""
    return st.text_input(label, value=str_val, key=key, help=default_help)


def _collect_save_values() -> Dict[str, Any]:
    """从 session_state 收集所有修改过的字段值。"""
    values = {}
    for key in FIELD_META:
        if key in st.session_state:
            values[key] = st.session_state[key]
    return values


def show():
    from src.core.config_store import ConfigStore
    from src.core.config import get_config, reload_config

    st.header("⚙️ 系统配置")

    # 加载当前配置
    store = ConfigStore()
    config = get_config()
    db_config = store.get_all()

    tab_objects = st.tabs(_TABS)
    all_modified = {}

    for tab_idx, tab_name in enumerate(_TABS):
        with tab_objects[tab_idx]:
            keys = _FIELDS_BY_TAB[tab_name]
            if not keys:
                st.info("该分类暂无配置项")
                continue

            for key in keys:
                meta = FIELD_META[key]
                # 优先从 DB 加载，其次从 Config 对象获取
                current = db_config.get(key)
                if current is None:
                    # 从 Config 对象提取
                    parts = key.split(".", 1)
                    if len(parts) == 2:
                        section = getattr(config, parts[0], None)
                        if section:
                            current = getattr(section, parts[1], None)
                _render_field(key, meta, current)

    # ── 操作按钮 ──
    st.divider()
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("💾 保存到数据库", type="primary", use_container_width=True):
            try:
                values = _collect_save_values()
                for key, value in values.items():
                    store.set(key, value)
                reload_config()
                st.toast(f"✅ 配置已保存 ({len(values)} 项)", icon="✅")
                st.rerun()
            except Exception as e:
                st.error(f"保存失败: {e}")

    with col2:
        if st.button("🔄 从数据库重载", use_container_width=True):
            reload_config()
            st.toast("配置已从数据库重载", icon="🔄")
            st.rerun()

    with col3:
        with st.popover("⚠️ 恢复出厂设置"):
            st.warning("此操作将清空所有自定义配置，恢复为系统默认值。")
            confirm = st.checkbox("我已确认，执行恢复")
            if confirm and st.button("确认恢复默认值", type="primary"):
                store.clear()
                store.migrate_from_yaml()
                reload_config()
                st.toast("已恢复为默认值", icon="✅")
                st.rerun()
