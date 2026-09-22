"""两条历史推演记录之间的"版本差异"计算。

仅允许比较同一方案的两条记录。两份报告按
**步骤编号（incoming_step / order_index）+ 规则 ID（rule_id）**
对齐命中（finding），同一规则在同一步因多个类别对产生多条命中时，
再以"冲突步骤 + 类别对"区分；随后识别：

- added       —— 新记录中新增的命中
- removed     —— 新记录中消失的命中
- severity    —— 同一命中的严重级别发生变化
- basis       —— 级别未变，但规则文案 / 方程式 / 机理 / 类别对等反应依据发生变化
- unchanged   —— 两次完全一致的命中

并汇总总体状态、首次危险、受影响 / 阻断步骤以及命中计数的变化。
"""
from typing import Any
import json

# finding 对齐后，除严重级别外需要纳入"反应依据"比较的字段
BASIS_FIELDS = (
    "title",
    "reaction",
    "rationale",
    "references",
    "incoming_category",
    "existing_category",
    "match_direction",
    "rule_directional",
    "incoming_reagent",
    "existing_reagent",
    "incoming_step",
    "existing_step",
)

CHANGE_LABELS = {
    "added": "新增命中",
    "removed": "消失命中",
    "severity": "严重级别变化",
    "basis": "反应依据变化",
    "unchanged": "一致",
}

SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3}


def sev_rank(sev: Any) -> int:
    return SEVERITY_ORDER.get(sev, 0)

# 汇总计数中需要逐项比较的 summary 键及其展示名
_COUNT_KEYS = (
    ("findings", "命中总数"),
    ("high", "严重命中"),
    ("medium", "警示命中"),
    ("low", "提示命中"),
)


class PlanMismatchError(ValueError):
    """两条记录不属于同一方案（或方案已不存在）。"""


def _finding_key(f: dict) -> tuple:
    """对齐键：步骤编号 + 规则 ID；同一步多条命中再按冲突步骤、类别对与匹配方向区分。"""
    return (
        f.get("incoming_step"),
        f.get("rule_id"),
        f.get("existing_step"),
        f.get("incoming_category"),
        f.get("existing_category"),
        f.get("match_direction"),
    )


def _finding_snapshot(f: dict | None) -> dict | None:
    """裁剪出差异视图需要的 finding 字段（不含仅在单次报告内有效的 F 编号）。"""
    if f is None:
        return None
    return {
        "rule_id": f.get("rule_id"),
        "severity": f.get("severity"),
        "severity_label": f.get("severity_label"),
        "title": f.get("title", ""),
        "reaction": f.get("reaction", ""),
        "rationale": f.get("rationale", ""),
        "references": f.get("references", []),
        "incoming_step": f.get("incoming_step"),
        "incoming_reagent": f.get("incoming_reagent", ""),
        "incoming_category": f.get("incoming_category", ""),
        "existing_step": f.get("existing_step"),
        "existing_reagent": f.get("existing_reagent", ""),
        "existing_category": f.get("existing_category", ""),
        "match_direction": f.get("match_direction", ""),
        "rule_directional": f.get("rule_directional", False),
    }


def _basis_changed(a: dict, b: dict) -> tuple[bool, list[str]]:
    """比较同一对齐位置上两条 finding 的反应依据；返回（是否变化, 变化字段名）。"""
    changed: list[str] = []
    for field in BASIS_FIELDS:
        if a.get(field) != b.get(field):
            changed.append(field)
    return bool(changed), changed


def _compact_danger(d: dict | None) -> dict | None:
    if not d:
        return None
    return {
        "finding_id": d.get("finding_id"),
        "step": d.get("step"),
        "reagent_name": d.get("reagent_name", ""),
        "conflicts_with_step": d.get("conflicts_with_step"),
        "conflicts_with_reagent": d.get("conflicts_with_reagent", ""),
        "rule_id": d.get("rule_id"),
        "title": d.get("title", ""),
        "reaction": d.get("reaction", ""),
    }


def _danger_change_type(a: dict | None, b: dict | None) -> str:
    if not a and not b:
        return "none"
    if not a and b:
        return "added"
    if a and not b:
        return "removed"
    if a.get("rule_id") != b.get("rule_id") or a.get("step") != b.get("step"):
        return "changed"
    return "same"


def _set_diff(a: list, b: list) -> dict:
    """两个步骤编号集合的增 / 删差异。"""
    sa, sb = set(a or []), set(b or [])
    return {
        "base": sorted(sa),
        "target": sorted(sb),
        "added": sorted(sb - sa),
        "removed": sorted(sa - sb),
    }


def _step_states(report: dict) -> dict[int, str]:
    return {t.get("order_index"): t.get("state") for t in report.get("timeline", [])}


def _step_diff(base: dict, target: dict) -> dict:
    """按步骤编号对齐时间轴状态。"""
    sb, st = _step_states(base), _step_states(target)
    order = sorted(set(sb) | set(st))
    items = []
    for idx in order:
        a, b = sb.get(idx), st.get(idx)
        if a is None:
            change = "added"
        elif b is None:
            change = "removed"
        elif a != b:
            change = "changed"
        else:
            change = "same"
        items.append(
            {"step": idx, "base_state": a, "target_state": b, "change": change}
        )
    return {
        "base_steps": sorted(sb),
        "target_steps": sorted(st),
        "added": sorted(set(st) - set(sb)),
        "removed": sorted(set(sb) - set(st)),
        "items": items,
    }


def _counts_changes(base: dict, target: dict) -> list[dict]:
    changes = []
    for key, label in _COUNT_KEYS:
        a = base.get("summary", {}).get(key, 0)
        b = target.get("summary", {}).get(key, 0)
        a, b = a or 0, b or 0
        changes.append(
            {"key": key, "label": label, "base": a, "target": b, "delta": b - a}
        )
    return changes


def _finding_entries(base: dict, target: dict) -> list[dict]:
    """按对齐键配对两侧 finding，逐条生成差异条目。"""
    a_map = {_finding_key(f): f for f in base.get("findings", [])}
    b_map = {_finding_key(f): f for f in target.get("findings", [])}

    entries: list[dict] = []
    for key in set(a_map) | set(b_map):
        a, b = a_map.get(key), b_map.get(key)
        if a is None:
            change = "added"
            basis_changed = False
            changed_fields: list[str] = []
        elif b is None:
            change = "removed"
            basis_changed = False
            changed_fields = []
        else:
            sev_a, sev_b = a.get("severity"), b.get("severity")
            basis_changed, changed_fields = _basis_changed(a, b)
            if sev_a != sev_b:
                change = "severity"
            else:
                change = "basis" if basis_changed else "unchanged"

        cur = b or a
        # 排序：按步骤对齐阅读——加入步骤、冲突步骤、规则 ID；同位置新增排前
        change_rank = {"added": 0, "severity": 1, "basis": 2, "removed": 3, "unchanged": 4}
        order = [
            cur.get("incoming_step") if cur.get("incoming_step") is not None else -1,
            cur.get("existing_step") if cur.get("existing_step") is not None else -1,
            str(cur.get("rule_id") or ""),
            change_rank[change],
            -sev_rank(cur.get("severity")),
        ]
        entries.append(
            {
                "change": change,
                "change_label": CHANGE_LABELS[change],
                "rule_id": (b or a).get("rule_id"),
                "incoming_step": (b or a).get("incoming_step"),
                "existing_step": (b or a).get("existing_step"),
                "base_severity": a.get("severity") if a else None,
                "target_severity": b.get("severity") if b else None,
                "severity_changed": change == "severity",
                "basis_changed": change in ("severity", "basis") and basis_changed,
                "changed_fields": changed_fields,
                "base": _finding_snapshot(a),
                "target": _finding_snapshot(b),
                "_order": order,
            }
        )

    entries.sort(key=lambda e: e["_order"])
    for e in entries:
        e.pop("_order", None)
    return entries


def build_run_diff(base_run, target_run) -> dict:
    """计算两条 Run ORM 记录的版本差异。

    不属于同一方案（plan_id 为空或不一致）时抛 PlanMismatchError。
    base = 较早的对照记录，target = 较新的待审记录。
    """
    base_plan_id = base_run.plan_id
    target_plan_id = target_run.plan_id
    if base_plan_id is None or target_plan_id is None:
        raise PlanMismatchError("推演记录未关联已保存方案，无法进行版本差异比较")
    if base_plan_id != target_plan_id:
        raise PlanMismatchError(
            f"两条记录不属于同一方案（方案 #{base_plan_id} 与方案 #{target_plan_id}），"
            "版本差异比较仅允许在同一方案的记录之间进行"
        )

    base = json.loads(base_run.report)
    target = json.loads(target_run.report)

    entries = _finding_entries(base, target)
    counts = {
        c: sum(1 for e in entries if e["change"] == c)
        for c in ("added", "removed", "severity", "basis", "unchanged")
    }

    danger_a, danger_b = base.get("first_danger"), target.get("first_danger")
    status_changed = base_run.status != target_run.status

    return {
        "kind": "labmix-run-diff",
        "engine_version": "1.0",
        "plan_id": base_plan_id,
        "plan_name": target_run.plan_name or base_run.plan_name,
        "base": {
            "run_id": base_run.id,
            "plan_id": base_plan_id,
            "plan_name": base_run.plan_name,
            "rule_revision": base_run.rule_revision,
            "status": base_run.status,
            "created_at": base_run.created_at.isoformat(),
        },
        "target": {
            "run_id": target_run.id,
            "plan_id": target_plan_id,
            "plan_name": target_run.plan_name,
            "rule_revision": target_run.rule_revision,
            "status": target_run.status,
            "created_at": target_run.created_at.isoformat(),
        },
        "summary": {
            "status": {
                "base": base_run.status,
                "target": target_run.status,
                "changed": status_changed,
            },
            "rule_revision": {
                "base": base_run.rule_revision,
                "target": target_run.rule_revision,
                "changed": base_run.rule_revision != target_run.rule_revision,
            },
            "first_danger": {
                "change": _danger_change_type(danger_a, danger_b),
                "base": _compact_danger(danger_a),
                "target": _compact_danger(danger_b),
            },
            "affected_steps": _set_diff(
                base.get("affected_steps", []), target.get("affected_steps", [])
            ),
            "blocked_steps": _set_diff(
                base.get("blocked_steps", []), target.get("blocked_steps", [])
            ),
            "warning_steps": _set_diff(
                base.get("warning_steps", []), target.get("warning_steps", [])
            ),
            "steps": _step_diff(base, target),
            "counts": _counts_changes(base, target),
            "finding_changes": counts,
        },
        "findings": entries,
    }
