"""方案 CSV 导入：UTF-8 解析、逐行校验、单事务落库。

CSV 格式（首行表头，列顺序任意，支持中 / 英文别名）：

    步骤序号,试剂名,类别,时刻,用量,备注

- 类别列内多个类别可用 , ， ; ； 、 / | 分隔（含逗号的单元格需按 CSV 规范加引号）；
- 时刻 / 用量可留空（视为未填写），填写时必须为非负有限数值；
- 步骤序号必须为非负整数且全表唯一。

强约束：
- 任何行校验失败（序号重复、缺试剂名 / 类别、数值非法）→ 整体拒绝，
  返回行号与原因，不产生半成品；
- 已建档试剂按名称精确复用（关联 reagent_id，类别以档案实时值为准）；
- 未建档试剂仅在调用方显式确认（allow_unknown_reagents=True）后
  作为临时试剂写入步骤，不创建试剂档案；
- 导入步骤的安全确认一律为"待确认"（safety_confirmed=False），
  现有预检 / 正式推演门槛保持不变。
"""
import csv
import io
import json
import math
import re
from dataclasses import dataclass, field as dc_field

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models

MAX_ROWS = 500  # 单次导入最多步骤数
MAX_NAME_LEN = 128
MAX_CAT_LEN = 64
MAX_NOTE_LEN = 500

# 表头别名（比较前统一 strip / lower / 去空白）
_HEADER_ALIASES = {
    "order": {"步骤序号", "序号", "步骤", "order", "order_index", "step", "no"},
    "reagent": {"试剂名", "试剂名称", "试剂", "reagent", "reagent_name", "name"},
    "categories": {"类别", "类别标签", "相容性类别", "categories", "category"},
    "time": {"时刻", "时刻(min)", "时刻（min）", "时间", "time", "time_offset_min"},
    "amount": {"用量", "用量(ml)", "用量（ml）", "用量(ml/g)", "用量（ml/g）", "amount", "amount_ml"},
    "note": {"备注", "说明", "note", "remark"},
}
_REQUIRED = ("order", "reagent", "categories")
COLUMN_LABEL = {
    "order": "步骤序号",
    "reagent": "试剂名",
    "categories": "类别",
    "time": "时刻",
    "amount": "用量",
    "note": "备注",
}

_CAT_SPLIT = re.compile(r"[,，;；、/|]+")
_ORDER_RE = re.compile(r"\d{1,9}")


@dataclass
class ImportRow:
    """一行 CSV 数据的解析与校验结果。row 为 CSV 物理行号（表头为第 1 行）。"""

    row: int
    order_index: int | None = None
    reagent_name: str = ""
    categories: list[str] = dc_field(default_factory=list)
    time_offset_min: float | None = None
    amount_ml: float | None = None
    note: str | None = None
    errors: list[str] = dc_field(default_factory=list)


def _norm_header(cell: str) -> str:
    return re.sub(r"\s+", "", cell or "").lower()


def _header_map(header: list[str]) -> tuple[dict[int, str], list[str]]:
    """表头列号 → 逻辑列名；返回 (映射, 文件级错误)。未识别列忽略。"""
    norm_to_key = {}
    for key, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            norm_to_key[_norm_header(alias)] = key
    mapping: dict[int, str] = {}
    seen: dict[str, int] = {}
    errors: list[str] = []
    for idx, cell in enumerate(header):
        norm = _norm_header(cell)
        if not norm:
            continue
        key = norm_to_key.get(norm)
        if key is None:
            continue
        if key in seen:
            errors.append(
                f"表头列「{cell.strip()}」重复（第 {seen[key] + 1} 列与第 {idx + 1} 列）"
            )
            continue
        seen[key] = idx
        mapping[idx] = key
    missing = [COLUMN_LABEL[k] for k in _REQUIRED if k not in seen]
    if missing:
        errors.append(
            "缺少必需表头列：" + "、".join(missing)
            + "；表头应为：步骤序号,试剂名,类别,时刻,用量,备注（时刻/用量/备注列可省略）"
        )
    return mapping, errors


def _parse_number(raw: str, label: str, errors: list[str]) -> float | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        value = float(s)
    except ValueError:
        errors.append(f"{label}「{s}」数值非法：不是有效数字")
        return None
    if not math.isfinite(value) or value < 0:
        errors.append(f"{label}「{s}」数值非法：必须为非负有限数值")
        return None
    return value


def _parse_row(record: list[str], mapping: dict[int, str], header_len: int, line_no: int) -> ImportRow:
    row = ImportRow(row=line_no)
    if len(record) > header_len:
        row.errors.append(
            f"列数（{len(record)}）超过表头列数（{header_len}），"
            "请检查是否有多余逗号（含逗号的文本需用双引号包围）"
        )
        return row
    cells = {key: (record[idx] if idx < len(record) else "") for idx, key in mapping.items()}

    raw_order = cells.get("order", "").strip()
    if not raw_order:
        row.errors.append("步骤序号不能为空")
    elif not _ORDER_RE.fullmatch(raw_order):
        row.errors.append(f"步骤序号「{raw_order}」非法：必须为非负整数")
    else:
        row.order_index = int(raw_order)

    name = cells.get("reagent", "").strip()
    if not name:
        row.errors.append("试剂名不能为空")
    elif len(name) > MAX_NAME_LEN:
        row.errors.append(f"试剂名超长（>{MAX_NAME_LEN} 字符）")
    else:
        row.reagent_name = name

    cats: list[str] = []
    for c in _CAT_SPLIT.split(cells.get("categories", "")):
        c = c.strip()
        if c and c not in cats:
            cats.append(c)
    if not cats:
        row.errors.append("类别不能为空（多个类别可用分号分隔）")
    elif any(len(c) > MAX_CAT_LEN for c in cats):
        row.errors.append(f"类别标签超长（>{MAX_CAT_LEN} 字符）")
    else:
        row.categories = cats

    row.time_offset_min = _parse_number(cells.get("time", ""), "时刻", row.errors)
    row.amount_ml = _parse_number(cells.get("amount", ""), "用量", row.errors)

    note = cells.get("note", "").strip()
    if len(note) > MAX_NOTE_LEN:
        row.errors.append(f"备注超长（>{MAX_NOTE_LEN} 字符）")
    row.note = note or None
    return row


def parse_csv(text: str) -> tuple[list[ImportRow], list[str]]:
    """解析并逐行校验；返回 (数据行, 文件级错误)。行级错误记录在 ImportRow.errors。"""
    text = (text or "").lstrip("\ufeff")  # 兼容带 BOM 的 UTF-8 文件
    if not text.strip():
        return [], ["CSV 内容为空"]
    if "\ufffd" in text:
        return [], ["检测到乱码字符（U+FFFD）：文件似乎不是 UTF-8 编码，请另存为 UTF-8 后重试"]

    rows: list[ImportRow] = []
    mapping: dict[int, str] | None = None
    header_len = 0
    prev_end_line = 0
    reader = csv.reader(io.StringIO(text), strict=True)
    try:
        for record in reader:
            start_line = prev_end_line + 1
            prev_end_line = reader.line_num
            if mapping is None:
                if not any((c or "").strip() for c in record):
                    continue  # 跳过表头前的空行
                mapping, file_errors = _header_map(record)
                if file_errors:
                    return [], file_errors
                header_len = len(record)
                continue
            if not any((c or "").strip() for c in record):
                continue  # 空白行跳过（仍占物理行号）
            rows.append(_parse_row(record, mapping, header_len, start_line))
            if len(rows) > MAX_ROWS:
                return [], [f"数据行超过上限（{MAX_ROWS} 行）"]
    except csv.Error as exc:
        return [], [f"CSV 解析失败（第 {reader.line_num} 行附近）：{exc}"]

    if mapping is None:
        return [], ["CSV 内容为空"]
    return rows, []


def _check_duplicates(rows: list[ImportRow]) -> None:
    """跨行校验：步骤序号全表唯一，重复时每一行都标注与其冲突的首行行号。"""
    seen: dict[int, int] = {}
    for r in rows:
        if r.order_index is None:
            continue
        if r.order_index in seen:
            r.errors.append(f"步骤序号 {r.order_index} 与第 {seen[r.order_index]} 行重复")
        else:
            seen[r.order_index] = r.row


def resolve_reagents(db: Session, rows: list[ImportRow]) -> dict[str, models.Reagent]:
    """按名称精确匹配已建档试剂（去空白后严格相等）。"""
    names = sorted({r.reagent_name for r in rows if r.reagent_name})
    if not names:
        return {}
    found = db.query(models.Reagent).filter(models.Reagent.name.in_(names)).all()
    return {r.name: r for r in found}


def _analyze(db: Session, csv_text: str):
    """解析 + 校验 + 试剂匹配，返回 (数据行, 试剂映射, 预览字典)。"""
    rows, file_errors = parse_csv(csv_text)
    if rows:
        _check_duplicates(rows)
    elif not file_errors:
        file_errors = ["没有有效数据行"]
    reagent_map = resolve_reagents(db, rows)

    out_rows = []
    known: list[str] = []
    unknown: list[str] = []
    for r in rows:
        reagent = reagent_map.get(r.reagent_name)
        if reagent is not None:
            if reagent.name not in known:
                known.append(reagent.name)
        elif r.reagent_name and r.reagent_name not in unknown:
            unknown.append(r.reagent_name)
        out_rows.append(
            {
                "row": r.row,
                "order_index": r.order_index,
                "reagent_name": r.reagent_name,
                "categories": r.categories,
                "time_offset_min": r.time_offset_min,
                "amount_ml": r.amount_ml,
                "note": r.note,
                "errors": r.errors,
                "reagent_id": reagent.id if reagent else None,
                "archive_categories": json.loads(reagent.categories or "[]") if reagent else [],
                "temporary": reagent is None and bool(r.reagent_name),
            }
        )
    invalid = sum(1 for r in rows if r.errors)
    preview = {
        "ok": not file_errors and invalid == 0 and bool(rows),
        "file_errors": file_errors,
        "errors": [
            {"row": r.row, "reason": reason} for r in rows for reason in r.errors
        ],
        "rows": out_rows,
        "summary": {
            "total_rows": len(rows),
            "valid_rows": len(rows) - invalid,
            "invalid_rows": invalid,
            "known_reagents": known,
            "unknown_reagents": unknown,
        },
    }
    return rows, reagent_map, preview


def build_preview(db: Session, csv_text: str) -> dict:
    """预览接口：解析 + 逐行校验 + 试剂匹配，不落库。"""
    _, _, preview = _analyze(db, csv_text)
    return preview


def commit_import(
    db: Session,
    *,
    name: str,
    description: str | None,
    csv_text: str,
    allow_unknown_reagents: bool,
) -> tuple[models.Plan, dict]:
    """单事务创建方案与全部步骤；任何校验失败整体拒绝（不落任何数据）。

    全部校验在写入前完成；写入阶段任何异常都会回滚，保证不产生半成品。
    """
    rows, reagent_map, preview = _analyze(db, csv_text)
    if not preview["ok"]:
        raise HTTPException(
            422,
            detail={
                "message": "CSV 校验未通过，已整体拒绝，未写入任何数据",
                "file_errors": preview["file_errors"],
                "errors": preview["errors"],
            },
        )
    unknown = preview["summary"]["unknown_reagents"]
    if unknown and not allow_unknown_reagents:
        raise HTTPException(
            409,
            detail={
                "message": "存在未建档试剂：" + "、".join(unknown)
                + "。确认作为临时试剂导入（不创建试剂档案）后重新提交。",
                "unknown_reagents": unknown,
            },
        )

    plan = models.Plan(name=name, description=description)
    db.add(plan)
    try:
        db.flush()
        for r in sorted(rows, key=lambda x: (x.order_index, x.row)):
            reagent = reagent_map.get(r.reagent_name)
            db.add(
                models.Step(
                    plan_id=plan.id,
                    order_index=r.order_index,
                    time_offset_min=r.time_offset_min,
                    reagent_id=reagent.id if reagent else None,
                    reagent_name=reagent.name if reagent else r.reagent_name,
                    categories="[]" if reagent else json.dumps(r.categories, ensure_ascii=False),
                    amount_ml=r.amount_ml,
                    note=r.note,
                    # 安全确认保持默认"待确认"：safety_confirmed=False，
                    # 正式推演门槛（safety.assert_all_confirmed）照常生效
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(plan)
    summary = {
        "total_steps": len(rows),
        "known_reagents": preview["summary"]["known_reagents"],
        "temporary_reagents": list(unknown),
        "safety_pending": True,
    }
    return plan, summary
