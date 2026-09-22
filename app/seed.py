"""首次启动时写入内置试剂与示例方案。"""
import json

from sqlalchemy.orm import Session

from . import models

BUILTIN_REAGENTS = [
    ("盐酸", "7647-01-0", "HCl", "36%~38%", "liquid", ["strong_acid", "halide_salt"], "浓盐酸，强酸"),
    ("硫酸", "7664-93-9", "H₂SO₄", "98%", "liquid", ["strong_acid"], "浓硫酸，强腐蚀、强脱水"),
    ("硝酸", "7697-37-2", "HNO₃", "65%~68%", "liquid", ["strong_acid", "oxidizer", "nitrate"], "浓硝酸，强氧化性酸"),
    ("氢氧化钠溶液", "1310-73-2", "NaOH", "2 mol/L", "liquid", ["strong_base"], "氢氧化钠水溶液"),
    ("氢氧化钙", "1305-62-0", "Ca(OH)₂", None, "solid", ["strong_base"], "熟石灰"),
    ("高锰酸钾", "7722-64-7", "KMnO₄", None, "solid", ["oxidizer", "heavy_metal"], "强氧化剂"),
    ("重铬酸钾", "7778-50-9", "K₂Cr₂O₇", None, "solid", ["oxidizer", "heavy_metal"], "强氧化剂，六价铬"),
    ("30%过氧化氢", "7722-84-1", "H₂O₂", "30%", "liquid", ["oxidizer", "peroxide"], "强氧化剂，避光冷藏"),
    ("过硫酸铵", "7727-54-0", "(NH₄)₂S₂O₈", None, "solid", ["oxidizer", "peroxide", "ammonium"], "强氧化剂"),
    ("次氯酸钠(84消毒液)", "7681-52-9", "NaClO", "5%", "liquid", ["oxidizer", "hypochlorite"], "含氯消毒剂，禁与酸/氨混合"),
    ("无水乙醇", "64-17-5", "C₂H₅OH", "99.7%", "liquid", ["flammable"], "易燃，远离火源"),
    ("丙酮", "67-64-1", "CH₃COCH₃", None, "liquid", ["flammable"], "极易燃"),
    ("乙醚", "60-29-7", "(C₂H₅)₂O", None, "liquid", ["flammable"], "久置可生成过氧化物"),
    ("亚硝酸钠", "7632-00-0", "NaNO₂", None, "solid", ["reducer", "nitrite"], "剧毒，工业盐误食主因"),
    ("硫化钠", "1313-82-2", "Na₂S", None, "solid", ["reducer", "sulfide"], "遇酸放 H₂S"),
    ("亚硫酸钠", "7757-83-7", "Na₂SO₃", None, "solid", ["reducer", "weak_acid_salt"], "还原剂，遇酸放 SO₂"),
    ("氰化钾", "151-50-8", "KCN", None, "solid", ["cyanide"], "剧毒，严格双人双锁"),
    ("锌粉", "7440-66-6", "Zn", None, "solid", ["reducer", "metal_active"], "活泼金属粉末"),
    ("硝酸钾", "7757-79-1", "KNO₃", None, "solid", ["oxidizer", "nitrate"], "氧化剂，黑火药组分"),
    ("氯化铵", "12125-02-9", "NH₄Cl", None, "solid", ["ammonium", "weak_acid_salt"], "遇碱放氨"),
    ("氨水", "1336-21-6", "NH₃·H₂O", "25%", "liquid", ["ammonium"], "有刺激性氨臭"),
    ("氯化钠", "7647-14-5", "NaCl", None, "solid", ["halide_salt"], "食盐/氯离子来源"),
    ("水合肼", "7803-57-8", "N₂H₄·H₂O", "80%", "liquid", ["reducer", "hydrazine"], "高毒、强还原剂"),
    ("液溴", "7726-95-6", "Br₂", None, "liquid", ["halogen", "oxidizer"], "强腐蚀，蒸气剧毒"),
]

DEMO_PLANS = [
    {
        "name": "示例①氰化物废液酸化处理（错误做法）",
        "description": "试图用盐酸直接酸化含氰废液——规则图将在第 2 步标出剧毒 HCN 风险并中止推演。",
        "steps": [
            ("氰化钾", 0, 0, 10, "取含氰化物废液 100 mL"),
            ("盐酸", 1, 10, 20, "滴加盐酸酸化（危险操作！）"),
            ("无水乙醇", 2, 20, 5, "试图用乙醇洗涤"),
        ],
    },
    {
        "name": "示例②中和含铵盐废水",
        "description": "用 NaOH 处理氯化铵废水：中等放热并有氨气逸出警示；随后加入 84 消毒液将触发氯胺严重禁忌。",
        "steps": [
            ("氯化铵", 0, 0, 50, "含铵盐废水 50 mL"),
            ("氢氧化钠溶液", 1, 10, 50, "加碱中和"),
            ("次氯酸钠(84消毒液)", 2, 20, 20, "试图加含氯消毒剂（危险！）"),
        ],
    },
]


def seed_data(db: Session) -> None:
    """数据库为空时写入种子。"""
    if db.query(models.Reagent).count() == 0:
        name_to_id = {}
        for name, cas, formula, conc, state, cats, note in BUILTIN_REAGENTS:
            reagent = models.Reagent(
                name=name, cas=cas, formula=formula, concentration=conc,
                state=state, categories=json.dumps(cats, ensure_ascii=False),
                note=note, builtin=True,
            )
            db.add(reagent)
            db.flush()
            name_to_id[name] = reagent.id

        if db.query(models.Plan).count() == 0:
            for demo in DEMO_PLANS:
                plan = models.Plan(name=demo["name"], description=demo["description"])
                db.add(plan)
                db.flush()
                for name, order, t, amount, note in demo["steps"]:
                    db.add(
                        models.Step(
                            plan_id=plan.id,
                            order_index=order,
                            time_offset_min=float(t),
                            reagent_id=name_to_id.get(name),
                            reagent_name=name,
                            categories="[]",
                            amount_ml=float(amount),
                            note=note,
                        )
                    )
        db.commit()
