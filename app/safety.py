"""步骤安全确认：措施勾选、内容指纹绑定与正式推演门槛。

每个加液步骤可勾选安全措施（护目镜 / 通风 / 手套等）并填写安全备注，
确认时把确认绑定到"步骤内容指纹"上：

- 内容指纹 = 有效试剂（档案试剂实时解析名称/类别，临时试剂用快照）
  + 用量 + 时刻 + 操作备注；
- 确认指纹 = 内容指纹 + 已勾选措施 + 安全备注。

此后步骤内容、所引用试剂的名称/类别、或已确认的措施与备注发生变化，
指纹不再匹配，确认自动失效并标记为"待复核"（stale），无需人工清理。

门槛口径：正式推演（simulate persist=true）要求全部步骤确认有效，
否则返回 409 并列出未确认 / 待复核步骤；预检（simulate-dry、
persist=false）与导出不受此门槛限制，但报告中同样携带确认状态。
"""
import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models

# 界面预置的安全措施选项（前端渲染用；后端不限制 key，允许自定义）
MEASURE_PRESETS = [
    {"key": "goggles", "label": "护目镜"},
    {"key": "gloves", "label": "防护手套"},
    {"key": "ventilation", "label": "通风橱 / 强制通风"},
    {"key": "lab_coat", "label": "实验服"},
    {"key": "face_shield", "label": "防护面罩"},
    {"key": "emergency_shower", "label": "紧急喷淋 / 洗眼器就绪"},
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _norm_num(value):
    return None if value is None else float(value)


def _norm_text(value) -> str:
    return (value or "").strip()


def _hash(parts: list) -> str:
    payload = json.dumps(parts, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _effective_reagent(db: Session, reagent_id, fallback_name: str, fallback_categories):
    """步骤有效试剂名与类别：优先试剂档案实时值，兜底步骤快照。"""
    if reagent_id is not None:
        reagent = db.get(models.Reagent, reagent_id)
        if reagent is not None:
            return reagent.name, json.loads(reagent.categories or "[]")
    return fallback_name or "", list(fallback_categories or [])


def _content_parts(db: Session, step: models.Step) -> list:
    eff_name, eff_categories = _effective_reagent(
        db, step.reagent_id, step.reagent_name, json.loads(step.categories or "[]")
    )
    return [
        step.reagent_id,
        eff_name,
        sorted(eff_categories),
        _norm_num(step.amount_ml),
        _norm_num(step.time_offset_min),
        _norm_text(step.note),
    ]


def content_fingerprint(db: Session, step: models.Step) -> str:
    """步骤内容指纹（不含安全确认数据），用于跨保存匹配同一未变更步骤。"""
    return _hash(_content_parts(db, step))


def confirm_fingerprint(db: Session, step: models.Step) -> str:
    """确认指纹：内容 + 已勾选措施 + 安全备注。确认时落库，校验时重算比对。"""
    parts = _content_parts(db, step) + [
        sorted(json.loads(step.safety_measures or "[]")),
        _norm_text(step.safety_note),
    ]
    return _hash(parts)


def fingerprint_for_input(db: Session, st) -> str:
    """由请求中的步骤数据（StepIn）计算内容指纹，用于保存时继承旧步骤确认。"""
    eff_name, eff_categories = _effective_reagent(
        db, st.reagent_id, st.reagent_name or "", st.categories or []
    )
    return _hash([
        st.reagent_id,
        eff_name,
        sorted(eff_categories),
        _norm_num(st.amount_ml),
        _norm_num(st.time_offset_min),
        _norm_text(st.note),
    ])


def apply_safety(
    db: Session,
    step: models.Step,
    *,
    measures,
    note,
    confirmed: bool,
    stale: bool = False,
) -> None:
    """写入步骤安全确认数据；确认时把确认绑定到当前确认指纹。"""
    step.safety_measures = json.dumps(list(measures or []), ensure_ascii=False)
    step.safety_note = _norm_text(note) or None
    if confirmed:
        step.safety_confirmed = True
        step.safety_confirmed_at = _utcnow()
        step.safety_confirmed_fp = confirm_fingerprint(db, step)
        step.safety_stale = False
    else:
        step.safety_confirmed = False
        step.safety_confirmed_at = None
        step.safety_confirmed_fp = None
        step.safety_stale = bool(stale)


def inherit_safety(target: models.Step, source: models.Step) -> None:
    """整体替换步骤时，把内容未变步骤的确认状态原样迁移到新行。"""
    target.safety_measures = source.safety_measures
    target.safety_note = source.safety_note
    target.safety_confirmed = source.safety_confirmed
    target.safety_confirmed_at = source.safety_confirmed_at
    target.safety_confirmed_fp = source.safety_confirmed_fp
    target.safety_stale = source.safety_stale


def step_safety_state(db: Session, step: models.Step) -> dict:
    """派生步骤确认状态。

    confirmed 仅在"用户确认过 + 确认指纹与当前一致 + 未被标记待复核"时有效；
    确认后内容 / 试剂 / 措施发生变化 → 确认失效并呈现 stale（待复核）。
    """
    flagged = bool(step.safety_confirmed)
    fp_match = flagged and (step.safety_confirmed_fp or "") == confirm_fingerprint(db, step)
    stale = (flagged and not fp_match) or bool(step.safety_stale)
    return {
        "confirmed": bool(flagged and fp_match and not step.safety_stale),
        "stale": stale,
        "measures": json.loads(step.safety_measures or "[]"),
        "note": step.safety_note,
        "confirmed_at": step.safety_confirmed_at.isoformat()
        if step.safety_confirmed_at
        else None,
    }


def plan_safety_summary(db: Session, plan: models.Plan) -> dict:
    """方案级确认摘要，供方案详情、方案列表与推演报告展示。"""
    steps = sorted(plan.steps, key=lambda s: (s.order_index, s.id))
    items = []
    confirmed = stale = 0
    for s in steps:
        state = step_safety_state(db, s)
        confirmed += 1 if state["confirmed"] else 0
        stale += 1 if state["stale"] else 0
        items.append(
            {
                "order_index": s.order_index,
                "reagent_name": s.reagent_name,
                **state,
            }
        )
    total = len(items)
    return {
        "total_steps": total,
        "confirmed_steps": confirmed,
        "stale_steps": stale,
        "pending_steps": total - confirmed,
        "all_confirmed": total > 0 and confirmed == total,
        "steps": items,
    }


def assert_all_confirmed(db: Session, plan: models.Plan) -> None:
    """正式推演门槛：全部步骤确认有效，否则 409 并列出待办步骤。"""
    summary = plan_safety_summary(db, plan)
    if summary["all_confirmed"]:
        return
    todos = []
    for item in summary["steps"]:
        if item["confirmed"]:
            continue
        tag = "待复核" if item["stale"] else "未确认"
        # 步骤编号按编辑器行号（1 基）展示，便于定位
        todos.append(f"第 {item['order_index'] + 1} 步「{item['reagent_name']}」（{tag}）")
    raise HTTPException(
        409,
        "正式推演前须完成全部加液步骤的安全确认："
        + "、".join(todos)
        + "。请在方案编辑页勾选各步安全措施并确认（预检不受此限制）。",
    )
