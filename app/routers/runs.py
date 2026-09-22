"""历史推演记录、版本差异比较与结果 JSON 导出。"""
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..diffing import PlanMismatchError, build_run_diff

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("")
def list_runs(limit: int = 100, db: Session = Depends(get_db)):
    runs = (
        db.query(models.Run)
        .order_by(models.Run.created_at.desc())
        .limit(min(limit, 500))
        .all()
    )
    return [
        {
            "id": r.id,
            "plan_id": r.plan_id,
            "plan_name": r.plan_name,
            "rule_revision": r.rule_revision,
            "rule_version_id": r.rule_version_id,
            "status": r.status,
            "created_at": r.created_at,
        }
        for r in runs
    ]


def _get_run_or_404(db: Session, run_id: int, role: str = "推演记录") -> models.Run:
    run = db.get(models.Run, run_id)
    if run is None:
        raise HTTPException(404, f"{role} #{run_id} 不存在")
    return run


def _diff_or_4xx(db: Session, base_id: int, target_id: int) -> dict:
    """取两条记录并生成差异；记录缺失 404、自身比较 400、方案不一致 409。"""
    if base_id == target_id:
        raise HTTPException(400, "请选择两条不同的推演记录进行版本差异比较")
    base = _get_run_or_404(db, base_id, "基准推演记录")
    target = _get_run_or_404(db, target_id, "对照推演记录")
    try:
        return build_run_diff(base, target)
    except PlanMismatchError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/diff")
def compare_runs(
    base_id: int = Query(..., description="基准（较早）推演记录 ID"),
    target_id: int = Query(..., description="对照（较新）推演记录 ID"),
    db: Session = Depends(get_db),
):
    """比较同一方案的两条历史推演记录，返回规则版本差异视图。"""
    return _diff_or_4xx(db, base_id, target_id)


@router.get("/diff/export")
def export_run_diff(
    base_id: int = Query(..., description="基准（较早）推演记录 ID"),
    target_id: int = Query(..., description="对照（较新）推演记录 ID"),
    db: Session = Depends(get_db),
):
    """导出两条记录的版本差异 JSON 文件。"""
    diff = _diff_or_4xx(db, base_id, target_id)
    return JSONResponse(
        diff,
        headers={
            "Content-Disposition": f'attachment; filename="runs-{base_id}-vs-{target_id}-diff.json"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id)
    return json.loads(run.report) | {"id": run.id, "created_at": run.created_at.isoformat()}


@router.get("/{run_id}/export")
def export_run(run_id: int, db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id)
    report = json.loads(run.report)
    report["run_id"] = run.id
    report["exported_at"] = run.created_at.isoformat()
    return JSONResponse(
        report,
        headers={
            "Content-Disposition": f'attachment; filename="run-{run_id}-report.json"',
            "Cache-Control": "no-store",
        },
    )


@router.delete("/{run_id}", status_code=204)
def delete_run(run_id: int, db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id)
    db.delete(run)
    db.commit()
