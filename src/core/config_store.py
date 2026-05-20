"""
配置加密存储模块。

职责：
1. Fernet 加密密钥生命周期管理（首次自动生成，后续自动加载）
2. Config dataclass ←→ SQLite 序列化
3. 敏感字段加密存储
4. YAML → DB 一键迁移
"""
from pathlib import Path
from typing import Any, Dict, Optional
import json
import sqlite3
import logging

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# ── 项目路径 ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "live_state" / "trading.db"
_KEY_PATH = _PROJECT_ROOT / "data" / ".config_key"

# ── 敏感字段列表（需要加密存储）──
SENSITIVE_KEYS = {
    "live.password",
    "live.auth_code",
    "notify.dingtalk_secret",
    "notify.dingtalk_webhook",
}


class ConfigStore:
    """配置加密存储中心。"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._fernet: Optional[Fernet] = None
        self._init_key()
        self._init_table()

    # ────────── 密钥管理 ──────────

    def _init_key(self):
        """首次自动生成密钥，后续加载已有密钥。"""
        if _KEY_PATH.exists():
            key = _KEY_PATH.read_bytes()
        else:
            key = Fernet.generate_key()
            _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
            _KEY_PATH.write_bytes(key)
            logger.info(f"配置加密密钥已生成: {_KEY_PATH}")
        self._fernet = Fernet(key)

    # ────────── 数据库 ──────────

    def _conn(self) -> sqlite3.Connection:
        """创建数据库连接（WAL 模式）。"""
        c = sqlite3.connect(str(self.db_path))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _init_table(self):
        """创建 app_config 表（如不存在）。"""
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS app_config (
                    key         TEXT PRIMARY KEY,
                    value       TEXT NOT NULL,
                    encrypted   INTEGER NOT NULL DEFAULT 0,
                    updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
                )
            """)
            c.commit()

    # ────────── 加解密 ──────────

    def _encrypt(self, plain: str) -> str:
        """加密明文 → base64 密文字符串。"""
        if not self._fernet:
            return plain
        return self._fernet.encrypt(plain.encode("utf-8")).decode("utf-8")

    def _decrypt(self, cipher: str) -> str:
        """解密密文 → 明文字符串。失败返回空字符串。"""
        if not self._fernet:
            return cipher
        try:
            return self._fernet.decrypt(cipher.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            logger.warning("配置解密失败（密钥已变更？），返回空值")
            return ""
        except Exception as e:
            logger.warning(f"配置解密异常: {e}")
            return ""

    # ────────── CRUD ──────────

    def get(self, key: str) -> Optional[Any]:
        """获取单个配置值。"""
        with self._conn() as c:
            row = c.execute(
                "SELECT value, encrypted FROM app_config WHERE key=?", (key,)
            ).fetchone()
        if row is None:
            return None
        raw = row["value"]
        if row["encrypted"]:
            raw = self._decrypt(raw)
        return self._deserialize(raw)

    def set(self, key: str, value: Any):
        """设置配置值。敏感字段自动加密。"""
        is_sensitive = key in SENSITIVE_KEYS
        raw = self._serialize(value)
        if is_sensitive:
            raw = self._encrypt(raw)
        with self._conn() as c:
            c.execute(
                """INSERT INTO app_config (key, value, encrypted, updated_at)
                   VALUES (?, ?, ?, datetime('now','localtime'))
                   ON CONFLICT(key) DO UPDATE SET
                       value=excluded.value,
                       encrypted=excluded.encrypted,
                       updated_at=excluded.updated_at""",
                (key, raw, 1 if is_sensitive else 0),
            )
            c.commit()

    def delete(self, key: str):
        """删除配置项。"""
        with self._conn() as c:
            c.execute("DELETE FROM app_config WHERE key=?", (key,))
            c.commit()

    def get_all(self) -> Dict[str, Any]:
        """获取全部配置（扁平 dict，已解密）。"""
        with self._conn() as c:
            rows = c.execute(
                "SELECT key, value, encrypted FROM app_config ORDER BY key"
            ).fetchall()
        result = {}
        for row in rows:
            raw = row["value"]
            if row["encrypted"]:
                raw = self._decrypt(raw)
            result[row["key"]] = self._deserialize(raw)
        return result

    def count(self) -> int:
        """配置条目数。"""
        with self._conn() as c:
            row = c.execute("SELECT COUNT(*) AS n FROM app_config").fetchone()
            return row["n"] if row else 0

    def clear(self):
        """清空配置表。"""
        with self._conn() as c:
            c.execute("DELETE FROM app_config")
            c.commit()

    # ────────── 序列化工具 ──────────

    @staticmethod
    def _serialize(value: Any) -> str:
        """将任意值转为存储字符串。"""
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _deserialize(raw: str) -> Any:
        """将存储字符串恢复为 Python 值。"""
        # 先尝试 JSON 解析（处理 int / float / bool / list / dict）
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
        # 视为原始字符串
        return raw

    # ────────── Config dataclass 双向映射 ──────────

    @staticmethod
    def _flatten(config) -> Dict[str, Any]:
        """将 Config dataclass 树展平为带点号的扁平 dict。"""
        from dataclasses import asdict

        result = {}
        section_map = {
            "data": config.data,
            "logging": config.logging,
            "backtest": config.backtest,
            "strategy": config.strategy,
            "ai": config.ai,
            "schedule": config.schedule,
            "notify": config.notify,
            "live": config.live,
        }
        for section_name, section_obj in section_map.items():
            d = asdict(section_obj)
            for field_name, field_value in d.items():
                result[f"{section_name}.{field_name}"] = field_value
        return result

    @staticmethod
    def _set_field(config, key: str, value: Any):
        """根据带点号的 key 设置 Config 对象的字段。"""
        parts = key.split(".", 1)
        if len(parts) != 2:
            return
        section_name, field_name = parts
        section = getattr(config, section_name, None)
        if section is None or not hasattr(section, field_name):
            return
        # 类型保持：从字段原类型推断
        current = getattr(section, field_name)
        if isinstance(current, bool):
            # bool 是 int 的子类，需优先判断
            coerced = str(value).lower() in ("true", "1", "yes") if not isinstance(value, bool) else value
        elif isinstance(current, int) and not isinstance(current, bool):
            coerced = int(value) if not isinstance(value, int) else value
        elif isinstance(current, float):
            coerced = float(value) if not isinstance(value, float) else value
        elif isinstance(current, list):
            coerced = value if isinstance(value, list) else [value]
        elif isinstance(current, dict):
            coerced = value if isinstance(value, dict) else {}
        else:
            coerced = str(value) if value is not None else current
        setattr(section, field_name, coerced)

    def load_into(self, config) -> bool:
        """从 DB 加载配置到 Config 对象。DB 为空则返回 False。"""
        if self.count() == 0:
            return False
        for key, value in self.get_all().items():
            self._set_field(config, key, value)
        return True

    def save_from(self, config) -> int:
        """将 Config 对象全部写入 DB。返回写入条目数。"""
        flat = self._flatten(config)
        for key, value in flat.items():
            self.set(key, value)
        return len(flat)

    # ────────── YAML 迁移 ──────────

    def migrate_from_yaml(self, secrets_path: str = "./config/secrets.yaml") -> bool:
        """从 secrets.yaml 迁移配置到 DB。

        策略：用 Config 默认值构造对象，叠加 secrets.yaml 中的值，写入 DB。
        仅在 DB 为空时自动调用。

        Returns:
            True 表示写入了数据
        """
        from src.core.config import Config

        config = Config()

        # 尝试加载 secrets.yaml
        secrets_file = Path(secrets_path)
        if secrets_file.exists():
            try:
                import yaml
                with open(secrets_file, "r", encoding="utf-8") as f:
                    secrets = yaml.safe_load(f) or {}

                ctp = secrets.get("ctp", {})
                for k, v in ctp.items():
                    # userid → user_id, brokerid → broker_id
                    if k == "userid":
                        config.live.user_id = str(v)
                    elif k == "password":
                        config.live.password = str(v)
                    elif k == "brokerid":
                        config.live.broker_id = str(v)
                    elif k == "app_id":
                        config.live.app_id = str(v)
                    elif k == "auth_code":
                        config.live.auth_code = str(v)
                    elif k == "td_address":
                        config.live.td_address = str(v)
                    elif k == "md_address":
                        config.live.md_address = str(v)

                dingtalk = secrets.get("dingtalk", {})
                if dingtalk.get("webhook"):
                    config.notify.dingtalk_webhook = str(dingtalk["webhook"])
                if dingtalk.get("secret"):
                    config.notify.dingtalk_secret = str(dingtalk["secret"])

                logger.info("已从 secrets.yaml 加载密钥")
            except Exception as e:
                logger.warning(f"加载 secrets.yaml 失败: {e}")

        self.save_from(config)
        logger.info(f"配置已迁移到数据库: {self.db_path}")
        return True
