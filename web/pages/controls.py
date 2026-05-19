"""
手动控制 — 引擎操作按钮（暂停/恢复/停止/全平/撤单）。
"""

import streamlit as st


def show():
    from web.state_reader import is_engine_recent, get_engine_state, execute_engine_command

    st.header("🎮 手动控制")

    eng_available = is_engine_recent(max_age=120)
    eng_state = get_engine_state()
    state = eng_state.get("state", "UNKNOWN")

    if not eng_available:
        st.warning("⚠️ 引擎未运行")
        st.info(
            "请先启动引擎：\n\n"
            "```\n.venv/Scripts/python scripts/run_live_engine.py\n```\n\n"
            "启动后刷新本页面即可发送命令。"
        )
        return

    # --------------------------------------------------------------
    # 状态显示
    # --------------------------------------------------------------
    st.subheader("引擎状态")
    from web.state_reader import cn_state
    state_color = "🟢" if state == "RUNNING" else "🟡" if state == "PAUSED" else "🔴"
    st.info(f"当前状态: {state_color} **{cn_state(state)}**")

    # --------------------------------------------------------------
    # 操作按钮
    # --------------------------------------------------------------
    st.subheader("操作")

    col1, col2, col3 = st.columns(3)

    with col1:
        if state == "RUNNING":
            if st.button("⏸️ 暂停策略", type="secondary", use_container_width=True):
                with st.spinner("正在暂停..."):
                    result = execute_engine_command("pause")
                if result.get("success"):
                    st.success(result.get("message"))
                else:
                    st.error(result.get("message"))
                st.rerun()

        elif state == "PAUSED":
            if st.button("▶️ 恢复策略", type="primary", use_container_width=True):
                with st.spinner("正在恢复..."):
                    result = execute_engine_command("resume")
                if result.get("success"):
                    st.success(result.get("message"))
                else:
                    st.error(result.get("message"))
                st.rerun()

        else:
            st.button("⏸️ 暂停策略", disabled=True, use_container_width=True)

    with col2:
        if state in ("RUNNING", "PAUSED", "ERROR"):
            if st.button("🛑 停止引擎", type="secondary", use_container_width=True):
                with st.spinner("正在停止..."):
                    result = execute_engine_command("stop")
                if result.get("success"):
                    st.success(result.get("message"))
                else:
                    st.error(result.get("message"))
                st.rerun()
        else:
            st.button("🛑 停止引擎", disabled=True, use_container_width=True)

    with col3:
        st.button("🔄 刷新状态", use_container_width=True)

    # --------------------------------------------------------------
    # 危险操作区
    # --------------------------------------------------------------
    st.divider()
    st.subheader("⚠️ 危险操作")

    col_a, col_b = st.columns(2)

    with col_a:
        # 全平持仓（需二次确认）
        with st.popover("🔥 全平所有持仓", disabled=state not in ("RUNNING", "PAUSED")):
            st.warning("此操作将平掉所有持仓，且不可撤销！")
            confirm = st.checkbox("我已确认，执行全平")
            if confirm:
                if st.button("确认执行全平", type="primary", use_container_width=True):
                    with st.spinner("正在全平..."):
                        result = execute_engine_command("close_all")
                    if result.get("success"):
                        st.success(result.get("message"))
                    else:
                        st.error(result.get("message"))
                    st.rerun()

    with col_b:
        # 取消所有活跃订单
        with st.popover("❌ 取消所有活跃订单", disabled=state not in ("RUNNING", "PAUSED")):
            st.warning("将取消所有未成交和部分成交的订单。")
            confirm2 = st.checkbox("我已确认，取消所有订单")
            if confirm2:
                if st.button("确认执行撤单", type="secondary", use_container_width=True):
                    with st.spinner("正在撤单..."):
                        result = execute_engine_command("cancel_all")
                    if result.get("success"):
                        st.success(result.get("message"))
                    else:
                        st.error(result.get("message"))
                    st.rerun()


if __name__ == "__main__":
    show()
