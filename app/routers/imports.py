"""方案 CSV 导入：预览校验（不落库）与单事务提交。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import importer
from ..database import get_db
from ..schemas import ImportPreviewIn, PlanImportIn
from .plans import _plan_out

# 注意：/api/plans/import 必须在 plans 路由的 /api/plans/{plan_id} 之前注册（见 main.py）
router = APIRouter(prefix="/api/plans/import", tags=["imports"])


@router.post("/preview")
def preview_import(payload: ImportPreviewIn, db: Session = Depends(get_db)):
    """解析 CSV 并逐行校验：返回每行状态、全部错误的行号与原因；不写库。

    响应中 unknown_reagents 为档案中不存在的试剂——提交导入时需用户确认，
    确认后作为临时试剂写入步骤（不创建试剂档案）。
    """
    return importer.validate_csv(db, payload.csv_text)


@router.post("", status_code=201)
def commit_import(payload: PlanImportIn, db: Session = Depends(get_db)):
    """导入即建方案：方案与全部步骤在单个事务内创建。

    任何序号重复、缺少试剂名/类别或数值非法都整体拒绝（422，含行号与原因），
    不产生半成品；存在档案外试剂时必须显式确认，否则 409。
    导入步骤的安全确认均为待确认，现有预检 / 正式推演门槛照常生效。
    """
    try:
        plan, result = importer.create_plan_from_csv(
            db,
            name=payload.name.strip(),
            description=(payload.description or "").strip() or None,
            csv_text=payload.csv_text,
            allow_unknown_reagents=payload.allow_unknown_reagents,
        )
    except importer.ImportValidationError as exc:
        errors = exc.result["errors"]
        raise HTTPException(
            422,
            detail={
                "message": f"CSV 校验未通过（{len(errors)} 处错误），已整体拒绝，未创建任何数据",
                "errors": errors,
                "warnings": exc.result["warnings"],
            },
        ) from exc
    except importer.UnknownReagentsError as exc:
        raise HTTPException(
            409,
            detail={
                "message": "以下试剂不在试剂档案中，需确认作为临时试剂导入后才能提交："
                + "、".join(exc.names),
                "unknown_reagents": exc.names,
            },
        ) from exc
    return {
        "plan": _plan_out(db, plan),
        "import": {
            "total_rows": result["total_rows"],
            "matched_reagents": result["matched_reagents"],
            "temporary_reagents": result["unknown_reagents"],
            "warnings": result["warnings"],
            # 导入结果的安全确认口径：全部步骤均为待确认
            "safety": "pending",
        },
    }
