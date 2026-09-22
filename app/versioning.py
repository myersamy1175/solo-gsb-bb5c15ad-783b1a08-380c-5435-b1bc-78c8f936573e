"""方案级规则版本服务。

每个方案可以维护自己的规则版本链：

- draft       草稿：可反复编辑规则集合与严重级别依据；每个方案至多一个草稿
- published   当前生效版本：每个方案至多一个；推演接口只读取它
- superseded  已发布但被新版本替代（保留快照用于差异查看与历史追溯）
- deactivated 被人工停用：不再参与判定，方案回落到全局限定规则图

规则集合以快照形式存在 rule_versions.rules_json 中，发布后不可变；
每版保留每条规则的严重级别依据（标题/方程式/机理/文献）及创建、发布、
停用与最近变更时间。
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import models

# 状态机与中文展示
STATUS_LABELS = {
    "draft": "草稿",
    "published": "生效中",
    "superseded": "已被替代",
    "deactivated": "已停用",
}
PUBLISHED = "published"
DRAFT = "draft"
SUPERSEDED = "superseded"
DEACTIVATED = "deactivated"

# 规则条目之间需要纳入差异比较的"反应依据"字段
BASIS_FIELDS = (
    "title",
    "reaction",
    "rationale",
    "references",
    "source",
    "target",
    "directional",
)
FIELD_LABELS = {
    "severity": "严重级别",
    "title": "规则标题",
    "reaction": "反应方程式",
    "rationale": "机理解释",
    "references": "参考文献",
    "source": "类别 A",
    "target": "类别 B",
    "directional": "方向",
}
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


class RuleVersionError(ValueError):
    """规则版本业务校验错误（路由层转 4xx）。"""


@dataclass
class SnapshotRule:
    """供推演引擎使用的规则快照（字段与 models.Rule 一致）。"""

    id: str
    source: str
    target: str
    directional: bool
    severity: str
    title: str
    reaction: str
    rationale: str
    references: str  # JSON 字符串，与 ORM Rule 保持一致


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------- 快照与查询

def snapshot_active_global_rules(db: Session) -> list[dict]:
    """克隆当前全局限定规则图中处于启用状态的规则。"""
    rules = db.query(models.Rule).filter(models.Rule.active.is_(True)).all()
    return [
        {
            "id": r.id,
            "source": r.source,
            "target": r.target,
            "directional": bool(r.directional),
            "severity": r.severity,
            "title": r.title,
            "reaction": r.reaction,
            "rationale": r.rationale,
            "references": json.loads(r.references or "[]"),
            "builtin": bool(r.builtin),
        }
        for r in sorted(rules, key=lambda x: x.id)
    ]


def snapshot_version_rules(version: models.RuleVersion) -> list[dict]:
    return json.loads(version.rules_json or "[]")


def get_published_version(db: Session, plan_id: int) -> models.RuleVersion | None:
    """返回方案当前生效（published）的规则版本；没有则 None。"""
    return (
        db.query(models.RuleVersion)
        .filter(
            models.RuleVersion.plan_id == plan_id,
            models.RuleVersion.status == PUBLISHED,
        )
        .first()
    )


def get_version_or_none(db: Session, plan_id: int, version_id: int) -> models.RuleVersion | None:
    return (
        db.query(models.RuleVersion)
        .filter(
            models.RuleVersion.plan_id == plan_id,
            models.RuleVersion.id == version_id,
        )
        .first()
    )


def engine_rules(version: models.RuleVersion) -> list[SnapshotRule]:
    """把版本快照转换成推演引擎可消费的规则对象。"""
    out = []
    for item in snapshot_version_rules(version):
        out.append(
            SnapshotRule(
                id=item["id"],
                source=item["source"],
                target=item["target"],
                directional=bool(item.get("directional", False)),
                severity=item["severity"],
                title=item.get("title", ""),
                reaction=item.get("reaction", ""),
                rationale=item.get("rationale", ""),
                references=json.dumps(item.get("references", []), ensure_ascii=False),
            )
        )
    return out


def revision_label(version: models.RuleVersion) -> str:
    """报告中的版本标识，例如 方案#3-规则v2。"""
    return f"plan{version.plan_id}-rv{version.version_no}"


# ---------------------------------------------------------------- 序列化

def _rule_out(item: dict) -> dict:
    return {
        "id": item["id"],
        "source": item.get("source", ""),
        "target": item.get("target", ""),
        "directional": bool(item.get("directional", False)),
        "severity": item.get("severity", "medium"),
        "title": item.get("title", ""),
        "reaction": item.get("reaction", ""),
        "rationale": item.get("rationale", ""),
        "references": item.get("references", []),
        "builtin": bool(item.get("builtin", False)),
    }


def version_out(db: Session, v: models.RuleVersion, *, is_effective: bool | None = None) -> dict:
    if is_effective is None:
        is_effective = v.status == PUBLISHED
    rules = snapshot_version_rules(v)
    counts = {"high": 0, "medium": 0, "low": 0}
    for r in rules:
        counts[r.get("severity", "medium")] = counts.get(r.get("severity", "medium"), 0) + 1
    return {
        "id": v.id,
        "plan_id": v.plan_id,
        "version_no": v.version_no,
        "status": v.status,
        "status_label": STATUS_LABELS[v.status],
        "is_effective": is_effective,
        "source_of_version": v.source_of_version,
        "base_version_id": v.base_version_id,
        "base_revision": v.base_revision,
        "note": v.note,
        "rule_count": len(rules),
        "severity_counts": counts,
        "created_at": _iso(v.created_at),
        "updated_at": _iso(v.updated_at),
        "published_at": _iso(v.published_at),
        "deactivated_at": _iso(v.deactivated_at),
        "rules": [_rule_out(r) for r in rules],
    }


def effective_summary(v: models.RuleVersion | None) -> dict | None:
    """方案详情里展示的"当前生效状态"摘要。"""
    if v is None:
        return None
    return {
        "id": v.id,
        "version_no": v.version_no,
        "status": v.status,
        "status_label": STATUS_LABELS[v.status],
        "rule_count": len(snapshot_version_rules(v)),
        "published_at": _iso(v.published_at),
        "updated_at": _iso(v.updated_at),
    }


# ---------------------------------------------------------------- 校验

def validate_rules(rules: list[dict]) -> list[dict]:
    """校验并归一化草稿规则集合。"""
    if not isinstance(rules, list) or not rules:
        raise RuleVersionError("版本至少要包含一条规则；空规则集会导致所有方案判定失效")
    cleaned: list[dict] = []
    seen: set[str] = set()
    for i, raw in enumerate(rules):
        if not isinstance(raw, dict):
            raise RuleVersionError(f"第 {i + 1} 条规则格式不正确")
        rid = str(raw.get("id", "")).strip()
        if not rid or len(rid) > 32:
            raise RuleVersionError(f"第 {i + 1} 条规则缺少有效编号")
        if rid in seen:
            raise RuleVersionError(f"规则编号 {rid} 在同一版本中重复")
        seen.add(rid)
        source = str(raw.get("source", "")).strip()
        target = str(raw.get("target", "")).strip()
        if not source or not target:
            raise RuleVersionError(f"规则 {rid} 的类别 A/B 不能为空")
        if source == target:
            raise RuleVersionError(f"规则 {rid} 的两个类别不能相同")
        severity = raw.get("severity", "medium")
        if severity not in SEVERITY_RANK:
            raise RuleVersionError(f"规则 {rid} 的严重级别非法：{severity}")
        refs = raw.get("references", []) or []
        if not isinstance(refs, list):
            raise RuleVersionError(f"规则 {rid} 的参考文献必须是数组")
        cleaned.append(
            {
                "id": rid,
                "source": source,
                "target": target,
                "directional": bool(raw.get("directional", False)),
                "severity": severity,
                "title": str(raw.get("title", "") or ""),
                "reaction": str(raw.get("reaction", "") or ""),
                "rationale": str(raw.get("rationale", "") or ""),
                "references": [str(x) for x in refs],
                "builtin": bool(raw.get("builtin", False)),
            }
        )
    cleaned.sort(key=lambda r: r["id"])
    return cleaned


# ---------------------------------------------------------------- 生命周期

def _next_version_no(db: Session, plan_id: int) -> int:
    """版本号在方案内单调递增；草稿删除后也不复用其编号。"""
    last_no = (
        db.query(models.RuleVersion.version_no)
        .filter(models.RuleVersion.plan_id == plan_id)
        .order_by(models.RuleVersion.version_no.desc())
        .first()
    )
    return (last_no[0] if last_no else 0) + 1


def create_version(db: Session, plan_id: int, note: str | None = None,
                   rules: list[dict] | None = None,
                   base: models.RuleVersion | None = None) -> models.RuleVersion:
    """创建草稿版本：显式给 base 则克隆其快照，否则克隆当前生效版本，
    都没有时克隆全局限定规则图。每个方案至多一个草稿。
    """
    existing_draft = (
        db.query(models.RuleVersion)
        .filter(
            models.RuleVersion.plan_id == plan_id,
            models.RuleVersion.status == DRAFT,
        )
        .first()
    )
    if existing_draft is not None:
        raise RuleVersionError(
            f"该方案已有草稿 v{existing_draft.version_no}，请先发布或删除后再创建新版本"
        )

    effective = get_published_version(db, plan_id)
    if base is not None:
        snapshot = snapshot_version_rules(base)
        source = "published_version" if base.status != DRAFT else "draft"
        base_revision = revision_label(base)
        base_id = base.id
    elif effective is not None:
        snapshot = snapshot_version_rules(effective)
        source = "published_version"
        base_revision = revision_label(effective)
        base_id = effective.id
    else:
        from . import rules_store

        snapshot = snapshot_active_global_rules(db)
        source = "global"
        base_revision = rules_store.get_rule_revision()
        base_id = None

    if rules is not None:
        snapshot = validate_rules(rules)

    version = models.RuleVersion(
        plan_id=plan_id,
        version_no=_next_version_no(db, plan_id),
        status=DRAFT,
        source_of_version=source,
        base_version_id=base_id,
        base_revision=base_revision,
        note=(note or "").strip() or None,
        rules_json=json.dumps(snapshot, ensure_ascii=False),
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def update_draft(db: Session, version: models.RuleVersion, *,
                 note: str | None = None, rules: list[dict] | None = None) -> models.RuleVersion:
    if version.status != DRAFT:
        raise RuleVersionError("只有草稿状态的版本可以编辑，请创建新版本草稿后再修改")
    if note is not None:
        version.note = note.strip() or None
    if rules is not None:
        version.rules_json = json.dumps(validate_rules(rules), ensure_ascii=False)
    db.commit()
    db.refresh(version)
    return version


def publish(db: Session, version: models.RuleVersion) -> models.RuleVersion:
    """发布：草稿转 published；同方案原 published 版本原子地置为 superseded。"""
    if version.status != DRAFT:
        raise RuleVersionError(
            f"版本 v{version.version_no} 当前为「{STATUS_LABELS[version.status]}」，只有草稿可以发布"
        )
    snapshot = snapshot_version_rules(version)
    if not snapshot:
        raise RuleVersionError("草稿规则集合为空，不能发布")

    old_published = (
        db.query(models.RuleVersion)
        .filter(
            models.RuleVersion.plan_id == version.plan_id,
            models.RuleVersion.status == PUBLISHED,
        )
        .all()
    )
    now = _utcnow()
    for old in old_published:
        old.status = SUPERSEDED
    version.status = PUBLISHED
    version.published_at = now
    db.commit()
    db.refresh(version)
    return version


def deactivate(db: Session, version: models.RuleVersion) -> models.RuleVersion:
    """停用当前生效版本：停用后判定接口不再读取任何方案版本（回落全局规则图）。"""
    if version.status != PUBLISHED:
        raise RuleVersionError(
            f"版本 v{version.version_no} 不是当前生效版本（{STATUS_LABELS[version.status]}），无法停用"
        )
    version.status = DEACTIVATED
    version.deactivated_at = _utcnow()
    db.commit()
    db.refresh(version)
    return version


def delete_version(db: Session, version: models.RuleVersion) -> None:
    """删除版本：仅允许删除草稿；已发布版本作为判定历史不可删除。"""
    if version.status != DRAFT:
        raise RuleVersionError(
            f"版本 v{version.version_no} 已发布（{STATUS_LABELS[version.status]}），"
            "为保留判定依据不可删除，可停用当前生效版本"
        )
    db.delete(version)
    db.commit()


# ---------------------------------------------------------------- 版本差异

def _rule_map(rules: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in rules}


def _basis_equal(a: dict, b: dict) -> tuple[bool, list[str]]:
    changed: list[str] = []
    for field in BASIS_FIELDS:
        if a.get(field) != b.get(field):
            changed.append(field)
    return (not changed), changed


def diff_rules(base_rules: list[dict], target_rules: list[dict]) -> dict:
    """按规则 ID 对齐两个版本快照，输出 added/removed/severity/basis/unchanged。"""
    a_map = _rule_map(base_rules)
    b_map = _rule_map(target_rules)
    entries: list[dict] = []

    for rid in sorted(set(a_map) | set(b_map)):
        a, b = a_map.get(rid), b_map.get(rid)
        if a is None:
            change = "added"
            changed_fields: list[str] = []
        elif b is None:
            change = "removed"
            changed_fields = []
        else:
            _, changed_fields = _basis_equal(a, b)
            if a.get("severity") != b.get("severity"):
                change = "severity"
                changed_fields = ["severity"] + changed_fields
            elif changed_fields:
                change = "basis"
            else:
                change = "unchanged"
        cur = b or a
        entries.append(
            {
                "rule_id": rid,
                "change": change,
                "change_label": {
                    "added": "新增规则",
                    "removed": "删除规则",
                    "severity": "严重级别变化",
                    "basis": "判定依据变化",
                    "unchanged": "一致",
                }[change],
                "base_severity": a.get("severity") if a else None,
                "target_severity": b.get("severity") if b else None,
                "changed_fields": changed_fields,
                "field_labels": [FIELD_LABELS.get(f, f) for f in changed_fields],
                "base": _rule_out(a) if a else None,
                "target": _rule_out(b) if b else None,
                "_rank": (
                    {"added": 0, "severity": 1, "basis": 2, "removed": 3, "unchanged": 4}[change],
                    -SEVERITY_RANK.get(cur.get("severity", "medium"), 0),
                    rid,
                ),
            }
        )

    entries.sort(key=lambda e: e["_rank"])
    for e in entries:
        e.pop("_rank", None)

    counts = {
        c: sum(1 for e in entries if e["change"] == c)
        for c in ("added", "removed", "severity", "basis", "unchanged")
    }
    sev_counts = {"high": 0, "medium": 0, "low": 0}
    for r in target_rules:
        sev_counts[r.get("severity", "medium")] = sev_counts.get(r.get("severity", "medium"), 0) + 1

    return {
        "rule_count": {"base": len(base_rules), "target": len(target_rules)},
        "target_severity_counts": sev_counts,
        "changes": counts,
        "rules": entries,
    }


def global_side_meta(revision: str) -> dict:
    return {
        "kind": "global",
        "version_id": None,
        "version_no": None,
        "status_label": "全局限定规则图",
        "rule_revision": revision,
        "updated_at": None,
    }


def version_side_meta(v: models.RuleVersion) -> dict:
    return {
        "kind": "rule_version",
        "version_id": v.id,
        "version_no": v.version_no,
        "status": v.status,
        "status_label": STATUS_LABELS[v.status],
        "rule_revision": revision_label(v),
        "published_at": _iso(v.published_at),
        "updated_at": _iso(v.updated_at),
        "deactivated_at": _iso(v.deactivated_at),
    }
