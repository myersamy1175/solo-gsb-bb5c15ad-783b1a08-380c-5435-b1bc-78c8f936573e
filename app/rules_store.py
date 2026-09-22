"""规则图加载与同步。

规则图以 data/rules.yaml 为声明式来源（随代码版本维护），启动时同步入库；
用户在界面上追加的自定义规则直接入库，二者合并构成推演用规则图。
"""
import json
import shutil
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from . import models
from .config import RULES_FILE, SEED_RULES_FILE

_builtin_cache: dict = {}  # 进程内缓存 YAML（类别元信息等）


def _ensure_rules_file() -> Path:
    """数据目录里没有 rules.yaml 时，从仓库模板复制一份，便于现场直接修改。"""
    if not RULES_FILE.exists() and SEED_RULES_FILE.exists():
        shutil.copyfile(SEED_RULES_FILE, RULES_FILE)
    return RULES_FILE


def load_builtin_rules() -> dict:
    """读取 YAML 规则图定义。"""
    path = _ensure_rules_file()
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("meta", {})
    data.setdefault("categories", {})
    data.setdefault("rules", [])
    return data


def sync_builtin_rules(db: Session) -> str:
    """把 YAML 内置规则 upsert 到数据库。

    - 新增规则：active=True
    - 已存在规则：保留用户在界面上对 active 的开关与文案改动（仅补齐字段默认）
    """
    global _builtin_cache
    data = load_builtin_rules()
    _builtin_cache = data
    revision = str(data["meta"].get("revision", ""))

    seen: set[str] = set()
    for item in data["rules"]:
        rid = item["id"]
        if rid in seen:
            # YAML 中重复定义同一规则时以第一条为准，避免唯一键冲突
            continue
        seen.add(rid)
        refs = item.get("references", [])
        rule = db.get(models.Rule, rid)
        if rule is None:
            rule = models.Rule(
                id=rid,
                source=item["source"],
                target=item["target"],
                directional=bool(item.get("directional", False)),
                severity=item.get("severity", "medium"),
                title=item.get("title", ""),
                reaction=item.get("reaction", ""),
                rationale=item.get("rationale", ""),
                references=json.dumps(refs, ensure_ascii=False),
                builtin=True,
                active=True,
            )
            db.add(rule)
        else:
            # 已存在：同步 YAML 的最新内容，但保留用户的 active 开关与级别调整
            rule.source = item["source"]
            rule.target = item["target"]
            rule.directional = bool(item.get("directional", False))
            rule.title = item.get("title", "")
            rule.reaction = item.get("reaction", "")
            rule.rationale = item.get("rationale", "")
            rule.references = json.dumps(refs, ensure_ascii=False)
            rule.builtin = True
            # severity / active 以数据库（用户在界面上的调整）为准，不回写
    db.commit()
    return revision


def get_builtin_categories() -> dict:
    """返回类别元信息 {key: {label: ...}}。"""
    global _builtin_cache
    if not _builtin_cache:
        _builtin_cache = load_builtin_rules()
    return dict(_builtin_cache.get("categories", {}))


def get_rule_revision() -> str:
    global _builtin_cache
    if not _builtin_cache:
        _builtin_cache = load_builtin_rules()
    return str(_builtin_cache.get("meta", {}).get("revision", ""))
