"""相容性推演引擎。

输入：带类别标签的试剂序列（按时间/顺序排列的加液步骤）+ 规则图
输出：逐步推演报告——每一步将"待加入试剂"与"当前体系内所有试剂"两两比对，
      命中规则即生成 finding；首次出现 high 级命中即标记首次危险并中止推演，
      尚未执行的步骤标记为 affected（受影响/阻断）。
每个 finding 都带有可追溯的判定依据：命中规则 ID、标题、方程式、机理说明、
来源类别、参与步骤编号以及参考文献。
"""
import json
from dataclasses import dataclass, field

from . import rules_store

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
SEVERITY_LABEL = {"low": "提示", "medium": "警示", "high": "严重"}
STATUS_LABEL = {"safe": "安全", "warning": "存在警示", "danger": "存在严重危险"}


@dataclass
class InputReagent:
    name: str
    categories: list[str] = field(default_factory=list)


@dataclass
class InputStep:
    order_index: int
    reagent: InputReagent
    time_offset_min: float | None = None
    amount_ml: float | None = None
    note: str | None = None


def _rule_matches(rule, src_cat: str, tgt_cat: str) -> bool:
    """规则边是否匹配给定的有序类别对。

    无向边：正向或反向匹配均可；有向边：仅 source->target。
    """
    if rule.source == src_cat and rule.target == tgt_cat:
        return True
    if not rule.directional and rule.source == tgt_cat and rule.target == src_cat:
        return True
    return False


def _direction_for(rule, incoming_cat: str, existing_cat: str) -> str:
    if rule.source == incoming_cat and rule.target == existing_cat:
        return "incoming->existing"
    return "existing->incoming"


def simulate(steps: list[InputStep], db_rules, revision: str) -> dict:
    """执行逐步推演。db_rules: 已激活的规则 ORM 列表。"""
    findings: list[dict] = []
    timeline: list[dict] = []
    # 体系快照：已成功加入的试剂（类别集合 + 进入步骤）
    present: list[dict] = []
    first_danger = None
    halted = False

    finding_seq = 0

    for step in steps:
        incoming = step.reagent
        if halted:
            timeline.append(
                {
                    "order_index": step.order_index,
                    "reagent_name": incoming.name,
                    "state": "blocked",
                    "state_label": "已阻断",
                    "time_offset_min": step.time_offset_min,
                    "amount_ml": step.amount_ml,
                    "note": step.note,
                    "finding_ids": [],
                    "present_after": [p["reagent_name"] for p in present],
                }
            )
            continue

        step_finding_ids: list[str] = []
        step_pairs: list[dict] = []

        for entry in present:
            # 同一试剂分批加入（名称相同）不与其自身历史步骤做配对，避免自反应误报
            if entry["reagent_name"] == incoming.name:
                continue
            existing_cats = set(entry["categories"])
            incoming_cats = set(incoming.categories)
            matched_rule_ids: set[str] = set()

            for ic in incoming_cats:
                for ec in existing_cats:
                    for rule in db_rules:
                        if rule.id in matched_rule_ids:
                            continue
                        if _rule_matches(rule, ic, ec):
                            matched_rule_ids.add(rule.id)
                            finding_seq += 1
                            fid = f"F{finding_seq:03d}"
                            finding = {
                                "id": fid,
                                "rule_id": rule.id,
                                "severity": rule.severity,
                                "severity_label": SEVERITY_LABEL[rule.severity],
                                "title": rule.title,
                                "reaction": rule.reaction,
                                "rationale": rule.rationale,
                                "references": json.loads(rule.references or "[]"),
                                "incoming_step": step.order_index,
                                "incoming_reagent": incoming.name,
                                "incoming_category": ic,
                                "existing_step": entry["step"],
                                "existing_reagent": entry["reagent_name"],
                                "existing_category": ec,
                                "match_direction": _direction_for(rule, ic, ec),
                                "rule_directional": bool(rule.directional),
                            }
                            findings.append(finding)
                            step_finding_ids.append(fid)
                            step_pairs.append(
                                {
                                    "finding_id": fid,
                                    "rule_id": rule.id,
                                    "with_reagent": entry["reagent_name"],
                                    "incoming_category": ic,
                                    "existing_category": ec,
                                }
                            )

        worst = max(
            (SEVERITY_RANK[f["severity"]] for f in findings if f["id"] in step_finding_ids),
            default=0,
        )
        if step_finding_ids and worst >= SEVERITY_RANK["high"]:
            state = "danger"
            state_label = "发生严重反应"
        elif step_finding_ids:
            state = "warning"
            state_label = "发生警示反应"
        else:
            state = "ok"
            state_label = "相容"

        timeline.append(
            {
                "order_index": step.order_index,
                "reagent_name": incoming.name,
                "reagent_categories": list(incoming.categories),
                "state": state,
                "state_label": state_label,
                "time_offset_min": step.time_offset_min,
                "amount_ml": step.amount_ml,
                "note": step.note,
                "finding_ids": step_finding_ids,
                "interactions": step_pairs,
                "present_after": [p["reagent_name"] for p in present] + [incoming.name],
            }
        )

        if worst >= SEVERITY_RANK["high"]:
            halted = True
            danger_f = next(
                f for f in findings
                if f["id"] in step_finding_ids and f["severity"] == "high"
            )
            first_danger = {
                "finding_id": danger_f["id"],
                "step": step.order_index,
                "reagent_name": incoming.name,
                "conflicts_with_step": danger_f["existing_step"],
                "conflicts_with_reagent": danger_f["existing_reagent"],
                "rule_id": danger_f["rule_id"],
                "title": danger_f["title"],
                "reaction": danger_f["reaction"],
                "rationale": danger_f["rationale"],
                "references": danger_f["references"],
            }
            # 严重反应发生，该试剂视为未安全加入体系，后续步骤阻断
            timeline[-1]["present_after"] = [p["reagent_name"] for p in present]
        else:
            present.append(
                {
                    "reagent_name": incoming.name,
                    "categories": list(incoming.categories),
                    "step": step.order_index,
                }
            )

    # 汇总
    counts = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        counts[f["severity"]] += 1

    if halted:
        status = "danger"
    elif counts["medium"] or counts["low"]:
        status = "warning"
    else:
        status = "safe"

    blocked_steps = [t["order_index"] for t in timeline if t["state"] == "blocked"]
    reacted_steps = [
        t["order_index"] for t in timeline if t["state"] in ("warning", "danger")
    ]
    affected_steps = sorted(set(blocked_steps + reacted_steps))

    return {
        "engine": "labmix-compat-engine",
        "engine_version": "1.0",
        "rule_revision": revision,
        "status": status,
        "status_label": STATUS_LABEL[status],
        "halted": halted,
        "first_danger": first_danger,
        "affected_steps": affected_steps,
        "blocked_steps": blocked_steps,
        "warning_steps": [
            t["order_index"] for t in timeline if t["state"] == "warning"
        ],
        "summary": {
            "total_steps": len(steps),
            "executed_steps": len(steps) - len(blocked_steps),
            "findings": len(findings),
            "high": counts["high"],
            "medium": counts["medium"],
            "low": counts["low"],
        },
        "timeline": timeline,
        "findings": findings,
    }
