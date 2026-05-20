"""
Web 监控面板 — 主入口。

运行: cd d:/python/quant-trading && .venv/Scripts/python -m streamlit run web/app.py
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

import streamlit as st
import time

# st.set_page_config 必须在第一行，但避免在 bare import 时触发 warning
try:
    st.set_page_config(
        page_title="量化交易监控面板",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items=None,  # 隐藏右上角三个点菜单（全是英文）
    )
except Exception:
    pass

# ---------------------------------------------------------------------------
# Session state 初始化
# ---------------------------------------------------------------------------
for key, default in [
    ("page", "📊 总览"),
    ("refresh_interval", 5),
    ("auto_refresh", True),
    ("_last_refresh", time.time()),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# 隐藏 Streamlit 底部 "Made with Streamlit" 英文标签
st.markdown("""
<style>
footer {visibility: hidden;}
.stFooter {display: none;}
</style>
""", unsafe_allow_html=True)


def _auto_refresh():
    """自动刷新：每隔 refresh_interval 秒触发 rerun。"""
    now = time.time()
    elapsed = now - st.session_state._last_refresh
    if st.session_state.auto_refresh and elapsed >= st.session_state.refresh_interval:
        st.session_state._last_refresh = now
        st.rerun()


def _sidebar_status():
    """惰性加载引擎状态（避免模块 import 阶段触发 Streamlit context warning）。"""
    from web.state_reader import get_engine_state, has_engine
    return get_engine_state(), has_engine()


# ---------------------------------------------------------------------------
# 侧边栏
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("📊 监控面板")

    eng_state, eng_available = _sidebar_status()

    col1, col2 = st.columns(2)
    with col1:
        st.caption("引擎状态")
        from web.state_reader import cn_state
        state = eng_state.get("state", "UNKNOWN")
        state_cn = cn_state(state)
        if eng_available and state == "RUNNING":
            st.success(f"🟢 {state_cn}")
        elif eng_available and state in ("PAUSED",):
            st.warning(f"🟡 {state_cn}")
        elif eng_available or eng_state.get("source") == "snapshot":
            st.info(f"🔵 {state_cn}")
        else:
            st.error(f"🔴 {state_cn}")
    with col2:
        st.caption("数据源")
        src = eng_state.get("source", "none")
        if src == "live":
            st.success("实时")
        elif src == "snapshot":
            snap_time = eng_state.get("snap_time")
            if snap_time:
                from datetime import datetime
                try:
                    snap_dt = datetime.fromisoformat(snap_time)
                    age = (datetime.now() - snap_dt).total_seconds()
                    if age < 60:
                        st.success("近实时")
                        st.caption(f"更新: {snap_time.split()[1]}")
                    else:
                        st.info(f"快照")
                        st.caption(f"更新: {snap_time}")
                except Exception:
                    st.info("快照")
            else:
                st.info("快照")
        else:
            st.error("无数据")

    st.divider()

    # 刷新控制
    st.caption("刷新设置")
    st.session_state.auto_refresh = st.toggle("自动刷新", value=st.session_state.auto_refresh)
    st.session_state.refresh_interval = st.slider(
        "刷新间隔(秒)", 1, 60, st.session_state.refresh_interval,
        disabled=not st.session_state.auto_refresh,
    )
    if st.button("🔄 立即刷新"):
        st.rerun()

    st.divider()

    # 页面导航
    st.caption("页面导航")
    page_options = [
        "📊 总览",
        "💼 持仓",
        "📈 盈亏曲线",
        "📋 订单",
        "📊 K线图",
        "📝 日志",
        "🛡️ 风控",
        "🎮 控制",
    ]
    page_choice = st.radio(
        "跳转到",
        options=page_options,
        label_visibility="collapsed",
        key="page",
    )

    st.divider()
    remaining = max(0, int(st.session_state.refresh_interval - (time.time() - st.session_state._last_refresh)))
    st.caption(f"下次刷新: {remaining}秒")
    st.caption(f"更新时间: {time.strftime('%H:%M:%S')}")

# ---------------------------------------------------------------------------
# 页面路由 — 动态导入并调用 show()
# ---------------------------------------------------------------------------
_page_modules = {
    "📊 总览": "web.pages.overview",
    "💼 持仓": "web.pages.positions",
    "📈 盈亏曲线": "web.pages.pnl",
    "📋 订单": "web.pages.orders",
    "📊 K线图": "web.pages.kline",
    "📝 日志": "web.pages.logs",
    "🛡️ 风控": "web.pages.risk",
    "🎮 控制": "web.pages.controls",
}

import importlib
mod = importlib.import_module(_page_modules[page_choice])
if hasattr(mod, "show"):
    mod.show()

# ---------------------------------------------------------------------------
# 自动刷新
# ---------------------------------------------------------------------------
_auto_refresh()
