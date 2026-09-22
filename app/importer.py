"""方案 CSV 导入：解析、逐行校验与单事务落库。

CSV 约定（UTF-8，允许 BOM；首行为表头）：

    步骤序号,试剂名,类别,时刻,用量,备注

- 步骤序号：必填，≥1 的整数，全文件唯一；导入后按序号升序重排为 0 基步骤顺序；
- 试剂名：必填；与试剂档案按名称精确匹配（忽略首尾空白）时复用档案试剂，
  未匹配的试剂仅在用户显式确认后作为"临时试剂"写入步骤（不创建试剂档案）；
- 类别：必填，一个或多个类别 key，可用 , ， ; ； 、 / 分隔；
  档案已存在试剂的类别以档案为准（与 CSV 不一致时给出提示，不阻断导入）；
- 时刻 / 用量：可空；填写时必须为 ≥ 0 的数值；
- 备注：可空，自由文本。

强约束：任何一行校验失败（序号重复、缺少试剂名/类别、数值非法等）都整体拒绝，
错误信息携带 CSV 行号（表头为第 1 行）与原因；方案与全部步骤在单个事务内创建，
校验失败或落库异常时不产生任何半成品数据。
"""
import csv
import io
import json
import math
import re

from sqlalchemy.orm import Session

from . import models

MAX_ROWS = 500  # 单次导入的最大数据行数（防御性上限）

_FIELD_LABELS = {
    "seq": "步骤序号",
    "reagent": "试剂名",
    "categories": "类别",
    "time": "时刻",
    "amount": "用量",
    "note": "备注",
}


def _norm_header(cell: str) -> str:
    """表头归一化：忽略首尾空白、大小写与全/半角括号差异。"""
    return (
        (cell or "")
        .strip()
        .lower()
        .replace("（", "(")
        .replace("）", ")")
        .replace(" ", "")
    )


_HEADER_ALIASES = {
    "seq": {"步骤序号", "序号"},
    "reagent": {"试剂名", "试剂名称", "试剂"},
    "categories": {"类别", "类别标签", "相容性类别"},
    "time": {"时刻", "时刻(min)", "时间", "时间(min)"},
    "amount": {"用量", "用量(ml)", "用量(ml/g)"},
    "note": {"备注", "说明", "操作备注"},
}
_ALIAS_TO_FIELD = {
    _norm_header(alias): field
    for field, aliases in _HEADER_ALIASES.items()
    for alias in aliases
}
_REQUIRED_FIELDS = ("seq", "reagent", "categories")
_CAT_SPLIT = re.compile(r"[,，;；、/]")


class ImportValidationError(ValueError):
    """CSV 校验失败：携带完整校验结果（路由层转 422，含行号与原因）。"""

    def __init__(self, result: dict):
        super().__init__(f"CSV 校验未通过：{len(result['errors'])} 处错误")
        self.result = result


class UnknownReagentsError(ValueError):
    """存在档案外试剂且未获用户确认（路由层转 409）。"""

    def __init__(self, names: list[str]):
        super().__init__("存在档案外试剂，需确认后作为临时试剂导入")
        self.names = names


def _split_categories(raw: str) -> list[str]:
    """类别单元格 → 类别 key 列表（去空白、去重、保序）。"""
    out: list[str] = []
    for part in _CAT_SPLIT.split(raw or ""):
        key = part.strip()
        if key and key not in out:
            out.append(key)
    return out


def _parse_seq(raw: str):
    """步骤序号：≥1 的整数（兼容 Excel 导出的 3.0 写法），非法返回 None。"""
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value) or not value.is_integer() or value < 1:
        return None
    return int(value)


def _parse_nonneg(raw: str):
    """≥0 的数值，非法返回 None。"""
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _read_records(csv_text: str) -> tuple[list, list]:
    """解析 CSV 文本 → (记录列表[(物理行号, 单元格)], 文件级错误)。"""
    text = csv_text or ""
    if text.startswith("\ufeff"):  # 兼容 UTF-8 BOM
        text = text[1:]
    if not text.strip():
        return [], [
            {"row": 1, "seq": None, "field": "文件", "reason": "CSV 内容为空"}
        ]
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    records = []
    reader = csv.reader(io.StringIO(text), dialect)
    for row in reader:
        if not any((cell or "").strip() for cell in row):
            continue  # 跳过空行
        records.append((reader.line_num, [(cell or "").strip() for cell in row]))
    return records, []


def validate_csv(db: Session, csv_text: str) -> dict:
    """解析并逐行校验 CSV，返回预览结果（不落库）。

    返回结构：
        valid             是否全部通过
        errors            [{row, seq, field, reason}]，row 为 CSV 物理行号（表头=1）
        warnings          [{row, seq, message}]，不阻断导入的提示
        steps             归一化后的步骤（含匹配到的档案试剂 ID / 临时试剂类别）
        unknown_reagents  档案中不存在、需用户确认后才能导入的试剂名
        matched_reagents  按名称复用的档案试剂
    """
    errors: list[dict] = []
    warnings: list[dict] = []
    steps: list[dict] = []

    records, file_errors = _read_records(csv_text)
    errors.extend(file_errors)

    col_map: dict[str, int] = {}
    data_records: list = []
    if records:
        header_row, header_cells = records[0]
        for idx, cell in enumerate(header_cells):
            field = _ALIAS_TO_FIELD.get(_norm_header(cell))
            if field is not None and field not in col_map:
                col_map[field] = idx
        for field in _REQUIRED_FIELDS:
            if field not in col_map:
                aliases = "、".join(sorted(_HEADER_ALIASES[field]))
                errors.append(
                    {
                        "row": header_row,
                        "seq": None,
                        "field": _FIELD_LABELS[field],
                        "reason": f"首行表头缺少「{_FIELD_LABELS[field]}」列（可用表头：{aliases}）",
                    }
                )
        data_records = records[1:]

    if records and not data_records and not any(e["field"] == "文件" for e in errors):
        errors.append(
            {
                "row": records[0][0],
                "seq": None,
                "field": "文件",
                "reason": "除表头外没有数据行",
            }
        )

    if len(data_records) > MAX_ROWS:
        errors.append(
            {
                "row": data_records[MAX_ROWS][0],
                "seq": None,
                "field": "文件",
                "reason": f"数据行超过单次导入上限 {MAX_ROWS} 行",
            }
        )
        data_records = data_records[:MAX_ROWS]

    def col(cells, field) -> str:
        idx = col_map.get(field)
        if idx is None or idx >= len(cells):
            return ""
        return cells[idx]

    # 必需表头缺失时文件结构已不成立，不再逐行校验（避免级联误报）
    if all(f in col_map for f in _REQUIRED_FIELDS):
        for line_no, cells in data_records:
            seq_raw = col(cells, "seq")
            seq = None
            if not seq_raw:
                errors.append(
                    {"row": line_no, "seq": None, "field": "步骤序号",
                     "reason": "缺少步骤序号"}
                )
            else:
                seq = _parse_seq(seq_raw)
                if seq is None:
                    errors.append(
                        {"row": line_no, "seq": None, "field": "步骤序号",
                         "reason": f"步骤序号「{seq_raw}」非法：必须是 ≥1 的整数"}
                    )

            name = col(cells, "reagent")
            if not name:
                errors.append(
                    {"row": line_no, "seq": seq, "field": "试剂名",
                     "reason": "缺少试剂名"}
                )
            elif len(name) > 128:
                errors.append(
                    {"row": line_no, "seq": seq, "field": "试剂名",
                     "reason": "试剂名超过 128 个字符"}
                )

            cats = _split_categories(col(cells, "categories"))
            if not cats:
                errors.append(
                    {"row": line_no, "seq": seq, "field": "类别",
                     "reason": "缺少类别（至少填写一个类别 key，多个用逗号分隔）"}
                )

            time_v = None
            time_raw = col(cells, "time")
            if time_raw:
                time_v = _parse_nonneg(time_raw)
                if time_v is None:
                    errors.append(
                        {"row": line_no, "seq": seq, "field": "时刻",
                         "reason": f"时刻「{time_raw}」非法：必须是 ≥0 的数值"}
                    )

            amount_v = None
            amount_raw = col(cells, "amount")
            if amount_raw:
                amount_v = _parse_nonneg(amount_raw)
                if amount_v is None:
                    errors.append(
                        {"row": line_no, "seq": seq, "field": "用量",
                         "reason": f"用量「{amount_raw}」非法：必须是 ≥0 的数值"}
                    )

            steps.append(
                {
                    "row": line_no,
                    "seq": seq,
                    "reagent_name": name,
                    "categories": cats,
                    "time_offset_min": time_v,
                    "amount_ml": amount_v,
                    "note": col(cells, "note") or None,
                }
            )

    # 序号全文件唯一（仅对序号本身合法的行查重）
    by_seq: dict[int, list] = {}
    for s in steps:
        if s["seq"] is not None:
            by_seq.setdefault(s["seq"], []).append(s)
    for seq, group in by_seq.items():
        if len(group) > 1:
            rows = "、".join(str(g["row"]) for g in group)
            for g in group:
                errors.append(
                    {"row": g["row"], "seq": seq, "field": "步骤序号",
                     "reason": f"步骤序号 {seq} 重复（出现于第 {rows} 行）"}
                )

    # 试剂档案按名称精确匹配：命中 → 复用档案试剂；未命中 → 待确认的临时试剂
    names = sorted({s["reagent_name"] for s in steps if s["reagent_name"]})
    by_name = {}
    if names:
        for r in db.query(models.Reagent).filter(models.Reagent.name.in_(names)).all():
            by_name[r.name] = r
    unknown: list[str] = []
    for s in steps:
        reagent = by_name.get(s["reagent_name"])
        if reagent is not None:
            archive_cats = json.loads(reagent.categories or "[]")
            s["reagent_id"] = reagent.id
            s["matched"] = True
            s["matched_categories"] = archive_cats
            if s["categories"] and sorted(s["categories"]) != sorted(archive_cats):
                warnings.append(
                    {"row": s["row"], "seq": s["seq"],
                     "message": f"试剂「{s['reagent_name']}」已存在于档案，CSV 类别与档案类别不一致，"
                                f"推演将使用档案类别（{'、'.join(archive_cats) or '无'}）"}
                )
        else:
            s["reagent_id"] = None
            s["matched"] = False
            s["matched_categories"] = None
            if s["reagent_name"] and s["reagent_name"] not in unknown:
                unknown.append(s["reagent_name"])

    matched = [
        {"name": r.name, "reagent_id": r.id,
         "categories": json.loads(r.categories or "[]")}
        for r in sorted(by_name.values(), key=lambda x: x.name)
    ]

    # 按序号升序重排为 0 基步骤顺序（序号非法的行排在末尾，仅用于预览展示）
    steps.sort(key=lambda s: (s["seq"] if s["seq"] is not None else math.inf, s["row"]))
    for i, s in enumerate(steps):
        s["order_index"] = i

    err_rows = {e["row"] for e in errors}
    for s in steps:
        s["ok"] = s["row"] not in err_rows
    errors.sort(key=lambda e: (e["row"], e["field"]))

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "total_rows": len(steps),
        "steps": steps,
        "unknown_reagents": unknown,
        "matched_reagents": matched,
    }


def create_plan_from_csv(
    db: Session,
    *,
    name: str,
    description: str | None,
    csv_text: str,
    allow_unknown_reagents: bool,
):
    """校验并创建方案 + 全部步骤（单个事务；任何失败整体回滚，不留半成品）。

    导入的步骤不写任何安全确认数据（均为待确认），现有预检 / 正式推演门槛照常生效。
    """
    result = validate_csv(db, csv_text)
    if result["errors"]:
        raise ImportValidationError(result)
    unknown = result["unknown_reagents"]
    if unknown and not allow_unknown_reagents:
        raise UnknownReagentsError(unknown)
    try:
        plan = models.Plan(name=name, description=description)
        db.add(plan)
        db.flush()
        for s in result["steps"]:
            db.add(
                models.Step(
                    plan_id=plan.id,
                    order_index=s["order_index"],
                    time_offset_min=s["time_offset_min"],
                    reagent_id=s["reagent_id"],
                    reagent_name=s["reagent_name"],
                    # 档案试剂以档案类别为准（步骤快照留空，与手工编辑器一致）；
                    # 临时试剂把 CSV 类别作为快照写入步骤
                    categories=json.dumps(
                        [] if s["reagent_id"] is not None else s["categories"],
                        ensure_ascii=False,
                    ),
                    amount_ml=s["amount_ml"],
                    note=s["note"],
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(plan)
    return plan, result
