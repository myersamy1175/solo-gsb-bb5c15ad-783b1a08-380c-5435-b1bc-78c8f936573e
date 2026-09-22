"""从已保存方案构建引擎输入并执行推演、落盘推演记录。

判定用规则来源（需求约束：发布后只读取当前生效版本，停用后不参与判定）：

1. 显式指定 rule_version_id 时（仅限不保存的预览），读取该版本快照；
2. 否则读取该方案唯一 status=published 的规则版本；
3. 方案没有生效版本（从未发布 / 已停用 / 已被替代）时，回落到全局限定规则图。
"""
import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import engine, models, rules_store, safety, versioning


def _step_categories(db: Session, step: models.Step) -> list[str]:
    """步骤关联试剂的类别：优先试剂档案，兜底步骤创建时的快照。"""
    if step.reagent_id is not None:
        reagent = db.get(models.Reagent, step.reagent_id)
        if reagent is not None:
            return json.loads(reagent.categories or "[]")
    return json.loads(step.categories or "[]")


def plan_to_input(db: Session, plan: models.Plan) -> list[engine.InputStep]:
    ordered = sorted(plan.steps, key=lambda s: (s.order_index, s.id))
    inputs = []
    for s in ordered:
        inputs.append(
            engine.InputStep(
                order_index=s.order_index,
                time_offset_min=s.time_offset_min,
                amount_ml=s.amount_ml,
                note=s.note,
                reagent=engine.InputReagent(
                    name=s.reagent_name,
                    categories=_step_categories(db, s),
                ),
            )
        )
    return inputs


def resolve_rule_source(
    db: Session,
    plan: models.Plan | None,
    rule_version_id: int | None = None,
) -> tuple[list, str, int | None, str]:
    """解析判定使用的规则来源。

    返回 (引擎规则列表, 版本标识, rule_version_id, 规则范围 global|plan_version)。
    rule_version_id 显式给出时允许读取任意状态版本（用于草稿预览），
    否则只认 published；停用版本永远不会经自动路径参与判定。
    """
    if rule_version_id is not None:
        if plan is None:
            raise HTTPException(422, "未保存方案不能指定规则版本")
        version = versioning.get_version_or_none(db, plan.id, rule_version_id)
        if version is None:
            raise HTTPException(404, f"规则版本 #{rule_version_id} 不存在或不属于该方案")
        return (
            versioning.engine_rules(version),
            versioning.revision_label(version),
            version.id,
            "plan_version",
        )

    if plan is not None:
        effective = versioning.get_published_version(db, plan.id)
        if effective is not None:
            return (
                versioning.engine_rules(effective),
                versioning.revision_label(effective),
                effective.id,
                "plan_version",
            )

    rules = db.query(models.Rule).filter(models.Rule.active.is_(True)).all()
    return rules, rules_store.get_rule_revision(), None, "global"


def build_report(
    db: Session,
    plan: models.Plan | None,
    *,
    rule_version_id: int | None = None,
) -> tuple[dict, int | None]:
    """执行推演，返回 (报告, 实际使用的规则版本 ID)。

    报告附带各步骤安全确认状态（safety 摘要 + 时间轴逐步标记）：
    正式推演的确认门槛在路由层把控，预检 / 导出同样展示确认状态。
    """
    rules, revision, resolved_vid, scope = resolve_rule_source(db, plan, rule_version_id)
    steps = plan_to_input(db, plan) if plan is not None else []
    report = engine.simulate(steps, rules, revision)
    report["rule_scope"] = scope
    if resolved_vid is not None:
        report["rule_version_id"] = resolved_vid
    if plan is not None:
        report["plan_name"] = plan.name
        summary = safety.plan_safety_summary(db, plan)
        report["safety"] = summary
        by_index = {item["order_index"]: item for item in summary["steps"]}
        for item in report["timeline"]:
            step_safety = by_index.get(item["order_index"])
            if step_safety is not None:
                item["safety_confirmed"] = step_safety["confirmed"]
                item["safety_stale"] = step_safety["stale"]
    return report, resolved_vid


def persist_run(
    db: Session,
    plan: models.Plan,
    report: dict,
    persist: bool = True,
    rule_version_id: int | None = None,
):
    if not persist:
        return None
    run = models.Run(
        plan_id=plan.id,
        plan_name=plan.name,
        rule_revision=report.get("rule_revision", ""),
        rule_version_id=rule_version_id,
        status=report["status"],
        report=json.dumps(report, ensure_ascii=False),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run.id
