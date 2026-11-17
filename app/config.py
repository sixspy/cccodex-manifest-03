import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Config:
    LAB_NAME = "湖区清单台"
    SECRET = os.environ.get("SECRET_KEY", "cc-manifest-dev-secret")
    ADMIN_USER = "admin"
    ADMIN_PASSWORD = "123456"
    DEFAULT_DB = str(ROOT / "instance" / "manifest_lab.db")

    @classmethod
    def database(cls) -> str:
        return os.environ.get("DATABASE_PATH", cls.DEFAULT_DB)

    # 跨区依赖：key 区前缀闭合前，value 列出的区前缀同业务日（及更早）批次须全部闭合
    ZONE_DEPENDENCIES = {"silver": ["bronze"]}
