"""
配置迁移脚本 — 将 secrets.yaml 中的配置迁移到 SQLite（加密存储）。

用法:
    python scripts/migrate_config.py               # 迁移（DB 为空时自动进行）
    python scripts/migrate_config.py --force       # 强制覆盖已有配置
    python scripts/migrate_config.py --verify      # 验证加密存储
    python scripts/migrate_config.py --clear       # 清空配置表
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config_store import ConfigStore


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]

    if "--clear" in sys.argv:
        store = ConfigStore()
        store.clear()
        print("✅ 配置表已清空")
        return

    if "--verify" in sys.argv:
        store = ConfigStore()
        all_cfg = store.get_all()
        print(f"配置条目数: {len(all_cfg)}")
        for key, value in all_cfg.items():
            sensitive = key in (
                "live.password", "live.auth_code",
                "notify.dingtalk_secret", "notify.dingtalk_webhook",
            )
            masked = str(value)[:8] + "..." if sensitive and value else str(value)
            print(f"  {key}: {masked}")
        return

    store = ConfigStore()

    if "--force" in sys.argv:
        store.clear()

    if store.count() > 0:
        print(f"配置表中已有 {store.count()} 项。如需重新迁移请使用 --force")
    else:
        store.migrate_from_yaml()
        print(f"✅ 迁移完成: {store.count()} 项配置已写入数据库")


if __name__ == "__main__":
    main()
