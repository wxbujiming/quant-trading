"""
快速查看交易状态

用法:
    python scripts/status.py           # 查看当前持仓、信号和引擎状态
    python scripts/status.py --watch   # 持续监控（每 5 秒刷新）
"""
import sys
import time
import json
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import get_config


def read_live_state():
    """读取最新状态文件"""
    state_dir = Path("./data/live_state")
    today = datetime.now().strftime("%Y%m%d")
    state_file = state_dir / f"live_state_{today}.json"
    if state_file.exists():
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def read_equity():
    """读取权益历史"""
    equity_file = Path("./data/live_state/equity_history.csv")
    if equity_file.exists():
        lines = equity_file.read_text(encoding="utf-8").strip().split("\n")
        if len(lines) > 1:
            last = lines[-1].split(",")
            return last
    return None


def show_status():
    config = get_config()
    state = read_live_state()

    print("=" * 50)
    print(f"  量化交易状态  ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print("=" * 50)

    if state:
        print(f"\n引擎状态:  {state.get('state', 'N/A')}")
        print(f"交易日:    {state.get('trading_day', 'N/A')}")
        print(f"更新时间:  {state.get('timestamp', 'N/A')}")

        account = state.get("account", {})
        if account:
            print(f"\n账户:")
            print(f"  余额:     {account.get('balance', 0):>12,.0f}")
            print(f"  可用:     {account.get('available', 0):>12,.0f}")
            print(f"  保证金:   {account.get('margin', 0):>12,.0f}")
            print(f"  浮动盈亏: {account.get('pnl', 0):>+12,.0f}")

        positions = state.get("positions", [])
        if positions:
            print(f"\n持仓 ({len(positions)} 个):")
            for p in positions:
                side = "多" if p.get("direction") == "BUY" else "空"
                print(f"  {p['symbol']}  {side}  {p['volume']}手  "
                      f"均价{p['price']:>.1f}  PnL={p.get('pnl',0):+,.0f}")
        else:
            print(f"\n持仓: 无")

        pending = state.get("pending_orders", [])
        if pending:
            print(f"\n挂单 ({len(pending)} 个):")
            for o in pending:
                print(f"  {o['symbol']}  {o['direction']}  {o['volume']}手  "
                      f"@{o['price']}  status={o['status']}")

    else:
        print("\n无状态文件（引擎可能未运行）")

    print(f"\n品种: {config.live.symbols}")
    print(f"策略: {config.live.strategy_name}")
    print(f"参数: {config.live.strategy_params}")

    # 日志最新交易信号
    log_file = Path("logs/live_engine.log")
    if log_file.exists():
        content = log_file.read_text(encoding="utf-8", errors="ignore")
        # 查找最新的开平仓记录
        trades = []
        for line in content.split("\n"):
            if any(kw in line for kw in ["开多", "开空", "平多", "平空", "止损", "成交", "引擎心跳"]):
                trades.append(line)
        if trades:
            print(f"\n最近活动 (最新 5 条):")
            for t in trades[-5:]:
                # 提取时间戳和消息
                parts = t.split(" - ", 1)
                if len(parts) > 1:
                    t_msg = "|".join(parts[-1].split("|")[-1:]).strip()
                    print(f"  {parts[0][:19]}  {t_msg[:80]}")


def watch_loop(interval=5):
    try:
        while True:
            show_status()
            print(f"\n--- 每 {interval} 秒刷新 (Ctrl+C 退出) ---")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n退出监控")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="查看交易状态")
    parser.add_argument("--watch", action="store_true", help="持续监控模式")
    args = parser.parse_args()

    if args.watch:
        watch_loop()
    else:
        show_status()
