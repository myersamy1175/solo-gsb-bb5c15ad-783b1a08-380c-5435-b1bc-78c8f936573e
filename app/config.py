"""应用配置与文件路径。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("APP_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = os.getenv("APP_DB_PATH", str(DATA_DIR / "labmix.db"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

RULES_FILE = DATA_DIR / "rules.yaml"
SEED_RULES_FILE = BASE_DIR / "data" / "rules.yaml"  # 随仓库发布的内置规则图

WEB_DIR = BASE_DIR / "web"
