"""
Canopy 全局配置
"""
import os

# 数据库路径（SQLite）
db_path: str = os.environ.get(
    "CANOPY_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "canopy.db")
)

# Vault 加密存储开关
vault_enabled: bool = os.environ.get("CANOPY_VAULT_ENABLED", "1").lower() in (
    "1", "true", "yes"
)
