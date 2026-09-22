"""规则图查看与自定义规则维护。"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, rules_store
from ..database import get_db
from ..schemas import RuleCreate, RuleOut, RuleUpdate

router = APIRouter(prefix="/api/rules", tags=["rules"])


def _to_out(rule: models.Rule) -> dict:
    return {
        "id": rule.id,
        "source": rule.source,
        "target": rule.target,
        "directional": rule.directional,
        "severity": rule.severity,
        "title": rule.title,
        "reaction": rule.reaction,
        "rationale": rule.rationale,
        "references": json.loads(rule.references or "[]"),
        "builtin": rule.builtin,
        "active": rule.active,
    }


@router.get("")
def list_rules(active_only: bool = False, db: Session = Depends(get_db)):
    """返回规则边 + 类别元信息 + 版本号，供列表与规则图渲染。"""
    q = db.query(models.Rule)
    if active_only:
        q = q.filter(models.Rule.active.is_(True))
    rules = q.order_by(models.Rule.id).all()

    # 类别集合 = YAML 内置类别 ∪ 数据库中出现过的类别
    categories = dict(rules_store.get_builtin_categories())
    seen = set(categories.keys())
    for r in rules:
        for cat in (r.source, r.target):
            if cat not in seen:
                categories[cat] = {"label": cat}
                seen.add(cat)

    return {
        "revision": rules_store.get_rule_revision(),
        "categories": categories,
        "rules": [_to_out(r) for r in rules],
    }


@router.post("", response_model=RuleOut, status_code=201)
def create_rule(rule_in: RuleCreate, db: Session = Depends(get_db)):
    if db.get(models.Rule, rule_in.id) is not None:
        raise HTTPException(409, f"规则编号 {rule_in.id} 已存在（内置规则编号请用 C 开头避免冲突）")
    if rule_in.source == rule_in.target:
        raise HTTPException(422, "规则的两个类别不能相同")
    rule = models.Rule(
        id=rule_in.id,
        source=rule_in.source,
        target=rule_in.target,
        directional=rule_in.directional,
        severity=rule_in.severity,
        title=rule_in.title,
        reaction=rule_in.reaction,
        rationale=rule_in.rationale,
        references=json.dumps(rule_in.references, ensure_ascii=False),
        builtin=False,
        active=True,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.patch("/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: str, patch: RuleUpdate, db: Session = Depends(get_db)):
    rule = db.get(models.Rule, rule_id)
    if rule is None:
        raise HTTPException(404, "规则不存在")
    data = patch.model_dump(exclude_unset=True)
    # 内置规则只允许开关与严重级别调整；文案以 YAML 为唯一来源
    allowed = {"active", "severity"} if rule.builtin else {"active", "severity", "title", "rationale"}
    for key, value in data.items():
        if key in allowed and value is not None:
            setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: str, db: Session = Depends(get_db)):
    rule = db.get(models.Rule, rule_id)
    if rule is None:
        raise HTTPException(404, "规则不存在")
    if rule.builtin:
        raise HTTPException(409, "内置规则不可删除，可在列表中停用，或修改 data/rules.yaml")
    db.delete(rule)
    db.commit()
