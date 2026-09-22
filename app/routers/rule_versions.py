"""方案级规则版本：创建版本、编辑草稿、发布、停用与版本间差异。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, rules_store, versioning
from ..database import get_db
from ..schemas import RuleVersionCreate, RuleVersionUpdate

router = APIRouter(
    prefix="/api/plans/{plan_id}/rule-versions",
    tags=["rule-versions"],
)


def _get_plan_or_404(db: Session, plan_id: int) -> models.Plan:
    plan = db.get(models.Plan, plan_id)
    if plan is None:
        raise HTTPException(404, f"方案 #{plan_id} 不存在")
    return plan


def _get_version_or_404(db: Session, plan_id: int, version_id: int) -> models.RuleVersion:
    version = versioning.get_version_or_none(db, plan_id, version_id)
    if version is None:
        raise HTTPException(404, f"规则版本 #{version_id} 不存在或不属于方案 #{plan_id}")
    return version


def _payload_rules(payload: RuleVersionCreate | RuleVersionUpdate | None):
    if payload is None or payload.rules is None:
        return None
    return [r.model_dump() for r in payload.rules]


@router.get("")
def list_versions(plan_id: int, db: Session = Depends(get_db)):
    """方案下全部规则版本（草稿/生效/已替代/停用），按版本号倒序。"""
    _get_plan_or_404(db, plan_id)
    versions = (
        db.query(models.RuleVersion)
        .filter(models.RuleVersion.plan_id == plan_id)
        .order_by(models.RuleVersion.version_no.desc())
        .all()
    )
    effective = versioning.get_published_version(db, plan_id)
    eff_id = effective.id if effective else None
    return {
        "plan_id": plan_id,
        "effective_version_id": eff_id,
        "global_revision": rules_store.get_rule_revision(),
        "versions": [
            versioning.version_out(db, v, is_effective=(v.id == eff_id)) for v in versions
        ],
    }


# 注意：/diff 必须注册在 /{version_id} 之前，否则 "diff" 会被当成版本 ID
@router.get("/diff")
def diff_versions(
    plan_id: int,
    base: str = Query(
        ...,
        description="基准版本 ID；特殊值 global=当前全局限定规则图（启用中规则）",
    ),
    target: str = Query(
        "",
        description="对照版本 ID；特殊值 global=全局限定规则图；缺省=当前生效版本",
    ),
    db: Session = Depends(get_db),
):
    """按规则 ID 对齐两个版本（任一版本可为全局限定规则图），查看规则差异与级别依据变化。"""
    plan = _get_plan_or_404(db, plan_id)

    def resolve(token: str, *, role: str):
        token = (token or "").strip()
        if token in ("", "global", "current"):
            if token == "current":
                eff = versioning.get_published_version(db, plan_id)
                if eff is None:
                    raise HTTPException(409, "该方案当前没有生效的规则版本，无法作为对照")
                return ("version", eff)
            return ("global", None)
        try:
            vid = int(token)
        except ValueError:
            raise HTTPException(422, f"{role}版本 ID 必须是数字或特殊值 global/current")
        return ("version", _get_version_or_404(db, plan_id, vid))

    base_kind, base_obj = resolve(base, role="基准")
    target_kind, target_obj = resolve(target, role="对照")

    global_revision = rules_store.get_rule_revision()
    if base_kind == "global":
        base_rules = versioning.snapshot_active_global_rules(db)
        base_meta = versioning.global_side_meta(global_revision)
    else:
        base_rules = versioning.snapshot_version_rules(base_obj)
        base_meta = versioning.version_side_meta(base_obj)
    if target_kind == "global":
        target_rules = versioning.snapshot_active_global_rules(db)
        target_meta = versioning.global_side_meta(global_revision)
    else:
        target_rules = versioning.snapshot_version_rules(target_obj)
        target_meta = versioning.version_side_meta(target_obj)

    if base_meta.get("version_id") == target_meta.get("version_id") and base_kind == target_kind:
        raise HTTPException(400, "请选择两个不同的规则版本进行比较")

    diff = versioning.diff_rules(base_rules, target_rules)
    return {
        "kind": "labmix-rule-version-diff",
        "plan_id": plan_id,
        "plan_name": plan.name,
        "global_revision": global_revision,
        "base": base_meta,
        "target": target_meta,
        **diff,
    }


@router.post("", status_code=201)
def create_version(plan_id: int, payload: RuleVersionCreate, db: Session = Depends(get_db)):
    _get_plan_or_404(db, plan_id)

    base = None
    if payload.base_version_id is not None:
        base = _get_version_or_404(db, plan_id, payload.base_version_id)

    try:
        version = versioning.create_version(
            db,
            plan_id,
            note=payload.note,
            rules=_payload_rules(payload),
            base=base,
        )
    except versioning.RuleVersionError as exc:
        raise HTTPException(409, str(exc)) from exc
    return versioning.version_out(db, version, is_effective=False)


@router.get("/{version_id}")
def get_version(plan_id: int, version_id: int, db: Session = Depends(get_db)):
    version = _get_version_or_404(db, plan_id, version_id)
    return versioning.version_out(db, version)


@router.put("/{version_id}")
def update_version(
    plan_id: int,
    version_id: int,
    payload: RuleVersionUpdate,
    db: Session = Depends(get_db),
):
    version = _get_version_or_404(db, plan_id, version_id)
    try:
        version = versioning.update_draft(
            db, version, note=payload.note, rules=_payload_rules(payload)
        )
    except versioning.RuleVersionError as exc:
        raise HTTPException(409, str(exc)) from exc
    return versioning.version_out(db, version)


@router.post("/{version_id}/publish")
def publish_version(plan_id: int, version_id: int, db: Session = Depends(get_db)):
    """发布草稿：成为该方案唯一当前生效版本，原生效版本转为已替代。"""
    version = _get_version_or_404(db, plan_id, version_id)
    try:
        version = versioning.publish(db, version)
    except versioning.RuleVersionError as exc:
        raise HTTPException(409, str(exc)) from exc
    return versioning.version_out(db, version, is_effective=True)


@router.post("/{version_id}/deactivate")
def deactivate_version(plan_id: int, version_id: int, db: Session = Depends(get_db)):
    """停用当前生效版本：之后判定接口不再读取方案版本（回落全局规则图）。"""
    version = _get_version_or_404(db, plan_id, version_id)
    try:
        version = versioning.deactivate(db, version)
    except versioning.RuleVersionError as exc:
        raise HTTPException(409, str(exc)) from exc
    return versioning.version_out(db, version, is_effective=False)


@router.delete("/{version_id}", status_code=204)
def delete_version(plan_id: int, version_id: int, db: Session = Depends(get_db)):
    version = _get_version_or_404(db, plan_id, version_id)
    try:
        versioning.delete_version(db, version)
    except versioning.RuleVersionError as exc:
        raise HTTPException(409, str(exc)) from exc
