"""试剂属性档案管理。"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..schemas import ReagentCreate, ReagentOut, ReagentUpdate

router = APIRouter(prefix="/api/reagents", tags=["reagents"])


@router.get("", response_model=list[ReagentOut])
def list_reagents(q: str | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Reagent)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (models.Reagent.name.like(like))
            | (models.Reagent.cas.like(like))
            | (models.Reagent.formula.like(like))
        )
    return query.order_by(models.Reagent.name).all()


@router.post("", response_model=ReagentOut, status_code=201)
def create_reagent(reagent_in: ReagentCreate, db: Session = Depends(get_db)):
    exists = db.query(models.Reagent).filter_by(name=reagent_in.name).first()
    if exists:
        raise HTTPException(409, f"试剂「{reagent_in.name}」已存在")
    reagent = models.Reagent(
        name=reagent_in.name,
        cas=reagent_in.cas,
        formula=reagent_in.formula,
        concentration=reagent_in.concentration,
        state=reagent_in.state,
        categories=json.dumps(reagent_in.categories, ensure_ascii=False),
        note=reagent_in.note,
        builtin=False,
    )
    db.add(reagent)
    db.commit()
    db.refresh(reagent)
    return reagent


@router.get("/{reagent_id}", response_model=ReagentOut)
def get_reagent(reagent_id: int, db: Session = Depends(get_db)):
    reagent = db.get(models.Reagent, reagent_id)
    if reagent is None:
        raise HTTPException(404, "试剂不存在")
    return reagent


@router.put("/{reagent_id}", response_model=ReagentOut)
def update_reagent(
    reagent_id: int, reagent_in: ReagentUpdate, db: Session = Depends(get_db)
):
    reagent = db.get(models.Reagent, reagent_id)
    if reagent is None:
        raise HTTPException(404, "试剂不存在")
    data = reagent_in.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        dup = (
            db.query(models.Reagent)
            .filter(models.Reagent.name == data["name"], models.Reagent.id != reagent_id)
            .first()
        )
        if dup:
            raise HTTPException(409, f"试剂「{data['name']}」已存在")
    if "categories" in data and data["categories"] is not None:
        reagent.categories = json.dumps(data.pop("categories"), ensure_ascii=False)
    for key, value in data.items():
        setattr(reagent, key, value)
    db.commit()
    db.refresh(reagent)
    return reagent


@router.delete("/{reagent_id}", status_code=204)
def delete_reagent(reagent_id: int, db: Session = Depends(get_db)):
    reagent = db.get(models.Reagent, reagent_id)
    if reagent is None:
        raise HTTPException(404, "试剂不存在")
    used = db.query(models.Step).filter_by(reagent_id=reagent_id).count()
    if used:
        raise HTTPException(
            409,
            f"试剂「{reagent.name}」正被 {used} 个加液步骤引用，请先修改相关方案后再删除。",
        )
    db.delete(reagent)
    db.commit()
