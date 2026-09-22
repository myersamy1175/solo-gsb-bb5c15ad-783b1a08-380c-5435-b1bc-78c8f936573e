# 实验室配液相容性推演台（LabMix Compatibility Console）

录入**试剂属性**与**按时间排列的加液步骤**，系统依据一张**可维护的相容性规则图**逐步推演：
每加入一种试剂，就与当前体系中已有的全部试剂按"类别对"匹配禁忌规则；
首次出现**严重危险反应（起火 / 爆炸 / 剧毒气体）即中止推演**，并标出：

- 🛑 **首次危险反应**发生在第几步、与哪一步加入的哪种试剂冲突；
- ⛔ **受影响步骤**（发生反应的步骤）与**被阻断步骤**（中止后未执行的步骤）；
- 🔎 每条命中都附**可追溯判定依据**：规则编号、反应方程式、机理解释、匹配类别对、
  参与的加液步骤编号、参考文献、规则图版本号。

支持方案保存、历史推演记录、规则图升级后的**版本差异比对**，一键**导出 JSON 结果**，
规则图以 YAML 声明式维护并提供网页可视化。

**步骤安全确认（v1.2 新增）**：每个加液步骤可勾选**护目镜 / 通风 / 手套**等安全措施并填写安全备注；
**保存正式推演（落盘）前必须完成全部步骤确认**，否则接口返回 `409` 并列出待办步骤。
确认与步骤内容指纹绑定——**步骤内容或所引用试剂的名称 / 类别变更后，受影响步骤的确认自动失效**
并标记**待复核**，重新确认后方可正式推演；方案详情、方案列表、推演报告（含历史记录与导出 JSON）
均展示确认状态，**预检（dry-run / persist=false）与导出不设此门槛**。

**规则版本（v1.1 新增）**：同一方案的规则支持**创建版本 → 编辑草稿 → 发布 → 停用**的完整生命周期，
每版保留全部规则的严重级别依据与创建 / 发布 / 停用 / 变更时间；方案详情可查看当前生效状态并
按版本比较差异。**发布后判定接口只读取当前生效版本快照，停用后不再参与判定**（回落全局限定规则图）。
未创建任何版本的方案行为与旧版完全一致。

> ⚠️ 本工具用于教学、方案预检与安全评审辅助，**不能替代**实验室 SOP、MSDS 与专业安全评估。

---

## 一、单条命令启动

需要 Docker 20.10+（带 Compose 插件）。在项目根目录执行：

```bash
docker compose up -d --build
```

启动后访问：

| 入口 | 地址 |
| --- | --- |
| **网页界面** | <http://localhost:8000/> |
| API 文档（Swagger） | <http://localhost:8000/docs> |
| 健康检查 | <http://localhost:8000/api/health> |

端口为 **8000**（宿主机）。如被占用，修改 `docker-compose.yml` 中 `"8000:8000"` 左侧端口即可。

常用命令：

```bash
docker compose logs -f      # 查看日志
docker compose down         # 停止
docker compose down -v      # 停止并删除数据卷（清空所有方案/试剂/记录）
```

数据（SQLite 数据库 `labmix.db`、可现场编辑的 `rules.yaml`）持久化在命名卷 `labmix-data`（容器内 `/data`）。

### 不用 Docker 的本地启动

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# 打开 http://localhost:8000
```

---

## 二、快速上手（3 分钟）

系统首次启动已内置 **24 种常见试剂**、**18 条相容性规则**和 **2 个示例方案**：

1. 打开 **📋 配液方案** 页，左侧是方案编辑器，点击「＋ 添加步骤」按时间排列加液步骤；
   每步可从档案库选择试剂，或直接填写"临时试剂 + 类别"。
2. 每步下方展开 **🛡️ 安全确认**：勾选护目镜 / 手套 / 通风橱等措施、填写安全备注，
   勾选「已确认本步安全措施」；表格下方的进度条实时显示 `已确认 x/y`。
   **修改步骤内容（试剂 / 类别 / 用量等）会使该步确认自动失效并标记"待复核"**。
3. 点击 **▶ 预检（不保存）** 立即推演（预检不要求安全确认）；或 **💾 保存方案** 后点
   **⚡ 保存并推演**——正式推演（落盘）要求全部步骤完成确认，否则提示哪些步骤待确认 / 待复核。
4. 查看报告：
   - 顶部横幅给出**首次危险**与受影响/阻断步骤汇总，并列出各步**安全确认状态**；
   - 左侧**逐步时间轴**展示每一步是"相容 / 警示 / 严重 / 已阻断"，并带 🛡️ 确认标记；
   - 右侧列出全部**命中规则**，点击任意一条查看反应方程式、机理、参考文献与参与步骤。
5. 点击 **导出 JSON** 下载完整推演报告；所有推演自动保存在 **🗂️ 推演记录** 中，可回溯、可再导出。
6. 在 **🗂️ 推演记录** 页顶部选择**同一方案**的两条记录（或先点记录上的「差异」按钮选入），
   点 **🔍 比较版本差异**：系统按步骤编号 + 规则 ID 对齐两次命中，列出新增 / 消失 / 严重级别变化，
   并汇总总体状态、首次危险、受影响 / 阻断步骤的变化；可用顶部筛选按变化类型或关键字过滤，并
   **⬇ 导出差异 JSON**。仅允许比较同一方案，记录缺失或方案不一致会返回明确的 4xx 错误。
7. 打开 **示例①「氰化物废液酸化处理（错误做法）」** 点「编辑」，为各步骤勾选安全措施并确认、
   保存后点「⚡ 保存并推演」，可看到第 2 步盐酸 + 氰化钾命中规则 `R001`（生成剧毒 HCN），
   推演立即中止，第 3 步被阻断。（未完成确认时正式推演会被拦截并提示待确认步骤；
   点「▶ 预检」则不受此限制。）
8. 想体验规则版本：在该方案卡片上点 **📦 规则版本 → ＋ 新建版本草稿**，把 `R001`
   从"严重"改为"警示"后 **🚩 保存并发布**，再次推演：同方案不再中止，报告标注
   `plan1-rv1`；「差异」可对比版本与全局规则图，「停用」即恢复全局判定。

---

## 三、规则图如何维护

系统有两层规则，均在 **🕸️ 规则图** 页维护：

1. **全局限定规则图**（本节）：YAML + 网页自定义规则，是所有"未发布方案规则版本"
   的方案以及预检（dry-run）的判定来源；
2. **方案规则版本**（见下一章）：按方案克隆出来的不可变快照，发布后该方案判定只认它。

规则图 = **类别节点** + **相容性禁忌边**，数据模型刻意保持简单透明：

```
试剂(Reagent) --携带 1..n 个类别标签--> [类别节点] --规则边(severity)--> [类别节点]
```

### 方式 A：改 YAML（推荐用于随版本管理的正式规则）

规则图源文件：[`data/rules.yaml`](data/rules.yaml)

```yaml
- id: R001
  source: cyanide
  target: strong_acid
  directional: false        # 无向边：两个类别谁先加入都会命中
  severity: high            # high=严重(中止) / medium=警示(继续) / low=提示
  title: 酸与氰化物接触生成剧毒氰化氢
  reaction: CN⁻ + H⁺ → HCN↑
  rationale: 酸性条件下氰离子立即质子化……
  references:
    - GB 17914-2013……
```

- 容器环境：编辑命名卷内的 `/data/rules.yaml`（首次启动时从仓库模板自动复制），
  然后 `docker compose restart` 即可生效；
- 本地开发：直接编辑 `data/rules.yaml` 后重启服务。
- 类别中文名在文件顶部 `categories:` 段维护。内置规则只能在网页上**停用 / 调整级别**，
  文案以 YAML 为唯一来源（避免网页改动与版本库漂移）。

### 方式 B：网页追加（适合现场临时规则）

**🕸️ 规则图** 页右侧「追加自定义规则」：填编号（建议 `C` 开头）、类别 A/B、
严重级别、方程式、机理与文献，提交后立即参与推演，可随时删除。

规则图页同时提供**力导向可视化**：节点颜色对应该类别关联规则的最高级别，
边颜色表示严重级别、虚线表示有向规则；点击边查看判定依据，悬停节点高亮其全部关联边。

### 推演规则

- 每个步骤只加入一种试剂，加入前与**体系内已存在**的所有试剂按类别两两匹配；
- `high` 级首次命中 → 该试剂视为未安全加入，记录**首次危险**，后续步骤全部标记为阻断；
- `medium` / `low` 级命中 → 记录 finding，推演继续；
- 无向边双向等价匹配；有向边只按 `source → target` 触发。

---

## 四、方案规则版本（草稿 / 发布 / 停用）

> 场景：不同方案要依据不同时期或不同评审口径的规则集判定（例如某方案经工程防护评审，
> 将特定禁忌从"严重"降为"警示"），同时要求规则变更可评审、可追溯、可回退。

每个方案都有一条独立的规则版本链，与全局限定规则图（YAML + 网页自定义规则）并存：

| 状态 | 含义 | 是否参与判定 |
| --- | --- | --- |
| `draft` 草稿 | 从当前生效版本（首次为全局限定规则图）克隆，可反复编辑规则集合与严重级别依据 | 否（仅可手动预览） |
| `published` 生效中 | 发布后的不可变快照；**每个方案至多一个** | **是，判定接口只读取它** |
| `superseded` 已被替代 | 发布新版本时，原生效版本自动转入此状态 | 否（保留供差异比对与历史追溯） |
| `deactivated` 已停用 | 当前生效版本被人工停用 | 否（方案回落全局限定规则图） |

### 网页操作

- **🕸️ 规则图** 页顶部「📦 方案规则版本」选择方案，或在 **📋 配液方案** 卡片上点「📦 规则版本」；
- 「＋ 新建版本草稿」会克隆**当前生效版本**（首次克隆全局启用规则），也可在 API 指定
  `base_version_id` 从任意历史版本克隆；
- 草稿编辑器可**逐规则调整严重级别**、增删规则、编辑标题 / 方程式 / 机理 / 参考文献（即严重级别依据），
  「▶ 预览判定」用草稿跑一次不落盘的推演，「🚩 保存并发布」使其立即成为当前生效版本；
- 版本列表对每版显示状态、规则数（按严重级别统计）、来源版本、备注以及
  **创建 / 发布 / 停用时间**（编辑草稿会更新"最近变更时间"）；
- 「差异」可在**任意两个版本之间**或**版本 ↔ 全局限定规则图**之间按规则 ID 对齐，
  列出新增 / 删除 / 严重级别变化 / 判定依据变化（含两侧标题、方程式、机理、文献与级别），可导出 JSON；
- 「停用」仅对当前生效版本可用。停用后推演 / 导出立即恢复使用全局限定规则图；
  已发布版本不可删除（保留判定历史），草稿可删除，每个方案至多保留一个草稿。

方案详情 `GET /api/plans/{id}` 的 `effective_rule_version` 字段给出当前生效状态：

```json
{ "id": 5, "version_no": 2, "status": "published", "status_label": "生效中",
  "rule_count": 18, "published_at": "2026-09-21T10:00:00+00:00",
  "updated_at": "2026-09-21T10:00:00+00:00" }
```
为 `null` 时表示该方案没有生效版本，判定使用全局限定规则图。

### 判定口径（强约束）

1. 方案推演 / 导出等正式判定：只读取该方案唯一 `published` 版本快照；
2. 草稿、已替代、已停用版本**都不会**被正式判定读取；
3. 从未发布或停用后：回落全局限定规则图，行为与 v1.0 完全一致；
4. 快照在创建时固化，此后修改 YAML 重启、在网页停用 / 改级全局规则**不影响**已发布版本；
5. 历史推演记录保存所用版本 ID（`runs.rule_version_id`），报告内版本标识形如
   `plan3-rv2`、并带 `rule_scope=plan_version|global`；旧的记录差异比对因此可直接用于
   评估"换规则版本对同一方案的影响"。

### HTTP API（均挂在现有 `/api/plans` 前缀下，无需改变访问方式）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/plans/{id}/rule-versions` | 版本列表 + 当前生效版本 ID + 全局版本号 |
| POST | `/api/plans/{id}/rule-versions` | 创建草稿（克隆生效版本/全局；可带 `base_version_id`、`rules`） |
| GET/PUT/DELETE | `/api/plans/{id}/rule-versions/{vid}` | 版本详情 / 编辑草稿（规则与备注）/ 删除草稿 |
| POST | `/api/plans/{id}/rule-versions/{vid}/publish` | 发布：原生效版本自动转为已替代 |
| POST | `/api/plans/{id}/rule-versions/{vid}/deactivate` | 停用当前生效版本 |
| GET | `/api/plans/{id}/rule-versions/diff?base=&target=` | 版本差异；`global` = 全局限定规则图，target 缺省 = global |

`POST /api/plans/{id}/simulate?persist=false&rule_version_id={vid}` 可用任意版本（含草稿）预览；
`persist=true` 的正式判定固定使用当前生效版本，不接受该参数（返回 `422`）。

**4xx 约定**：方案 / 版本不存在或跨方案访问 → `404`；重复草稿、编辑 / 发布 / 停用 / 删除
状态不允许、规则集合业务校验失败（空集合、编号重复、类别相同）→ `409`；
枚举值非法（严重级别不在 low/medium/high）由请求模型拦截 → `422`；
比较同一版本 → `400`；正式判定携带版本参数 → `422`。

---

## 五、步骤安全确认（正式推演门槛）

> 场景：正式推演（保存记录）前，要求操作者逐步确认个人防护与工程控制措施已落实；
> 步骤或试剂一旦变更，原确认必须作废并重新复核，防止"确认过但内容已改"的误用。

### 数据模型与界面

每个加液步骤携带一组安全确认数据（网页编辑器中每步下方的 🛡️ 区域）：

| 字段 | 含义 |
| --- | --- |
| `safety_measures` | 已勾选措施（预置：护目镜 `goggles`、防护手套 `gloves`、通风橱 `ventilation`、实验服 `lab_coat`、防护面罩 `face_shield`、紧急喷淋 `emergency_shower`；API 可传入自定义 key） |
| `safety_note` | 安全备注（如"通风橱内操作，废液单独收集"） |
| `safety_confirmed` | 确认标记（有效确认，见下方口径） |
| `safety_stale` | 待复核标记（确认后内容已变更） |
| `safety_confirmed_at` | 确认时间 |

### 确认与内容指纹绑定（自动失效）

确认时系统把确认绑定到**步骤内容指纹**（有效试剂名称 / 类别、用量、时刻、操作备注、
已勾选措施与安全备注；档案试剂按档案实时解析）。此后发生以下任一变化，
确认**自动失效**并标记 **⚠️ 待复核**，无需人工清理：

- 编辑方案时修改了该步骤的试剂、临时试剂类别、用量、时刻或备注；
- 修改了已确认的措施勾选或安全备注；
- **试剂档案的名称 / 相容性类别被修改**（引用该试剂的所有步骤联动失效）。

整体保存方案（`PUT /api/plans/{id}`）时：请求未携带安全数据的步骤，若内容指纹与
变更前某步骤一致，**自动继承**其确认状态；内容变化的步骤确认失效。

### 门槛口径（强约束）

1. `POST /api/plans/{id}/simulate?persist=true`（保存正式推演）：要求全部步骤确认有效，
   否则返回 `409`，错误信息列出未确认 / 待复核步骤（按编辑器行号）；
2. **预检不受限**：`persist=false`、`POST /api/plans/simulate-dry`、`GET /api/plans/{id}/export`
   不检查确认状态，但报告中同样携带 `safety` 字段展示确认情况；
3. 细粒度确认接口 `PUT /api/plans/{plan_id}/steps/{step_id}/safety`：
   请求体 `{ "safety_measures": [...], "safety_note": "...", "confirmed": true }`，
   返回该步骤最新确认状态与方案级摘要；跨方案或不存在的步骤返回 `404`；
4. 方案详情 / 列表的 `safety_summary` 字段给出确认进度：
   `{ "total_steps": 3, "confirmed_steps": 2, "stale_steps": 1, "pending_steps": 1,
      "all_confirmed": false, "steps": [ { "order_index": 0, "reagent_name": "…",
      "confirmed": true, "stale": false, "measures": ["goggles"], "note": "…",
      "confirmed_at": "…" } ] }`。

### HTTP API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| PUT | `/api/plans/{id}/steps/{sid}/safety` | 设置单步安全确认（措施 / 备注 / 确认或取消） |
| — | `POST/PUT /api/plans[/{id}]` | 步骤可随方案整体提交 `safety_*` 字段 |
| — | `GET /api/plans[/{id}]` | 返回逐步确认状态与 `safety_summary` 摘要 |

---

## 六、导出的 JSON 结果结构

`GET /api/plans/{id}/export`（实时推演）或 `GET /api/runs/{id}/export`（历史记录）：

```json
{
  "engine": "labmix-compat-engine",
  "engine_version": "1.0",
  "rule_revision": "plan3-rv2",
  "rule_scope": "plan_version",
  "rule_version_id": 5,
  "status": "danger",                    // safe | warning | danger
  "halted": true,
  "first_danger": {
    "finding_id": "F001",
    "step": 1,                          // 首次危险发生在第 1 步（0 基）
    "reagent_name": "盐酸",
    "conflicts_with_step": 0,
    "conflicts_with_reagent": "氰化钾",
    "rule_id": "R001",
    "title": "酸与氰化物接触生成剧毒氰化氢",
    "reaction": "CN⁻ + H⁺ → HCN↑（剧毒气体）",
    "rationale": "……",
    "references": ["GB 17914-2013……"]
  },
  "affected_steps": [1],                // 发生反应的步骤
  "blocked_steps": [2],                 // 中止后未执行的步骤
  "summary": { "total_steps": 3, "executed_steps": 2, "findings": 1,
               "high": 1, "medium": 0, "low": 0 },
  "timeline": [
    { "order_index": 1, "reagent_name": "盐酸", "state": "danger",
      "state_label": "发生严重反应", "finding_ids": ["F001"],
      "safety_confirmed": true, "safety_stale": false,
      "interactions": [ { "rule_id": "R001", "with_reagent": "氰化钾" } ] }
  ],
  "safety": {
    "total_steps": 3, "confirmed_steps": 3, "stale_steps": 0,
    "pending_steps": 0, "all_confirmed": true,
    "steps": [
      { "order_index": 0, "reagent_name": "氰化钾", "confirmed": true, "stale": false,
        "measures": ["goggles", "gloves"], "note": "通风橱内操作",
        "confirmed_at": "2026-09-21T10:00:00+00:00" }
    ]
  },
  "findings": [
    { "id": "F001", "rule_id": "R001", "severity": "high",
      "incoming_step": 1, "incoming_reagent": "盐酸", "incoming_category": "strong_acid",
      "existing_step": 0, "existing_reagent": "氰化钾", "existing_category": "cyanide",
      "match_direction": "existing->incoming", "rule_directional": false,
      "title": "……", "reaction": "……", "rationale": "……", "references": ["……"] }
  ]
}
```

> `rule_scope=global` 时 `rule_revision` 为 YAML 版本号（如 `2026.09`）、无 `rule_version_id`；
> `rule_scope=plan_version` 时 `rule_revision` 为 `plan{方案ID}-rv{版本号}`，
> `rule_version_id` 为对应版本。报告是自包含快照：版本后续被替代 / 停用 / 删除规则，
> 历史记录与导出文件仍保留当时的判定依据。
>
> `safety` 为步骤安全确认快照（见第五章）：`all_confirmed=false` 表示存在未确认 / 待复核步骤；
> 时间轴每项的 `safety_confirmed` / `safety_stale` 给出该步确认状态。

---

## 七、版本差异视图（规则升级影响评估）

当规则图升级（修改 `rules.yaml` 重启、网页停用/改级、追加自定义规则）后，对**同一方案**重新推演，
即可在「🗂️ 推演记录」中比较新旧两条记录。对齐口径为

```
对齐键 = 加入步骤编号 incoming_step + 规则 ID rule_id
         （同一步多条命中再按冲突步骤 existing_step 与类别对区分）
```

每个对齐位置归类为 `added`（新增命中）/ `removed`（消失命中）/ `severity`（严重级别变化）/
`basis`（级别未变但标题、方程式、机理、文献、类别对、匹配方向等反应依据变化）/ `unchanged`（一致）；
同时汇总：

- **总体状态**：`safe / warning / danger` 及其是否变化；
- **两次规则图版本号**；
- **首次危险**：无 / 新增 / 消除 / 位置或规则变化（含两侧步骤、试剂、规则与方程式摘要）；
- **受影响步骤 / 阻断步骤 / 警示步骤**：编号集合的新增与消失；
- **逐步状态对齐表**与命中计数（总数及 high/medium/low）的增减。

`GET /api/runs/diff?base_id={旧记录}&target_id={新记录}` 返回结构（摘要）：

```json
{
  "kind": "labmix-run-diff",
  "plan_id": 3, "plan_name": "……",
  "base":   { "run_id": 7, "rule_revision": "2026.09", "status": "danger",  "created_at": "……" },
  "target": { "run_id": 9, "rule_revision": "2026.10", "status": "warning", "created_at": "……" },
  "summary": {
    "status":         { "base": "danger", "target": "warning", "changed": true },
    "rule_revision":  { "base": "2026.09", "target": "2026.10", "changed": true },
    "first_danger":   { "change": "removed", "base": { "step": 1, "rule_id": "R001", "…": "…" }, "target": null },
    "affected_steps": { "base": [1,2], "target": [1], "added": [], "removed": [2] },
    "blocked_steps":  { "base": [2], "target": [], "added": [], "removed": [2] },
    "steps":          { "items": [ { "step": 1, "base_state": "danger", "target_state": "warning", "change": "changed" } ] },
    "counts":         [ { "key": "high", "label": "严重命中", "base": 1, "target": 0, "delta": -1 } ],
    "finding_changes": { "added": 0, "removed": 0, "severity": 1, "basis": 0, "unchanged": 0 }
  },
  "findings": [
    { "change": "severity", "rule_id": "R001", "incoming_step": 1, "existing_step": 0,
      "base_severity": "high", "target_severity": "medium",
      "basis_changed": false, "changed_fields": [],
      "base":   { "rule_id": "R001", "severity": "high", "title": "…", "reaction": "…",
                  "rationale": "…", "references": ["…"], "incoming_reagent": "盐酸", "…": "…" },
      "target": { "rule_id": "R001", "severity": "medium", "…": "…" } }
  ]
}
```

`GET /api/runs/diff/export` 以相同结构返回，并附带
`Content-Disposition: attachment; filename="runs-{base}-vs-{target}-diff.json"` 下载头。

> 注意：差异比较只对**同一方案**有意义——方案步骤本身被修改会体现在"逐步状态对齐"表中，
> 但 finding 的对齐仍以步骤编号与规则 ID 为准。记录所属方案被删除（`plan_id` 为空）时拒绝比较。

---

## 八、HTTP API 速览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/reagents?q=` | 试剂列表（可按名称/CAS/分子式搜索） |
| POST/PUT/DELETE | `/api/reagents[/{id}]` | 试剂增改删（被步骤引用时拒绝删除） |
| GET/POST | `/api/plans` | 方案列表 / 新建（含步骤，步骤可携带 `safety_*` 确认数据） |
| GET/PUT/DELETE | `/api/plans/{id}` | 方案详情（含 `effective_rule_version` 当前生效版本、`safety_summary` 确认摘要） / 修改 / 删除 |
| PUT | `/api/plans/{id}/steps/{sid}/safety` | **步骤安全确认：勾选措施 / 安全备注 / 确认或取消确认** |
| POST | `/api/plans/{id}/simulate?persist=true` | 按当前生效规则版本推演（无版本则全局图）并可选保存记录；**persist=true 要求全部步骤已确认，否则 409** |
| GET/POST/PUT/DELETE | `/api/plans/{id}/rule-versions[/{vid}[/publish\|/deactivate]]` | **规则版本：创建 / 编辑草稿 / 发布 / 停用 / 删除** |
| GET | `/api/plans/{id}/rule-versions/diff?base=&target=` | **规则版本差异（支持 `global`）** |
| POST | `/api/plans/simulate-dry` | 不保存方案，直接预检（使用全局图） |
| GET | `/api/plans/{id}/export` | 实时推演并下载 JSON |
| GET | `/api/rules[?active_only=true]` | 规则边 + 类别元信息 + 版本号 |
| POST | `/api/rules` | 追加自定义规则 |
| PATCH/DELETE | `/api/rules/{id}` | 启停 / 改级别（自定义规则可删） |
| GET | `/api/runs[/{id}[/export]]` | 历史推演记录、详情、导出 |
| GET | `/api/runs/diff?base_id=&target_id=` | 同一方案两条记录的**版本差异** |
| GET | `/api/runs/diff/export?base_id=&target_id=` | 下载版本差异 JSON |

**版本差异接口的 4xx 约定**：缺少参数 → `422`；两条记录 ID 相同 → `400`；
任一记录不存在 → `404`（错误信息标明是基准还是对照记录）；
两条记录不属于同一方案（含方案已删除、记录未关联方案）→ `409`。

**安全确认接口的 4xx 约定**：方案 / 步骤不存在或步骤不属于该方案 → `404`；
`persist=true` 正式推演存在未确认 / 待复核步骤 → `409`（错误信息列出待办步骤）；
措施超过 16 项等请求校验失败 → `422`。

完整交互模型见 <http://localhost:8000/docs>。

---

## 九、目录结构

```
.
├── app/
│   ├── main.py            # FastAPI 入口：建库、同步规则图、挂载网页
│   ├── config.py           # 路径 / DB 配置（环境变量可覆盖）
│   ├── database.py         # SQLite 引擎与会话
│   ├── models.py           # ORM：试剂 / 方案 / 步骤 / 规则 / 推演记录
│   ├── schemas.py          # Pydantic 请求响应模型
│   ├── rules_store.py      # 读取并同步 YAML 规则图（全局限定规则图）
│   ├── versioning.py       # 方案规则版本：快照、草稿/发布/停用状态机、版本差异
│   ├── safety.py           # 步骤安全确认：内容指纹绑定、自动失效、正式推演门槛
│   ├── engine.py           # 相容性逐步推演引擎（核心算法）
│   ├── deduce.py           # 方案 → 规则版本解析 → 引擎输入 → 报告 → 落盘
│   ├── diffing.py          # 两条历史记录的版本差异对齐与汇总
│   ├── seed.py             # 内置试剂与示例方案
│   └── routers/            # reagents / plans / rule_versions / rules / runs 路由
├── data/
│   └── rules.yaml          # 声明式规则图（类别 + 规则边）
├── web/                    # 原生 HTML/CSS/JS 界面（无构建步骤）
│   ├── index.html
│   ├── style.css
│   └── app.js              # 含力导向规则图可视化
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 十、配置项

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `APP_DATA_DIR` | `./data`（本地）/ `/data`（容器） | SQLite 与现场 `rules.yaml` 所在目录 |
| `DATABASE_URL` | `sqlite:///<APP_DATA_DIR>/labmix.db` | 数据库连接串 |

---

### 安全与合规说明

内置规则参考了 GB 15603《危险化学品仓库储存通则》、GB 30000《化学品分类和标签规范》系列、
《Prudent Practices in the Laboratory》(NRC) 及无机化学通用结论，仅覆盖教学实验中最常见的
配伍禁忌，**不保证完备**；新增试剂或特殊工艺请结合 MSDS、院校/单位安全规程并咨询安全管理员。
