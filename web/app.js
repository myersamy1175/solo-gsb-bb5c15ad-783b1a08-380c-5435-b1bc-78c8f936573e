/* 实验室配液相容性推演台 —— 前端逻辑（原生 JS，无构建依赖） */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  reagents: [],
  plans: [],
  rules: [],
  categories: {},
  revision: "",
  stepRows: [],          // 方案编辑器中的步骤行
  editingStepReagents: [],
  customCats: new Set(),
  report: null,
  runs: [],
  diff: null,
  ruleVersions: [],      // 当前选中方案的规则版本列表
  rvPlanId: null,        // 规则版本模块当前选中的方案 ID
};

/* ---------------- API ---------------- */

async function api(path, options = {}) {
  const opts = { headers: { "Content-Type": "application/json" }, ...options };
  if (opts.body && typeof opts.body !== "string") opts.body = JSON.stringify(opts.body);
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || `请求失败 (${res.status})`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

function toast(msg, isErr = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isErr ? " err" : "");
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2800);
}

function downloadJson(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---------------- Tabs ---------------- */

$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${btn.dataset.tab}`));
    if (btn.dataset.tab === "rules") {
      refreshRvPlanSelect();
      setTimeout(renderGraph, 60);
    }
    if (btn.dataset.tab === "runs") loadRuns();
  });
});

/* ---------------- 数据加载 ---------------- */

async function loadReagents() {
  state.reagents = await api("/api/reagents");
  renderReagentList();
  renderCategoryChips();
  renderStepRows();
}

async function loadPlans() {
  state.plans = await api("/api/plans");
  renderPlanList();
  refreshRvPlanSelect();
}

async function loadRules() {
  const data = await api("/api/rules");
  state.rules = data.rules;
  state.categories = data.categories;
  state.revision = data.revision;
  $("#ruleRev").textContent = `规则图版本 ${data.revision} · ${data.rules.length} 条规则 · ${Object.keys(data.categories).length} 个类别`;
  renderRuleList();
  renderCategoryChips();
  renderGraph();
}

const catLabel = (key) => state.categories[key]?.label || key;
const sevRank = { low: 1, medium: 2, high: 3 };
const sevLabel = { low: "提示", medium: "警示", high: "严重" };

/* ---------------- 方案编辑 ---------------- */

// 步骤安全确认：预置措施（与后端 safety.MEASURE_PRESETS 对应，允许自定义 key 由 API 传入）
const SAFETY_MEASURES = [
  { key: "goggles", label: "🥽 护目镜" },
  { key: "gloves", label: "🧤 防护手套" },
  { key: "ventilation", label: "🌬️ 通风橱/通风" },
  { key: "lab_coat", label: "🥼 实验服" },
  { key: "face_shield", label: "😷 防护面罩" },
  { key: "emergency_shower", label: "🚿 紧急喷淋就绪" },
];
const measureLabel = (key) => SAFETY_MEASURES.find((m) => m.key === key)?.label || key;

function makeStepRow(partial = {}) {
  return {
    order_index: partial.order_index ?? state.stepRows.length,
    time_offset_min: partial.time_offset_min ?? null,
    amount_ml: partial.amount_ml ?? null,
    reagent_id: partial.reagent_id ?? null,
    reagent_name: partial.reagent_name ?? "",
    categories: partial.categories ?? [],
    note: partial.note ?? "",
    // 安全确认状态（随方案保存一并提交）
    safety_measures: partial.safety_measures ?? [],
    safety_note: partial.safety_note ?? "",
    safety_confirmed: partial.safety_confirmed ?? false,
    safety_stale: partial.safety_stale ?? false,
  };
}

// 步骤内容或已确认措施变更后：确认立即失效并标记待复核（与后端指纹口径一致）
function invalidateRowSafety(row) {
  if (row.safety_confirmed) {
    row.safety_confirmed = false;
    row.safety_stale = true;
  }
}

function safetyBadgeHtml(row) {
  if (row.safety_confirmed) return '<span class="badge badge-ok">✅ 已确认</span>';
  if (row.safety_stale) return '<span class="badge badge-medium">⚠️ 待复核（内容已变更）</span>';
  return '<span class="badge badge-blocked">⬜ 未确认</span>';
}

function renderSafetyRow(row, idx) {
  const tr = document.createElement("tr");
  tr.className = "safety-row";
  tr.dataset.idx = idx;
  const td = document.createElement("td");
  td.colSpan = 6;
  td.innerHTML = `
    <div class="safety-box">
      <div class="safety-head">
        <span class="safety-title">🛡️ 安全确认</span>
        <span class="safety-badge">${safetyBadgeHtml(row)}</span>
        <label class="switch safety-confirm-label" title="确认本步安全措施已落实">
          <input type="checkbox" class="safety-confirm" ${row.safety_confirmed ? "checked" : ""} />
          已确认本步安全措施
        </label>
      </div>
      <div class="safety-measures">
        ${SAFETY_MEASURES.map((m) => `
          <span class="chip safety-chip${row.safety_measures.includes(m.key) ? " on" : ""}" data-key="${m.key}">${m.label}</span>`).join("")}
      </div>
      <input type="text" class="safety-note" maxlength="500" placeholder="安全备注（如：通风橱内操作，废液单独收集）" value="${escapeHtml(row.safety_note)}" />
    </div>`;
  tr.appendChild(td);

  $$(".safety-chip", td).forEach((chip) => {
    chip.addEventListener("click", () => {
      const key = chip.dataset.key;
      const i = row.safety_measures.indexOf(key);
      if (i >= 0) row.safety_measures.splice(i, 1);
      else row.safety_measures.push(key);
      chip.classList.toggle("on");
      invalidateRowSafety(row);
      refreshSafetyBadge(tr, row);
      renderSafetyProgress();
    });
  });
  $(".safety-note", td).addEventListener("input", (e) => {
    row.safety_note = e.target.value;
    invalidateRowSafety(row);
    refreshSafetyBadge(tr, row);
    renderSafetyProgress();
  });
  $(".safety-confirm", td).addEventListener("change", (e) => {
    row.safety_confirmed = e.target.checked;
    if (row.safety_confirmed) row.safety_stale = false;
    refreshSafetyBadge(tr, row);
    renderSafetyProgress();
  });
  return tr;
}

// 内容输入变更后只刷新徽章与勾选框，避免重绘整行导致输入框失焦
function refreshSafetyBadge(tr, row) {
  const badge = $(".safety-badge", tr);
  if (badge) badge.innerHTML = safetyBadgeHtml(row);
  const confirmBox = $(".safety-confirm", tr);
  if (confirmBox) confirmBox.checked = row.safety_confirmed;
}

function renderSafetyProgress() {
  const box = $("#safetyProgress");
  if (!box) return;
  const rows = state.stepRows;
  const total = rows.length;
  const confirmed = rows.filter((r) => r.safety_confirmed).length;
  const stale = rows.filter((r) => !r.safety_confirmed && r.safety_stale).length;
  if (!total) { box.innerHTML = ""; return; }
  const all = confirmed === total;
  box.className = "safety-progress " + (all ? "ok" : "pending");
  box.innerHTML = all
    ? `🛡️ 安全确认 <b>${confirmed}/${total}</b> 步已完成 —— 可以保存正式推演`
    : `🛡️ 安全确认 <b>${confirmed}/${total}</b> 步已确认` +
      (stale ? ` · <span class="badge badge-medium">⚠️ ${stale} 步待复核</span>` : "") +
      ` · <span class="hint-inline">保存正式推演前须完成全部步骤确认（预检不受限）</span>`;
}

function renderStepRows() {
  const body = $("#stepsBody");
  body.innerHTML = "";
  state.stepRows.forEach((row, idx) => {
    const tr = document.createElement("tr");

    const tdIdx = document.createElement("td");
    tdIdx.className = "step-idx";
    tdIdx.textContent = idx + 1;
    tr.appendChild(tdIdx);

    // 试剂：下拉选择档案 + “使用临时试剂”切换
    const tdReg = document.createElement("td");
    const select = document.createElement("select");
    select.innerHTML =
      '<option value="">— 临时试剂（手动填写）—</option>' +
      state.reagents
        .map((r) => `<option value="${r.id}" ${row.reagent_id === r.id ? "selected" : ""}>${escapeHtml(r.name)}</option>`)
        .join("");
    select.addEventListener("change", () => {
      if (select.value) {
        row.reagent_id = Number(select.value);
        const r = state.reagents.find((x) => x.id === row.reagent_id);
        row.reagent_name = r ? r.name : "";
      } else {
        row.reagent_id = null;
      }
      invalidateRowSafety(row);
      renderStepRows();
    });
    tdReg.appendChild(select);

    if (row.reagent_id === null) {
      const tmp = document.createElement("input");
      tmp.type = "text";
      tmp.placeholder = "临时试剂名（如：新配制的王水）";
      tmp.value = row.reagent_name;
      tmp.style.marginTop = "5px";
      tmp.addEventListener("input", () => {
        row.reagent_name = tmp.value;
        invalidateRowSafety(row);
        refreshSafetyBadge(body.querySelector(`tr.safety-row[data-idx="${idx}"]`), row);
        renderSafetyProgress();
      });
      tdReg.appendChild(tmp);

      const catInput = document.createElement("input");
      catInput.type = "text";
      catInput.placeholder = "类别，逗号分隔（如 strong_acid, oxidizer）";
      catInput.value = row.categories.join(", ");
      catInput.style.marginTop = "5px";
      catInput.addEventListener("input", () => {
        row.categories = catInput.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
        invalidateRowSafety(row);
        refreshSafetyBadge(body.querySelector(`tr.safety-row[data-idx="${idx}"]`), row);
        renderSafetyProgress();
      });
      tdReg.appendChild(catInput);
    } else {
      const r = state.reagents.find((x) => x.id === row.reagent_id);
      if (r && r.categories.length) {
        const tags = document.createElement("div");
        tags.style.marginTop = "4px";
        tags.innerHTML = r.categories
          .map((c) => `<span class="badge badge-low">${escapeHtml(catLabel(c))}</span>`)
          .join(" ");
        tdReg.appendChild(tags);
      }
    }
    tr.appendChild(tdReg);

    // 时刻
    const tdTime = document.createElement("td");
    const inTime = document.createElement("input");
    inTime.type = "number"; inTime.min = "0"; inTime.step = "1";
    inTime.value = row.time_offset_min ?? "";
    inTime.addEventListener("input", () => {
      row.time_offset_min = inTime.value === "" ? null : Number(inTime.value);
      invalidateRowSafety(row);
      refreshSafetyBadge(body.querySelector(`tr.safety-row[data-idx="${idx}"]`), row);
      renderSafetyProgress();
    });
    tdTime.appendChild(inTime);
    tr.appendChild(tdTime);

    // 用量
    const tdAmt = document.createElement("td");
    const inAmt = document.createElement("input");
    inAmt.type = "number"; inAmt.min = "0"; inAmt.step = "0.1";
    inAmt.value = row.amount_ml ?? "";
    inAmt.addEventListener("input", () => {
      row.amount_ml = inAmt.value === "" ? null : Number(inAmt.value);
      invalidateRowSafety(row);
      refreshSafetyBadge(body.querySelector(`tr.safety-row[data-idx="${idx}"]`), row);
      renderSafetyProgress();
    });
    tdAmt.appendChild(inAmt);
    tr.appendChild(tdAmt);

    // 备注
    const tdNote = document.createElement("td");
    const inNote = document.createElement("input");
    inNote.type = "text"; inNote.value = row.note || "";
    inNote.placeholder = "操作方式/注意";
    inNote.addEventListener("input", () => {
      row.note = inNote.value;
      invalidateRowSafety(row);
      refreshSafetyBadge(body.querySelector(`tr.safety-row[data-idx="${idx}"]`), row);
      renderSafetyProgress();
    });
    tdNote.appendChild(inNote);
    tr.appendChild(tdNote);

    // 删除
    const tdDel = document.createElement("td");
    const del = document.createElement("button");
    del.type = "button"; del.className = "icon-btn"; del.textContent = "✕";
    del.title = "删除此步骤";
    del.addEventListener("click", () => {
      state.stepRows.splice(idx, 1);
      renderStepRows();
    });
    tdDel.appendChild(del);
    tr.appendChild(tdDel);

    body.appendChild(tr);
    body.appendChild(renderSafetyRow(row, idx));
  });
  renderSafetyProgress();
}

function collectPlanPayload() {
  const name = $("#planName").value.trim();
  if (!name) throw new Error("请填写方案名称");
  if (!state.stepRows.length) throw new Error("请至少添加一个加液步骤");
  state.stepRows.forEach((r, i) => {
    if (r.reagent_id === null && !r.reagent_name.trim()) {
      throw new Error(`第 ${i + 1} 步需要选择试剂或填写临时试剂名`);
    }
  });
  return {
    name,
    description: $("#planDesc").value.trim() || null,
    steps: state.stepRows.map((r, i) => ({
      order_index: i,
      time_offset_min: r.time_offset_min,
      amount_ml: r.amount_ml,
      reagent_id: r.reagent_id,
      reagent_name: r.reagent_id ? null : r.reagent_name.trim(),
      categories: r.reagent_id ? null : r.categories,
      note: r.note || null,
      safety_measures: r.safety_measures,
      safety_note: r.safety_note.trim() || null,
      safety_confirmed: r.safety_confirmed,
      safety_stale: r.safety_stale,
    })),
  };
}

$("#btnAddStep").addEventListener("click", () => {
  state.stepRows.push(makeStepRow());
  renderStepRows();
});

$("#btnPlanReset").addEventListener("click", resetPlanForm);

function resetPlanForm() {
  $("#planForm").reset();
  $("#planId").value = "";
  $("#planFormTitle").textContent = "新建配液方案";
  $("#btnSavePlan").textContent = "💾 保存方案";
  $("#btnSimulateSaved").classList.add("hidden");
  $("#reportWrap").classList.add("hidden");
  state.report = null;
  state.stepRows = [makeStepRow()];
  renderStepRows();
}

$("#planForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const payload = collectPlanPayload();
    const id = $("#planId").value;
    if (id) {
      await api(`/api/plans/${id}`, { method: "PUT", body: payload });
      toast("方案已更新");
    } else {
      const created = await api("/api/plans", { method: "POST", body: payload });
      $("#planId").value = created.id;
      $("#planFormTitle").textContent = "编辑配液方案";
      $("#btnSavePlan").textContent = "💾 保存修改";
      $("#btnSimulateSaved").classList.remove("hidden");
      toast("方案已保存");
    }
    await loadPlans();
  } catch (err) {
    toast(err.message, true);
  }
});

$("#btnDryRun").addEventListener("click", async () => {
  try {
    const payload = collectPlanPayload();
    const report = await api("/api/plans/simulate-dry", { method: "POST", body: payload });
    state.report = report;
    renderReport(report, { editable: true });
    toast(report.status === "danger" ? "预检发现严重危险！" : report.status === "warning" ? "预检完成：存在警示" : "预检通过：相容");
  } catch (err) {
    toast(err.message, true);
  }
});

$("#btnSimulateSaved").addEventListener("click", async () => {
  const id = $("#planId").value;
  if (!id) return;
  try {
    // 先保存当前表单（含各步安全确认），再按已保存内容做正式推演
    const payload = collectPlanPayload();
    await api(`/api/plans/${id}`, { method: "PUT", body: payload });
    await loadPlans();
    const report = await api(`/api/plans/${id}/simulate?persist=true`, { method: "POST" });
    state.report = report;
    renderReport(report, { editable: true });
    loadRuns();
    toast("推演完成并已记录");
  } catch (err) {
    toast(err.message, true);
  }
});

function editPlan(plan) {
  resetPlanForm();
  $("#planId").value = plan.id;
  $("#planName").value = plan.name;
  $("#planDesc").value = plan.description || "";
  $("#planFormTitle").textContent = "编辑配液方案";
  $("#btnSavePlan").textContent = "💾 保存修改";
  $("#btnSimulateSaved").classList.remove("hidden");
  state.stepRows = plan.steps.map((s) => makeStepRow({
    order_index: s.order_index,
    time_offset_min: s.time_offset_min,
    amount_ml: s.amount_ml,
    reagent_id: s.reagent_id,
    reagent_name: s.reagent_name,
    categories: s.categories,
    note: s.note,
    safety_measures: s.safety_measures || [],
    safety_note: s.safety_note || "",
    safety_confirmed: s.safety_confirmed || false,
    safety_stale: s.safety_stale || false,
  }));
  renderStepRows();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function simulatePlan(plan) {
  editPlan(plan);
  const report = await api(`/api/plans/${plan.id}/simulate?persist=true`, { method: "POST" });
  state.report = report;
  renderReport(report, { editable: true });
  loadRuns();
}

function renderPlanList() {
  const q = ($("#planSearch").value || "").toLowerCase();
  const ul = $("#planList");
  ul.innerHTML = "";
  state.plans
    .filter((p) => !q || p.name.toLowerCase().includes(q))
    .forEach((p) => {
      const li = document.createElement("li");
      li.className = "item";
      const ev = p.effective_rule_version;
      const effLine = ev
        ? `<span class="badge badge-ok">规则 v${ev.version_no} 生效中</span>`
        : '<span class="badge badge-blocked">全局规则图</span>';
      const sf = p.safety_summary;
      const sfLine = !sf || !sf.total_steps
        ? ""
        : sf.all_confirmed
          ? `<span class="badge badge-ok">🛡️ 确认 ${sf.confirmed_steps}/${sf.total_steps}</span>`
          : `<span class="badge badge-medium" title="正式推演前须完成全部步骤安全确认">🛡️ 确认 ${sf.confirmed_steps}/${sf.total_steps}${sf.stale_steps ? ` · ${sf.stale_steps} 待复核` : ""}</span>`;
      li.innerHTML = `
        <div class="item-title">${escapeHtml(p.name)} ${effLine}</div>
        <div class="item-meta"><span>🕐 ${p.steps.length} 步</span>${sfLine}<span>更新于 ${fmtTime(p.updated_at)}</span></div>
        ${p.description ? `<div class="item-meta">${escapeHtml(p.description)}</div>` : ""}
      `;
      const actions = document.createElement("div");
      actions.className = "item-actions";
      actions.append(
        actionBtn("编辑", "btn-small", () => editPlan(p)),
        actionBtn("⚡ 推演", "btn-small btn-primary", () => simulatePlan(p).catch((e) => toast(e.message, true))),
        actionBtn("📦 规则版本", "btn-small", () => openPlanVersions(p)),
        actionBtn("导出 JSON", "btn-small", () => exportPlan(p.id)),
        actionBtn("删除", "btn-small btn-danger", () => removePlan(p)),
      );
      li.appendChild(actions);
      ul.appendChild(li);
    });
}

$("#planSearch").addEventListener("input", renderPlanList);

async function exportPlan(id) {
  const data = await api(`/api/plans/${id}/export`);
  downloadJson(data, `plan-${id}-report.json`);
  toast("已导出推演结果 JSON");
}

async function removePlan(plan) {
  if (!confirm(`确定删除方案「${plan.name}」？此操作不可撤销。`)) return;
  await api(`/api/plans/${plan.id}`, { method: "DELETE" });
  if (String($("#planId").value) === String(plan.id)) resetPlanForm();
  await loadPlans();
  toast("方案已删除");
}

function actionBtn(text, cls, fn) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = `btn ${cls}`;
  b.textContent = text;
  b.addEventListener("click", (e) => { e.stopPropagation(); fn(); });
  return b;
}

function openPlanVersions(plan) {
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === "rules"));
  $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === "tab-rules"));
  refreshRvPlanSelect(plan.id);
  state.rvPlanId = plan.id;
  $("#rvPlanSelect").value = String(plan.id);
  renderRvEffective();
  openRvManager();
}

/* ---------------- 报告渲染 ---------------- */

// 报告横幅中的步骤安全确认摘要行（预检 / 正式推演 / 历史记录统一展示）
function renderSafetySummaryLine(report) {
  const sf = report.safety;
  if (!sf || !sf.total_steps) return "";
  const stateBadge = sf.all_confirmed
    ? '<span class="badge badge-ok">全部已确认</span>'
    : `<span class="badge badge-medium">存在未确认步骤</span>`;
  const stale = sf.stale_steps ? ` · <span class="badge badge-medium">⚠️ 待复核 ${sf.stale_steps} 步</span>` : "";
  const details = (sf.steps || [])
    .map((s) => {
      const mark = s.confirmed ? "✅" : s.stale ? "⚠️" : "⬜";
      const measures = (s.measures || []).map((m) => escapeHtml(measureLabel(m))).join("、");
      const tip = `${s.reagent_name}${measures ? "：" + measures : ""}${s.note ? "（" + s.note + "）" : ""}`;
      return `<span class="safety-step-mark" title="${escapeHtml(tip)}">${mark} 第 ${s.order_index} 步</span>`;
    })
    .join(" ");
  return `<p class="item-meta">🛡️ 步骤安全确认 <b>${sf.confirmed_steps}/${sf.total_steps}</b> ${stateBadge}${stale}<br>${details}</p>`;
}

function renderReport(report, { editable = false, hideExport = false, container = $("#reportWrap") } = {}) {
  const editable2 = { editable, hideExport };
  window.__lastReport = report;
  const wrap = container;
  wrap.classList.remove("hidden");

  const first = report.first_danger;
  const bannerCls = report.status === "danger" ? "danger" : report.status === "warning" ? "warning" : "safe";
  const icon = report.status === "danger" ? "🛑" : report.status === "warning" ? "⚠️" : "✅";
  const title =
    report.status === "danger"
      ? `推演中止：第 ${first.step} 步首次发生严重危险反应`
      : report.status === "warning" ? "推演完成：存在需要关注的警示反应" : "推演完成：各步骤相容";

  let bannerMsg = "";
  if (first) {
    bannerMsg = `
      <p><b>${escapeHtml(first.reagent_name)}</b>（第 ${first.step} 步）与第 ${first.conflicts_with_step} 步加入的
      <b>${escapeHtml(first.conflicts_with_reagent)}</b> 冲突：${escapeHtml(first.title)}</p>
      <p>受影响步骤：${report.affected_steps.length ? report.affected_steps.map((s) => `第 ${s} 步`).join("、") : "无"}；
      阻断步骤：${report.blocked_steps.length ? report.blocked_steps.map((s) => `第 ${s} 步`).join("、") : "无"}</p>`;
  }

  wrap.innerHTML = `
    <div class="report-banner ${bannerCls}">
      <span class="big">${icon}</span>
      <div style="flex:1">
        <h2>${title}</h2>
        ${bannerMsg}
        <p class="item-meta">${report.rule_scope === "plan_version"
          ? `方案规则版本 <b>${escapeHtml(report.rule_revision)}</b>`
          : `全局限定规则图 ${escapeHtml(report.rule_revision)}`} ·
          共 ${report.summary.total_steps} 步 / 执行 ${report.summary.executed_steps} 步 ·
          命中规则 <span class="badge badge-high">严重 ${report.summary.high}</span>
          <span class="badge badge-medium">警示 ${report.summary.medium}</span>
          <span class="badge badge-low">提示 ${report.summary.low}</span>
        </p>
        ${renderSafetySummaryLine(report)}
      </div>
      <div class="form-actions" style="flex-direction:column">
        ${report.plan_id && !editable2.hideExport ? `<button class="btn btn-small" id="btnExportShow">⬇ 导出 JSON</button>` : ""}
      </div>
    </div>
    <div class="report-grid">
      <div class="card"><h2 style="margin-bottom:12px">⏱️ 逐步推演时间轴</h2><ul class="timeline">${
        report.timeline.map(renderTimelineItem).join("")
      }</ul></div>
      <div class="card"><h2 style="margin-bottom:12px">🔎 命中规则与判定依据（${report.findings.length}）</h2>
        <div class="finding-list">${
          report.findings.length
            ? report.findings.map(renderFindingCard).join("")
            : '<p class="hint">未命中任何相容性禁忌。</p>'
        }</div>
      </div>
    </div>`;

  const btnExport = $("#btnExportShow", wrap);
  if (btnExport) btnExport.addEventListener("click", () => exportPlan(report.plan_id));

  $$(".mini-rule, .finding-card", wrap).forEach((el) => {
    el.addEventListener("click", () => {
      const f = report.findings.find((x) => x.id === el.dataset.fid);
      if (f) openFindingModal(f, report.rule_revision);
    });
  });

  wrap.scrollIntoView?.({ behavior: "smooth", block: "start" });
}

function renderTimelineItem(t) {
  const findings = t.finding_ids
    .map((fid) => window.__lastReport?.findings?.find((x) => x.id === fid))
    .filter(Boolean);
  const safetyBadge = t.safety_confirmed
    ? '<span class="badge badge-ok" title="本步安全措施已确认">🛡️ 已确认</span>'
    : t.safety_stale
      ? '<span class="badge badge-medium" title="内容变更后尚未重新确认">🛡️ 待复核</span>'
      : '<span class="badge badge-blocked" title="尚未完成安全确认">🛡️ 未确认</span>';
  return `
    <li class="tl-item ${t.state}">
      <span class="tl-dot"></span>
      <div class="tl-body">
        <div class="tl-head">
          <span class="tl-name">第 ${t.order_index} 步 · ${escapeHtml(t.reagent_name)}</span>
          <span class="tl-badges">${safetyBadge}<span class="badge badge-${t.state === "ok" ? "ok" : t.state}">${t.state_label}</span></span>
        </div>
        <div class="tl-note">
          ${t.time_offset_min !== null ? `🕐 t=${t.time_offset_min} min · ` : ""}
          ${t.amount_ml !== null ? `${t.amount_ml} mL/g · ` : ""}
          ${(t.reagent_categories || []).map((c) => escapeHtml(catLabel(c))).join(" / ")}
          ${t.note ? " · " + escapeHtml(t.note) : ""}
        </div>
        <div class="tl-findings">
          ${findings.map((f) => `
            <button type="button" class="mini-rule ${f.severity}" data-fid="${f.id}">
              <b>[${f.rule_id}]</b> ${escapeHtml(f.title)} —— 与第 ${f.existing_step} 步「${escapeHtml(f.existing_reagent)}」
            </button>`).join("")}
        </div>
      </div>
    </li>`;
}

function renderFindingCard(f) {
  return `
    <div class="finding-card ${f.severity}" data-fid="${f.id}">
      <div class="fc-title">
        <span class="badge badge-${f.severity}">${f.severity_label}</span>
        [${f.rule_id}] ${escapeHtml(f.title)}
      </div>
      <div class="fc-meta">
        第 ${f.incoming_step} 步「${escapeHtml(f.incoming_reagent)}」(${escapeHtml(catLabel(f.incoming_category))})
        ⚠ 第 ${f.existing_step} 步「${escapeHtml(f.existing_reagent)}」(${escapeHtml(catLabel(f.existing_category))})
      </div>
      <div class="fc-meta">${escapeHtml(f.reaction)} · 点击查看机理与参考文献</div>
    </div>`;
}

/* ---------------- 弹层 ---------------- */

function openModal(html) {
  $("#modalBox").innerHTML = html;
  $("#modalBackdrop").classList.remove("hidden");
  const closeBtn = $(".modal-close", $("#modalBox"));
  if (closeBtn) closeBtn.addEventListener("click", closeModal);
}
function closeModal() {
  $("#modalBackdrop").classList.add("hidden");
  $("#modalBox").classList.remove("modal-wide");
}
$("#modalBackdrop").addEventListener("click", (e) => { if (e.target === $("#modalBackdrop")) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

function openFindingModal(f, revision) {
  openModal(`
    <button class="btn btn-ghost modal-close">✕ 关闭</button>
    <h3><span class="badge badge-${f.severity}">${f.severity_label}</span> [${f.rule_id}] ${escapeHtml(f.title)}</h3>
    <div class="m-row"><div class="m-k">反应 / 现象</div><div class="m-eq">${escapeHtml(f.reaction)}</div></div>
    <div class="m-row"><div class="m-k">判定依据（机理）</div><div>${escapeHtml(f.rationale).replace(/\n/g, "<br>")}</div></div>
    <div class="m-row"><div class="m-k">参与步骤（可追溯）</div>
      <div>第 ${f.incoming_step} 步加入「${escapeHtml(f.incoming_reagent)}」，类别 <b>${escapeHtml(catLabel(f.incoming_category))}</b><br>
      与体系中第 ${f.existing_step} 步已加入的「${escapeHtml(f.existing_reagent)}」，类别 <b>${escapeHtml(catLabel(f.existing_category))}</b> 发生匹配<br>
      匹配方向：${f.match_direction === "incoming->existing" ? "新加入 → 已存在" : "已存在 → 新加入"}
      ${f.rule_directional ? "（有向规则）" : "（无向规则，双向等价）"}</div>
    </div>
    <div class="m-row"><div class="m-k">参考文献</div>
      <ul class="m-refs">${f.references.map((r) => `<li>· ${escapeHtml(r)}</li>`).join("") || "<li>无</li>"}</ul>
    </div>
    <div class="m-row m-k">规则图版本 ${escapeHtml(revision || state.revision)}</div>
  `);
}

function openRuleModal(rule) {
  openModal(`
    <button class="btn btn-ghost modal-close">✕ 关闭</button>
    <h3><span class="badge badge-${rule.severity}">${sevLabel[rule.severity]}</span> [${rule.id}] ${escapeHtml(rule.title)}</h3>
    <div class="m-row"><div class="m-k">规则边</div>
      <div>${escapeHtml(catLabel(rule.source))} <b>→</b> ${escapeHtml(catLabel(rule.target))}
      ${rule.directional ? "（有向）" : "（无向，双向匹配）"} · ${rule.builtin ? "内置规则" : "自定义规则"} · ${rule.active ? "启用中" : "已停用"}</div>
    </div>
    <div class="m-row"><div class="m-k">反应 / 现象</div><div class="m-eq">${escapeHtml(rule.reaction)}</div></div>
    <div class="m-row"><div class="m-k">判定依据（机理）</div><div>${escapeHtml(rule.rationale).replace(/\n/g, "<br>")}</div></div>
    <div class="m-row"><div class="m-k">参考文献</div>
      <ul class="m-refs">${rule.references.map((r) => `<li>· ${escapeHtml(r)}</li>`).join("") || "<li>无</li>"}</ul>
    </div>
  `);
}

/* ---------------- 试剂档案 ---------------- */

function renderCategoryChips() {
  const box = $("#rgCats");
  if (!box) return;
  const selected = new Set(box.dataset.selected ? box.dataset.selected.split(",") : []);
  box.innerHTML = "";
  Object.entries(state.categories).forEach(([key, meta]) => {
    const chip = document.createElement("span");
    chip.className = "chip" + (selected.has(key) ? " on" : "");
    chip.textContent = meta.label || key;
    chip.title = key;
    chip.addEventListener("click", () => {
      chip.classList.toggle("on");
      syncSelectedCats(box);
    });
    box.appendChild(chip);
  });
  state.customCats.forEach((key) => {
    if (state.categories[key]) return;
    const chip = document.createElement("span");
    chip.className = "chip on";
    chip.textContent = key;
    chip.title = key;
    chip.addEventListener("click", () => { chip.remove(); syncSelectedCats(box); });
    box.appendChild(chip);
  });
}

function syncSelectedCats(box) {
  box.dataset.selected = $$(".chip.on", box).map((c) => c.title || c.textContent).join(",");
}

$("#rgCatsCustom").addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === ",") {
    e.preventDefault();
    const v = e.target.value.trim();
    if (v && !state.customCats.has(v)) {
      state.customCats.add(v);
      renderCategoryChips();
    }
    e.target.value = "";
  }
});

$("#reagentForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  syncSelectedCats($("#rgCats"));
  const selected = $("#rgCats").dataset.selected.split(",").filter(Boolean);
  const payload = {
    name: $("#rgName").value.trim(),
    cas: $("#rgCas").value.trim() || null,
    formula: $("#rgFormula").value.trim() || null,
    concentration: $("#rgConc").value.trim() || null,
    state: $("#rgState").value,
    categories: selected,
    note: $("#rgNote").value.trim() || null,
  };
  try {
    const id = $("#reagentId").value;
    if (id) await api(`/api/reagents/${id}`, { method: "PUT", body: payload });
    else await api("/api/reagents", { method: "POST", body: payload });
    toast("试剂已保存");
    resetReagentForm();
    await loadReagents();
  } catch (err) { toast(err.message, true); }
});

$("#btnReagentReset").addEventListener("click", resetReagentForm);

function resetReagentForm() {
  $("#reagentForm").reset();
  $("#reagentId").value = "";
  $("#reagentFormTitle").textContent = "新建试剂档案";
  state.customCats.clear();
  renderCategoryChips();
}

function editReagent(r) {
  $("#reagentId").value = r.id;
  $("#rgName").value = r.name;
  $("#rgCas").value = r.cas || "";
  $("#rgFormula").value = r.formula || "";
  $("#rgConc").value = r.concentration || "";
  $("#rgState").value = r.state;
  $("#rgNote").value = r.note || "";
  $("#reagentFormTitle").textContent = "编辑试剂档案";
  $("#rgCats").dataset.selected = r.categories.join(",");
  state.customCats = new Set(r.categories.filter((c) => !state.categories[c]));
  renderCategoryChips();
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === "reagents"));
  $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === "tab-reagents"));
  window.scrollTo({ top: 0 });
}

function renderReagentList() {
  const q = ($("#reagentSearch").value || "").toLowerCase();
  const ul = $("#reagentList");
  ul.innerHTML = "";
  state.reagents
    .filter((r) => !q || [r.name, r.cas, r.formula].some((x) => (x || "").toLowerCase().includes(q)))
    .forEach((r) => {
      const li = document.createElement("li");
      li.className = "item";
      li.innerHTML = `
        <div class="item-title">${escapeHtml(r.name)}
          ${r.builtin ? '<span class="badge badge-ok">内置</span>' : ""}
        </div>
        <div class="item-meta">
          ${r.formula ? `分子式 ${escapeHtml(r.formula)} · ` : ""}
          ${r.cas ? `CAS ${escapeHtml(r.cas)} · ` : ""}
          ${r.concentration ? escapeHtml(r.concentration) + " · " : ""}
          ${({ liquid: "液体", solid: "固体", gas: "气体" })[r.state]}
        </div>
        <div class="item-meta">${r.categories.map((c) => `<span class="badge badge-low">${escapeHtml(catLabel(c))}</span>`).join(" ")}</div>
        ${r.note ? `<div class="item-meta">${escapeHtml(r.note)}</div>` : ""}
      `;
      const actions = document.createElement("div");
      actions.className = "item-actions";
      actions.append(
        actionBtn("编辑", "btn-small", () => editReagent(r)),
        actionBtn("删除", "btn-small btn-danger", () => removeReagent(r)),
      );
      li.appendChild(actions);
      ul.appendChild(li);
    });
}

$("#reagentSearch").addEventListener("input", renderReagentList);

async function removeReagent(r) {
  if (!confirm(`确定删除试剂「${r.name}」？`)) return;
  try {
    await api(`/api/reagents/${r.id}`, { method: "DELETE" });
    toast("试剂已删除");
    await loadReagents();
  } catch (err) { toast(err.message, true); }
}

/* ---------------- 规则列表 / 自定义 ---------------- */

function renderRuleList() {
  const showInactive = $("#showInactive").checked;
  const ul = $("#ruleList");
  ul.innerHTML = "";
  state.rules
    .filter((r) => showInactive || r.active)
    .sort((a, b) => sevRank[b.severity] - sevRank[a.severity] || a.id.localeCompare(b.id))
    .forEach((r) => {
      const li = document.createElement("li");
      li.className = "item";
      li.innerHTML = `
        <div class="item-title">
          <span class="badge badge-${r.severity}">${sevLabel[r.severity]}</span>
          [${r.id}] ${escapeHtml(r.title)}
          ${!r.active ? '<span class="badge badge-off">已停用</span>' : ""}
          ${r.directional ? '<span class="badge badge-blocked">有向</span>' : ""}
        </div>
        <div class="item-meta">${escapeHtml(catLabel(r.source))} → ${escapeHtml(catLabel(r.target))}
          · ${r.builtin ? "内置" : "自定义"} · ${escapeHtml(r.reaction)}</div>
      `;
      const actions = document.createElement("div");
      actions.className = "item-actions";
      actions.append(
        actionBtn("依据", "btn-small", () => openRuleModal(r)),
        actionBtn(r.active ? "停用" : "启用", "btn-small", () => toggleRule(r)),
      );
      if (!r.builtin) actions.append(actionBtn("删除", "btn-small btn-danger", () => removeRule(r)));
      li.appendChild(actions);
      ul.appendChild(li);
    });
}

$("#showInactive").addEventListener("change", renderRuleList);

async function toggleRule(r) {
  await api(`/api/rules/${r.id}`, { method: "PATCH", body: { active: !r.active } });
  await loadRules();
  toast(r.active ? `已停用规则 ${r.id}` : `已启用规则 ${r.id}`);
}

async function removeRule(r) {
  if (!confirm(`确定删除自定义规则 ${r.id}？`)) return;
  await api(`/api/rules/${r.id}`, { method: "DELETE" });
  await loadRules();
  toast("规则已删除");
}

$("#ruleForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    id: $("#rlId").value.trim(),
    source: $("#rlSource").value.trim(),
    target: $("#rlTarget").value.trim(),
    directional: $("#rlDirectional").checked,
    severity: $("#rlSeverity").value,
    title: $("#rlTitle").value.trim(),
    reaction: $("#rlReaction").value.trim(),
    rationale: $("#rlRationale").value.trim(),
    references: $("#rlRefs").value.split("\n").map((s) => s.trim()).filter(Boolean),
  };
  try {
    await api("/api/rules", { method: "POST", body: payload });
    e.target.reset();
    toast("自定义规则已加入规则图");
    await loadRules();
  } catch (err) { toast(err.message, true); }
});

/* ---------------- 规则图（力导向 SVG） ---------------- */

const graph = { nodes: {}, edges: [], sim: null };

function renderGraph() {
  const svg = $("#graphSvg");
  if (!svg || !state.rules.length) return;

  const width = svg.clientWidth || 900;
  const height = 560;
  svg.innerHTML = `
    <defs>
      <marker id="arrow" markerWidth="10" markerHeight="10" refX="18" refY="3" orient="auto" markerUnits="strokeWidth">
        <path d="M0,0 L0,6 L9,3 z" fill="#5b6776"></path>
      </marker>
    </defs>
    <g id="viewport"></g>`;
  const vp = $("#viewport", svg);

  // 节点：参与启用规则的类别
  const nodes = new Map();
  state.rules.filter((r) => r.active).forEach((r) => {
    [r.source, r.target].forEach((c) => {
      if (!nodes.has(c)) {
        nodes.set(c, {
          id: c,
          x: width / 2 + (Math.random() - .5) * 300,
          y: height / 2 + (Math.random() - .5) * 300,
          vx: 0, vy: 0,
          worst: "low",
          degree: 0,
        });
      }
    });
    const n = nodes.get(r.source);
    if (sevRank[r.severity] > sevRank[n.worst]) n.worst = r.severity;
    nodes.get(r.target).degree++;
    n.degree++;
  });

  const edges = state.rules
    .filter((r) => r.active && nodes.has(r.source) && nodes.has(r.target))
    .map((r) => ({ source: r.source, target: r.target, rule: r }));

  // 简单力导向：斥力 + 弹簧 + 向心
  const nodeArr = [...nodes.values()];
  for (let iter = 0; iter < 300; iter++) {
    for (let i = 0; i < nodeArr.length; i++) {
      for (let j = i + 1; j < nodeArr.length; j++) {
        const a = nodeArr[i], b = nodeArr[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy || 1;
        const d = Math.sqrt(d2);
        const force = 26000 / d2;
        a.vx += (dx / d) * force; a.vy += (dy / d) * force;
        b.vx -= (dx / d) * force; b.vy -= (dy / d) * force;
      }
    }
    edges.forEach((e) => {
      const a = nodes.get(e.source), b = nodes.get(e.target);
      let dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.hypot(dx, dy) || 1;
      const target = 180;
      const force = (d - target) * 0.02;
      a.vx += (dx / d) * force; a.vy += (dy / d) * force;
      b.vx -= (dx / d) * force; b.vy -= (dy / d) * force;
    });
    nodeArr.forEach((n) => {
      n.vx += (width / 2 - n.x) * 0.004;
      n.vy += (height / 2 - n.y) * 0.004;
      n.vx *= .82; n.vy *= .82;
      n.x += n.vx; n.y += n.vy;
      n.x = Math.max(70, Math.min(width - 70, n.x));
      n.y = Math.max(40, Math.min(height - 40, n.y));
    });
  }

  // 画边
  const edgeLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
  edges.forEach((e) => {
    const a = nodes.get(e.source), b = nodes.get(e.target);
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
    line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
    line.setAttribute("class", `g-edge ${e.rule.severity}${e.rule.directional ? " directional" : ""}`);
    if (e.rule.directional) line.setAttribute("marker-end", "url(#arrow)");
    line.addEventListener("click", (ev) => { ev.stopPropagation(); openRuleModal(e.rule); });
    line.addEventListener("mouseenter", () => highlight(a.id, b.id));
    line.addEventListener("mouseleave", clearHighlight);
    line.dataset.source = e.source; line.dataset.target = e.target;
    edgeLayer.appendChild(line);
  });
  vp.appendChild(edgeLayer);

  // 画节点
  const colorByWorst = { high: "#dc2626", medium: "#d97706", low: "#2563eb" };
  const nodeLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
  nodeArr.forEach((n) => {
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("class", "g-node");
    g.setAttribute("transform", `translate(${n.x},${n.y})`);
    g.dataset.id = n.id;
    const el = document.createElementNS("http://www.w3.org/2000/svg", "ellipse");
    const label = catLabel(n.id);
    const w = Math.max(46, label.length * 13 + 18);
    el.setAttribute("rx", w / 2); el.setAttribute("ry", 17);
    el.setAttribute("stroke", colorByWorst[n.worst]);
    el.setAttribute("stroke-width", Math.min(3.5, 1.2 + n.degree * 0.25));
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("dy", "4");
    text.textContent = label;
    g.append(el, text);
    g.addEventListener("mouseenter", () => highlight(n.id));
    g.addEventListener("mouseleave", clearHighlight);
    g.addEventListener("click", () => {
      const related = state.rules.filter(
        (r) => r.active && (r.source === n.id || r.target === n.id)
      );
      if (related.length === 1) openRuleModal(related[0]);
      else if (related.length > 1) {
        openModal(`
          <button class="btn btn-ghost modal-close">✕ 关闭</button>
          <h3>类别「${escapeHtml(catLabel(n.id))}」关联的 ${related.length} 条规则</h3>
          <div class="finding-list" style="margin-top:12px">
            ${related.map((r) => `
              <div class="finding-card ${r.severity}" data-rid="${r.id}">
                <div class="fc-title"><span class="badge badge-${r.severity}">${sevLabel[r.severity]}</span>
                [${r.id}] ${escapeHtml(r.title)}</div>
                <div class="fc-meta">${escapeHtml(catLabel(r.source))} → ${escapeHtml(catLabel(r.target))}</div>
              </div>`).join("")}
          </div>`);
        $$(".finding-card", $("#modalBox")).forEach((card) => {
          card.addEventListener("click", () => {
            const r = related.find((x) => x.id === card.dataset.rid);
            if (r) openRuleModal(r);
          });
        });
      }
    });
    nodeLayer.appendChild(g);
  });
  vp.appendChild(nodeLayer);

  // 简单平移缩放
  let scale = 1, tx = 0, ty = 0, dragging = false, sx = 0, sy = 0;
  const apply = () => vp.setAttribute("transform", `translate(${tx},${ty}) scale(${scale})`);
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? .9 : 1.1;
    scale = Math.max(.4, Math.min(2.5, scale * delta));
    apply();
  }, { passive: false });
  svg.addEventListener("mousedown", (e) => {
    if (e.target.closest(".g-node")) return;
    dragging = true; sx = e.clientX - tx; sy = e.clientY - ty;
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    tx = e.clientX - sx; ty = e.clientY - sy; apply();
  });
  window.addEventListener("mouseup", () => (dragging = false));

  function highlight(nodeId, otherId) {
    $$(".g-node", svg).forEach((g) => {
      const on = g.dataset.id === nodeId || (otherId && g.dataset.id === otherId);
      g.classList.toggle("dim", !on);
    });
    $$(".g-edge", svg).forEach((l) => {
      const on = (l.dataset.source === nodeId || l.dataset.target === nodeId)
        && (!otherId || l.dataset.source === otherId || l.dataset.target === otherId);
      l.classList.toggle("dim", !on);
      l.classList.toggle("hl", on);
    });
  }
  function clearHighlight() {
    $$(".g-node,.g-edge", svg).forEach((el) => el.classList.remove("dim", "hl"));
  }

  $("#graphLegend").innerHTML = `
    <span><i style="background:var(--high)"></i>严重禁忌</span>
    <span><i style="background:var(--medium)"></i>警示</span>
    <span><i style="background:var(--low)"></i>提示</span>
    <span>┄ 有向规则</span>`;
}

/* ---------------- 推演记录 ---------------- */

const statusMeta = { danger: ["严重", "high"], warning: ["警示", "medium"], safe: ["安全", "ok"] };
const stateBadge = {
  ok: ["相容", "ok"], warning: ["警示", "medium"], danger: ["严重", "high"], blocked: ["阻断", "blocked"],
};

async function loadRuns() {
  state.runs = await api("/api/runs");
  renderRunList();
  renderDiffPickers();
}

function runOptionLabel(r) {
  const rev = r.rule_version_id ? `方案规则 v#${r.rule_version_id}` : `规则 ${r.rule_revision || "-"}`;
  return `#${r.id} · ${r.plan_name || "（已删除方案）"} · ${statusMeta[r.status]?.[0] || r.status} · ${rev} · ${fmtTime(r.created_at)}`;
}

function renderDiffPickers() {
  const baseSel = $("#diffBase");
  const targetSel = $("#diffTarget");
  if (!baseSel || !targetSel) return;
  // 按方案分组渲染，便于识别同一方案的记录
  const groups = new Map();
  state.runs.forEach((r) => {
    const key = r.plan_id === null || r.plan_id === undefined ? -1 : r.plan_id;
    if (!groups.has(key)) groups.set(key, { name: r.plan_id === null ? "未关联方案" : r.plan_name, runs: [] });
    groups.get(key).runs.push(r);
  });
  const buildOptions = (sel) => {
    const cur = sel.value;
    const parts = ['<option value="">— 请选择记录 —</option>'];
    [...groups.entries()]
      .sort((a, b) => (a[0] === -1 ? 1 : b[0] === -1 ? -1 : a[0] - b[0]))
      .forEach(([pid, g]) => {
        parts.push(`<optgroup label="${escapeHtml(g.name || `方案 #${pid}`)}">`);
        g.runs.forEach((r) => {
          parts.push(`<option value="${r.id}" data-plan="${r.plan_id ?? ""}">${escapeHtml(runOptionLabel(r))}</option>`);
        });
        parts.push("</optgroup>");
      });
    sel.innerHTML = parts.join("");
    if (cur && state.runs.some((r) => String(r.id) === String(cur))) sel.value = String(cur);
  };
  buildOptions(baseSel);
  buildOptions(targetSel);
}

function pickRunForDiff(r) {
  const baseSel = $("#diffBase");
  const targetSel = $("#diffTarget");
  if (r.plan_id === null) { toast("该记录未关联已保存方案，不能参与版本差异比较", true); return; }
  if (!baseSel.value) {
    baseSel.value = String(r.id);
  } else if (String(baseSel.value) === String(r.id)) {
    targetSel.value = String(r.id);
  } else if (!targetSel.value || String(targetSel.value) === String(r.id)) {
    targetSel.value = String(r.id);
  } else {
    // 两个槽都被占用：把基准替换为当前点击记录，原对照保留
    baseSel.value = String(r.id);
  }
  toast("已选入差异比较，仅同方案记录可比较");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

$("#btnDiffSwap")?.addEventListener("click", () => {
  const baseSel = $("#diffBase");
  const targetSel = $("#diffTarget");
  const b = baseSel.value;
  baseSel.value = targetSel.value;
  targetSel.value = b;
});

$("#btnRunDiff")?.addEventListener("click", async () => {
  const baseId = $("#diffBase").value;
  const targetId = $("#diffTarget").value;
  if (!baseId || !targetId) { toast("请先选择两条同方案的推演记录", true); return; }
  if (baseId === targetId) { toast("两条记录不能相同", true); return; }
  try {
    const diff = await api(`/api/runs/diff?base_id=${baseId}&target_id=${targetId}`);
    state.diff = diff;
    renderDiff(diff);
    $("#btnExportDiff").classList.remove("hidden");
  } catch (err) { toast(err.message, true); }
});

$("#btnExportDiff")?.addEventListener("click", async () => {
  // 始终导出当前已展示的差异（与最后一次成功比较一致），避免下拉选择已改但结果未刷新
  if (!state.diff) { toast("请先执行版本差异比较", true); return; }
  const baseId = state.diff.base.run_id;
  const targetId = state.diff.target.run_id;
  try {
    const data = await api(`/api/runs/diff/export?base_id=${baseId}&target_id=${targetId}`);
    downloadJson(data, `runs-${baseId}-vs-${targetId}-diff.json`);
    toast("已导出版本差异 JSON");
  } catch (err) { toast(err.message, true); }
});

function renderRunList() {
  const ul = $("#runList");
  ul.innerHTML = "";
  if (!state.runs.length) {
    ul.innerHTML = '<p class="hint">暂无推演记录。在「配液方案」中执行推演后会自动保存。</p>';
    return;
  }
  state.runs.forEach((r) => {
    const [label, cls] = statusMeta[r.status] || ["—", "blocked"];
    const li = document.createElement("li");
    li.className = "item";
    li.innerHTML = `
      <div class="item-title"><span class="badge badge-${cls}">${label}</span>
        ${escapeHtml(r.plan_name || "（方案已删除）")} <span class="item-meta">#${r.id}</span></div>
      <div class="item-meta">${fmtTime(r.created_at)} · ${
        r.rule_version_id
          ? `方案规则版本 #${r.rule_version_id}（${escapeHtml(r.rule_revision || "")}）`
          : `全局限定规则图 ${escapeHtml(r.rule_revision || "-")}`
      }</div>
    `;
    const actions = document.createElement("div");
    actions.className = "item-actions";
    actions.append(
      actionBtn("差异", "btn-small", () => pickRunForDiff(r)),
      actionBtn("查看", "btn-small", async () => {
        const report = await api(`/api/runs/${r.id}`);
        const host = $("#runDetail");
        host.innerHTML = "";
        renderReport(report, { container: host });
        host.scrollIntoView({ behavior: "smooth" });
      }),
      actionBtn("导出 JSON", "btn-small", async () => {
        const data = await api(`/api/runs/${r.id}/export`);
        downloadJson(data, `run-${r.id}-report.json`);
      }),
      actionBtn("删除", "btn-small btn-danger", async () => {
        if (!confirm("删除该推演记录？")) return;
        await api(`/api/runs/${r.id}`, { method: "DELETE" });
        loadRuns();
      }),
    );
    li.appendChild(actions);
    ul.appendChild(li);
  });
}

/* ---------------- 版本差异视图 ---------------- */

const DIFF_FILTERS = [
  { key: "all", label: "全部" },
  { key: "changed", label: "仅变化" },
  { key: "added", label: "🟢 新增" },
  { key: "removed", label: "🔴 消失" },
  { key: "severity", label: "🔶 级别变化" },
  { key: "basis", label: "📝 依据变化" },
  { key: "unchanged", label: "⚪ 一致" },
];

const basisFieldLabels = {
  title: "规则标题", reaction: "反应方程式", rationale: "机理解释", references: "参考文献",
  incoming_category: "新加入类别", existing_category: "已有类别", match_direction: "匹配方向",
  rule_directional: "规则方向", incoming_reagent: "新加入试剂", existing_reagent: "已有试剂",
  incoming_step: "加入步骤", existing_step: "冲突步骤",
};

function renderDiff(diff) {
  const host = $("#diffDetail");
  const s = diff.summary;
  const c = s.finding_changes;
  host.innerHTML = `
    <div class="card">
      <div class="card-head">
        <h2>🔀 版本差异 · ${escapeHtml(diff.plan_name)}</h2>
        <span class="item-meta">基准 #${diff.base.run_id} → 对照 #${diff.target.run_id}</span>
      </div>
      <div class="diff-sides">
        ${renderDiffSide(diff.base)}
        <div class="diff-arrow-big">→</div>
        ${renderDiffSide(diff.target)}
      </div>
      ${renderDiffSummary(s)}
    </div>
    <div class="card">
      <div class="card-head">
        <h2>命中差异列表</h2>
        <div class="diff-filters" id="diffFilters">
          ${DIFF_FILTERS.map((f, i) => `<button type="button" class="btn btn-small diff-filter${i === 1 ? " active" : ""}" data-filter="${f.key}">${f.label}</button>`).join("")}
          <input type="search" id="diffSearch" class="search" placeholder="规则 ID / 试剂 / 标题…" />
        </div>
      </div>
      <p class="hint" id="diffCounts">
        🟢 新增 ${c.added} ｜ 🔴 消失 ${c.removed} ｜ 🔶 级别变化 ${c.severity} ｜ 📝 依据变化 ${c.basis} ｜ ⚪ 一致 ${c.unchanged}
      </p>
      <div class="finding-list" id="diffFindingList"></div>
    </div>`;

  $$(".diff-filter", host).forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".diff-filter", host).forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      renderDiffFindings(diff);
    });
  });
  $("#diffSearch", host).addEventListener("input", () => renderDiffFindings(diff));
  renderDiffFindings(diff);
  host.scrollIntoView?.({ behavior: "smooth", block: "start" });
}

function renderDiffSide(side) {
  const [label, cls] = statusMeta[side.status] || ["—", "blocked"];
  return `
    <div class="diff-side">
      <div class="item-title">记录 #${side.run_id} <span class="badge badge-${cls}">${label}</span></div>
      <div class="item-meta">${fmtTime(side.created_at)}</div>
      <div class="item-meta">规则图版本 <b>${escapeHtml(side.rule_revision || "-")}</b></div>
    </div>`;
}

function renderSetDiff(title, d) {
  const fmt = (arr) => arr.length ? arr.map((x) => `第 ${x} 步`).join("、") : "无";
  return `
    <div class="diff-cell">
      <div class="m-k">${title}</div>
      <div class="item-meta">基准：${fmt(d.base)}</div>
      <div class="item-meta">对照：${fmt(d.target)}</div>
      ${d.added.length ? `<div class="diff-add">＋ ${d.added.map((x) => `第 ${x} 步`).join("、")}</div>` : ""}
      ${d.removed.length ? `<div class="diff-rm">－ ${d.removed.map((x) => `第 ${x} 步`).join("、")}</div>` : ""}
      ${!d.added.length && !d.removed.length ? '<div class="item-meta diff-same">— 无变化 —</div>' : ""}
    </div>`;
}

function renderDiffSummary(s) {
  const st = s.status;
  const statusLine = st.changed
    ? `🔀 <span class="badge badge-${statusMeta[st.base]?.[1] || "blocked"}">${statusMeta[st.base]?.[0] || st.base}</span>
       → <span class="badge badge-${statusMeta[st.target]?.[1] || "blocked"}">${statusMeta[st.target]?.[0] || st.target}</span>`
    : `⚪ <span class="badge badge-${statusMeta[st.target]?.[1] || "blocked"}">${statusMeta[st.target]?.[0] || st.target}</span>（无变化）`;

  const rev = s.rule_revision;
  const revLine = rev.changed
    ? `🔀 <b>${escapeHtml(rev.base || "-")}</b> → <b>${escapeHtml(rev.target || "-")}</b>`
    : `⚪ ${escapeHtml(rev.target || "-")}`;

  const fd = s.first_danger;
  let dangerLine;
  if (fd.change === "none") dangerLine = '⚪ 两次均无首次危险 <span class="badge badge-ok">无变化</span>';
  else if (fd.change === "added") dangerLine = `🟢 对照新增首次危险：第 ${fd.target.step} 步 [${escapeHtml(fd.target.rule_id)}] ${escapeHtml(fd.target.title)}`;
  else if (fd.change === "removed") dangerLine = `🔴 对照已消除首次危险（基准在第 ${fd.base.step} 步 [${escapeHtml(fd.base.rule_id)}]）`;
  else dangerLine = `🔀 首次危险变化：基准第 ${fd.base.step} 步 [${escapeHtml(fd.base.rule_id)}] → 对照第 ${fd.target.step} 步 [${escapeHtml(fd.target.rule_id)}]`;

  const countsRows = s.counts.map((x) => `
    <tr class="${x.delta !== 0 ? "diff-row-chg" : ""}">
      <td>${x.label}</td><td>${x.base}</td><td>${x.target}</td>
      <td>${x.delta === 0 ? "—" : (x.delta > 0 ? `<span class="diff-add">＋${x.delta}</span>` : `<span class="diff-rm">${x.delta}</span>`)}</td>
    </tr>`).join("");

  return `
    <div class="diff-summary-grid">
      <div class="diff-cell"><div class="m-k">总体状态</div><div>${statusLine}</div></div>
      <div class="diff-cell"><div class="m-k">规则图版本</div><div>${revLine}</div></div>
      <div class="diff-cell diff-cell-wide"><div class="m-k">首次危险</div><div>${dangerLine}</div></div>
      ${renderSetDiff("受影响步骤（发生反应 + 被阻断）", s.affected_steps)}
      ${renderSetDiff("阻断步骤（中止后未执行）", s.blocked_steps)}
      <div class="diff-cell diff-cell-wide">
        <div class="m-k">命中计数</div>
        <table class="grid diff-count-table">
          <thead><tr><th>指标</th><th>基准</th><th>对照</th><th>增减</th></tr></thead>
          <tbody>${countsRows}</tbody>
        </table>
      </div>
      <div class="diff-cell diff-cell-wide">
        <div class="m-k">逐步状态对齐</div>
        ${renderStepAlign(s.steps)}
      </div>
    </div>`;
}

function renderStepAlign(steps) {
  const rows = steps.items.map((it) => {
    const badge = (state) => {
      if (!state) return '<span class="item-meta">—</span>';
      const [label, cls] = stateBadge[state] || [state, "blocked"];
      return `<span class="badge badge-${cls}">${label}</span>`;
    };
    const mark = { added: '<span class="diff-add">新增步骤</span>', removed: '<span class="diff-rm">消失步骤</span>', changed: '<span class="badge badge-medium">状态变化</span>', same: "" }[it.change];
    return `<tr class="${it.change !== "same" ? "diff-row-chg" : ""}">
      <td>第 ${it.step} 步</td><td>${badge(it.base_state)}</td><td>${badge(it.target_state)}</td><td>${mark}</td>
    </tr>`;
  }).join("");
  return `<table class="grid diff-count-table">
    <thead><tr><th>步骤</th><th>基准状态</th><th>对照状态</th><th></th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function renderDiffFindings(diff) {
  const box = $("#diffFindingList");
  if (!box) return;
  const filter = ($$("#diffFilters .diff-filter.active")[0]?.dataset.filter) || "changed";
  const q = ($("#diffSearch").value || "").toLowerCase();
  const items = diff.findings.filter((e) => {
    if (filter === "changed" && e.change === "unchanged") return false;
    if (filter !== "all" && filter !== "changed" && e.change !== filter) return false;
    if (q) {
      const hay = [e.rule_id, e.base?.title, e.target?.title, e.base?.incoming_reagent,
        e.target?.incoming_reagent, e.base?.existing_reagent, e.target?.existing_reagent,
        e.base?.reaction, e.target?.reaction]
        .filter(Boolean).join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  box.innerHTML = items.length
    ? items.map(renderDiffFinding).join("")
    : '<p class="hint">没有符合筛选条件的差异条目。</p>';
  $$(".diff-finding", box).forEach((el) => {
    el.addEventListener("click", () => {
      const e = diff.findings.find((x) => x._id === el.dataset.id);
      if (e) openDiffFindingModal(e, diff);
    });
  });
}

let __diffSeq = 0;
function renderDiffFinding(e) {
  e._id = e._id ?? `d${++__diffSeq}`;
  const cur = e.target || e.base;
  const sevHtml = (s) => s ? `<span class="badge badge-${s}">${sevLabel[s]}</span>` : '<span class="item-meta">无</span>';
  let head;
  if (e.change === "added") head = `<span class="badge badge-ok diff-tag">🟢 新增命中</span>`;
  else if (e.change === "removed") head = `<span class="badge badge-blocked diff-tag">🔴 消失命中</span>`;
  else if (e.change === "severity") head = `<span class="badge badge-medium diff-tag">🔶 ${sevHtml(e.base_severity)} → ${sevHtml(e.target_severity)}</span>`;
  else if (e.change === "basis") head = '<span class="badge badge-low diff-tag">📝 反应依据变化</span>';
  else head = '<span class="badge badge-blocked diff-tag">⚪ 一致</span>';

  const stepLine = `第 ${e.incoming_step} 步「${escapeHtml(cur.incoming_reagent || "-")}」 × 第 ${e.existing_step} 步「${escapeHtml(cur.existing_reagent || "-")}」`;
  const fieldTags = e.changed_fields.length
    ? `<div class="item-meta">变化字段：${e.changed_fields.map((f) => `<span class="badge badge-low">${basisFieldLabels[f] || f}</span>`).join(" ")}</div>`
    : "";
  return `
    <div class="finding-card diff-finding ${e.target_severity || e.base_severity || ""}" data-id="${e._id}">
      <div class="fc-title">${head} <b>[${escapeHtml(e.rule_id || "-")}]</b> ${escapeHtml(cur.title || "")}</div>
      <div class="fc-meta">${stepLine}</div>
      <div class="fc-meta">${escapeHtml(cur.reaction || "")} · 点击查看两侧反应依据对比</div>
      ${fieldTags}
    </div>`;
}

function openDiffFindingModal(e, diff) {
  const row = (label, a, b) => `
    <tr><td class="m-k">${label}</td>
      <td>${a ?? "—"}</td><td>${b ?? "—"}</td></tr>`;
  const a = e.base, b = e.target;
  const sev = (s) => s ? `<span class="badge badge-${s}">${sevLabel[s]}</span>` : "—";
  const refs = (arr) => (arr && arr.length) ? arr.map((x) => `· ${escapeHtml(x)}`).join("<br>") : "—";
  openModal(`
    <button class="btn btn-ghost modal-close">✕ 关闭</button>
    <h3>${e.change_label} · [${escapeHtml(e.rule_id || "-")}] ${escapeHtml((b || a).title || "")}</h3>
    <div class="item-meta">基准记录 #${diff.base.run_id}（规则 ${escapeHtml(diff.base.rule_revision || "-")}）
      → 对照记录 #${diff.target.run_id}（规则 ${escapeHtml(diff.target.rule_revision || "-")}）</div>
    <table class="grid diff-modal-table">
      <thead><tr><th></th><th>基准（旧）</th><th>对照（新）</th></tr></thead>
      <tbody>
        ${row("严重级别", a ? sev(a.severity) : "—", b ? sev(b.severity) : "—")}
        ${row("步骤", a ? `第 ${a.incoming_step} 步加入「${escapeHtml(a.incoming_reagent)}」` : "—",
                  b ? `第 ${b.incoming_step} 步加入「${escapeHtml(b.incoming_reagent)}」` : "—")}
        ${row("冲突对象", a ? `第 ${a.existing_step} 步「${escapeHtml(a.existing_reagent)}」` : "—",
                  b ? `第 ${b.existing_step} 步「${escapeHtml(b.existing_reagent)}」` : "—")}
        ${row("类别对", a ? `${escapeHtml(catLabel(a.incoming_category))} × ${escapeHtml(catLabel(a.existing_category))}` : "—",
                  b ? `${escapeHtml(catLabel(b.incoming_category))} × ${escapeHtml(catLabel(b.existing_category))}` : "—")}
        ${row("反应方程式", a ? `<span class="m-eq">${escapeHtml(a.reaction)}</span>` : "—",
                  b ? `<span class="m-eq">${escapeHtml(b.reaction)}</span>` : "—")}
        ${row("机理解释", a ? escapeHtml(a.rationale).replace(/\n/g, "<br>") : "—",
                  b ? escapeHtml(b.rationale).replace(/\n/g, "<br>") : "—")}
        ${row("参考文献", a ? refs(a.references) : "—", b ? refs(b.references) : "—")}
        ${row("匹配方向", a ? `${a.match_direction === "incoming->existing" ? "新加入 → 已存在" : "已存在 → 新加入"}${a.rule_directional ? "（有向）" : "（无向）"}` : "—",
                  b ? `${b.match_direction === "incoming->existing" ? "新加入 → 已存在" : "已存在 → 新加入"}${b.rule_directional ? "（有向）" : "（无向）"}` : "—")}
      </tbody>
    </table>
    ${e.changed_fields.length ? `<p class="hint">变化字段：${e.changed_fields.map((f) => basisFieldLabels[f] || f).join("、")}</p>` : ""}
  `);
  $("#modalBox").classList.add("modal-wide");
}

/* ---------------- 方案规则版本 ---------------- */

const rvStatusMeta = {
  draft: ["草稿", "medium"],
  published: ["生效中", "ok"],
  superseded: ["已替代", "blocked"],
  deactivated: ["已停用", "blocked"],
};

const rv = {
  versions: [],
  effectiveId: null,
  globalRevision: "",
  edit: null,          // 草稿编辑器状态 { id, rules, note }
  editingRuleId: null, // 正在新增/编辑的规则条目 ID
  diff: null,
};

function refreshRvPlanSelect(preferId) {
  const sel = $("#rvPlanSelect");
  if (!sel) return;
  const cur = preferId ?? (sel.value || state.rvPlanId);
  sel.innerHTML = '<option value="">— 请选择方案 —</option>' +
    state.plans.map((p) => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
  if (cur && state.plans.some((p) => String(p.id) === String(cur))) {
    sel.value = String(cur);
    state.rvPlanId = Number(cur);
  } else {
    state.rvPlanId = null;
  }
  renderRvEffective();
}

function renderRvEffective() {
  const box = $("#rvEffective");
  if (!box) return;
  const plan = state.plans.find((p) => String(p.id) === String(state.rvPlanId));
  if (!plan) { box.innerHTML = ""; return; }
  const ev = plan.effective_rule_version;
  if (ev) {
    box.innerHTML = `当前生效：<span class="badge badge-ok">v${ev.version_no} · ${escapeHtml(ev.status_label)}</span>
      <span class="item-meta">${ev.rule_count} 条规则 · 发布于 ${fmtTime(ev.published_at)}</span>`;
  } else {
    box.innerHTML = `<span class="badge badge-blocked">未启用方案版本</span>
      <span class="item-meta">判定使用全局限定规则图 ${escapeHtml(state.revision || "")}</span>`;
  }
}

$("#rvPlanSelect")?.addEventListener("change", () => {
  state.rvPlanId = $("#rvPlanSelect").value ? Number($("#rvPlanSelect").value) : null;
  rv.versions = [];
  renderRvEffective();
});

$("#btnRvManage")?.addEventListener("click", openRvManager);
$("#btnRvNewDraft")?.addEventListener("click", async () => {
  if (!state.rvPlanId) { toast("请先选择方案", true); return; }
  try {
    const created = await api(`/api/plans/${state.rvPlanId}/rule-versions`, {
      method: "POST",
      body: { note: "" },
    });
    await loadRvVersions();
    await loadPlans();
    openRvDraftEditor(created.id);
    toast("已基于当前规则创建草稿，编辑后发布");
  } catch (err) { toast(err.message, true); }
});

async function loadRvVersions() {
  if (!state.rvPlanId) { rv.versions = []; return; }
  const data = await api(`/api/plans/${state.rvPlanId}/rule-versions`);
  rv.versions = data.versions;
  rv.effectiveId = data.effective_version_id;
  rv.globalRevision = data.global_revision;
  renderRvEffective();
}

function openRvManager() {
  if (!state.rvPlanId) { toast("请先选择方案", true); return; }
  openModal(`
    <button class="btn btn-ghost modal-close">✕ 关闭</button>
    <h3>📦 规则版本管理</h3>
    <div id="rvManagerBody" class="rv-manager-body"></div>
  `);
  $("#modalBox").classList.add("modal-wide");
  loadRvVersions().then(renderRvList).catch((e) => toast(e.message, true));
}

function renderRvList() {
  const host = $("#rvManagerBody");
  if (!host) return;
  const plan = state.plans.find((p) => String(p.id) === String(state.rvPlanId));
  const hasDraft = rv.versions.some((v) => v.status === "draft");

  const rows = rv.versions.length
    ? rv.versions.map((v) => {
        const [sLabel, sCls] = rvStatusMeta[v.status] || [v.status, "blocked"];
        const eff = v.is_effective ? '<span class="badge badge-ok">当前生效</span>' : "";
        const btns = [];
        btns.push(`<button type="button" class="btn btn-small" data-rv-act="rules" data-id="${v.id}">规则/依据</button>`);
        btns.push(`<button type="button" class="btn btn-small" data-rv-act="diff" data-id="${v.id}">差异</button>`);
        if (v.status === "draft") {
          btns.push(`<button type="button" class="btn btn-small" data-rv-act="edit" data-id="${v.id}">编辑草稿</button>`);
          btns.push(`<button type="button" class="btn btn-small btn-primary" data-rv-act="publish" data-id="${v.id}">发布</button>`);
          btns.push(`<button type="button" class="btn btn-small btn-danger" data-rv-act="delete" data-id="${v.id}">删除</button>`);
        } else if (v.status === "published") {
          btns.push(`<button type="button" class="btn btn-small" data-rv-act="preview" data-id="${v.id}">预览判定</button>`);
          btns.push(`<button type="button" class="btn btn-small btn-danger" data-rv-act="deactivate" data-id="${v.id}">停用</button>`);
        } else if (v.status === "superseded" || v.status === "deactivated") {
          btns.push(`<button type="button" class="btn btn-small" data-rv-act="preview" data-id="${v.id}">预览判定</button>`);
        }
        return `
          <tr>
            <td><b>v${v.version_no}</b></td>
            <td><span class="badge badge-${sCls}">${sLabel}</span> ${eff}</td>
            <td>${v.rule_count} 条
              <span class="item-meta"><span class="badge badge-high">高 ${v.severity_counts.high}</span>
              <span class="badge badge-medium">警 ${v.severity_counts.medium}</span>
              <span class="badge badge-low">提 ${v.severity_counts.low}</span></span>
            </td>
            <td class="item-meta">
              来源：${v.source_of_version === "global"
                ? `全局 ${escapeHtml(v.base_revision || "")}`
                : `基于 v${rv.versions.find((x) => x.id === v.base_version_id)?.version_no ?? "?"}`}<br>
              创建 ${fmtTime(v.created_at)}${v.published_at ? ` · 发布 ${fmtTime(v.published_at)}` : ""}
              ${v.deactivated_at ? ` · 停用 ${fmtTime(v.deactivated_at)}` : ""}
            </td>
            <td class="item-meta">${escapeHtml(v.note || "")}</td>
            <td><div class="rv-row-actions">${btns.join("")}</div></td>
          </tr>`;
      }).join("")
    : '<tr><td colspan="6" class="hint">该方案还没有规则版本。新建草稿将克隆全局限定规则图。</td></tr>';

  host.innerHTML = `
    <div class="card-head">
      <span class="item-title">${escapeHtml(plan?.name || "")}</span>
      <span class="item-meta">全局限定规则图版本 ${escapeHtml(rv.globalRevision || state.revision || "-")}</span>
    </div>
    <div class="table-wrap">
      <table class="grid rv-table">
        <thead><tr><th>版本</th><th>状态</th><th>规则</th><th>时间</th><th>备注</th><th>操作</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="form-actions">
      <button type="button" class="btn btn-small btn-primary" data-rv-act="new" ${hasDraft ? "disabled" : ""}>
        ＋ 新建版本草稿${hasDraft ? "（已有草稿）" : ""}
      </button>
    </div>`;

  host.querySelector("[data-rv-act='new']")?.addEventListener("click", async () => {
    try {
      const created = await api(`/api/plans/${state.rvPlanId}/rule-versions`, { method: "POST", body: {} });
      await loadRvVersions(); await loadPlans();
      openRvDraftEditor(created.id);
    } catch (err) { toast(err.message, true); }
  });

  $$("button[data-rv-act]", host).forEach((btn) => {
    btn.addEventListener("click", () => rvAction(btn.dataset.rvAct, Number(btn.dataset.id)));
  });
}

async function rvAction(act, id) {
  const v = rv.versions.find((x) => x.id === id);
  try {
    if (act === "edit") return openRvDraftEditor(id);
    if (act === "rules") return openRvRulesView(id);
    if (act === "diff") return openRvDiff(id);
    if (act === "publish") {
      if (!confirm(`确认发布 v${v.version_no}？发布后该方案判定立即改用此版本，原生效版本将被替代。`)) return;
      await api(`/api/plans/${state.rvPlanId}/rule-versions/${id}/publish`, { method: "POST" });
      await loadRvVersions(); await loadPlans();
      renderRvList();
      toast(`v${v.version_no} 已发布并生效`);
      return;
    }
    if (act === "deactivate") {
      if (!confirm(`确认停用 v${v.version_no}？停用后该方案判定将回落至全局限定规则图。`)) return;
      await api(`/api/plans/${state.rvPlanId}/rule-versions/${id}/deactivate`, { method: "POST" });
      await loadRvVersions(); await loadPlans();
      renderRvList();
      toast(`v${v.version_no} 已停用，不再参与判定`);
      return;
    }
    if (act === "delete") {
      if (!confirm(`删除草稿 v${v.version_no}？此操作不可撤销。`)) return;
      await api(`/api/plans/${state.rvPlanId}/rule-versions/${id}`, { method: "DELETE" });
      await loadRvVersions(); await loadPlans();
      renderRvList();
      toast("草稿已删除");
      return;
    }
    if (act === "preview") return previewRvVersion(id);
  } catch (err) { toast(err.message, true); }
}

/* ---------- 规则只读视图 ---------- */

function openRvRulesView(id) {
  const v = rv.versions.find((x) => x.id === id);
  const host = $("#rvManagerBody");
  const [sLabel, sCls] = rvStatusMeta[v.status] || [v.status, "blocked"];
  host.innerHTML = `
    <div class="card-head">
      <h3 style="margin:0">v${v.version_no} 规则与严重级别依据
        <span class="badge badge-${sCls}">${sLabel}</span></h3>
      <button type="button" class="btn btn-small" data-rv-back>← 返回版本列表</button>
    </div>
    <p class="hint">创建于 ${fmtTime(v.created_at)}${v.published_at ? ` · 发布于 ${fmtTime(v.published_at)}` : ""}
      ${v.note ? " · " + escapeHtml(v.note) : ""}</p>
    <div class="finding-list">${v.rules.map((r) => `
      <div class="finding-card ${r.severity}">
        <div class="fc-title"><span class="badge badge-${r.severity}">${sevLabel[r.severity]}</span>
          [${escapeHtml(r.id)}] ${escapeHtml(r.title)}
          ${r.builtin ? '<span class="badge badge-ok">内置</span>' : ""}
          ${r.directional ? '<span class="badge badge-blocked">有向</span>' : ""}</div>
        <div class="fc-meta">${escapeHtml(catLabel(r.source))} → ${escapeHtml(catLabel(r.target))}</div>
        <div class="fc-meta">${escapeHtml(r.reaction)}</div>
        <div class="fc-meta">${escapeHtml(r.rationale)}</div>
        <div class="fc-meta">${r.references.map((x) => `<span class="badge badge-low">${escapeHtml(x)}</span>`).join(" ")}</div>
      </div>`).join("")}</div>`;
  host.querySelector("[data-rv-back]").addEventListener("click", renderRvList);
}

/* ---------- 草稿编辑器 ---------- */

function openRvDraftEditor(id) {
  const v = rv.versions.find((x) => x.id === id);
  if (!v) return;
  if (v.status !== "draft") { toast("只有草稿可以编辑", true); return; }
  rv.edit = { id, note: v.note || "", rules: JSON.parse(JSON.stringify(v.rules)) };
  renderRvEditor();
}

function renderRvEditor() {
  const host = $("#rvManagerBody");
  const e = rv.edit;
  host.innerHTML = `
    <div class="card-head">
      <h3 style="margin:0">编辑草稿 v${rv.versions.find((x) => x.id === e.id)?.version_no}</h3>
      <button type="button" class="btn btn-small" data-rv-back>← 返回</button>
    </div>
    <label class="form-row">版本备注
      <input type="text" id="rvNote" maxlength="2000" value="${escapeHtml(e.note)}" placeholder="本版变更说明，如：依据 GB 新标准将 R001 降为警示" />
    </label>
    <div class="card-head">
      <h3>规则集合（${e.rules.length}）</h3>
      <button type="button" class="btn btn-small" id="rvAddRule">＋ 新增规则</button>
    </div>
    <div class="table-wrap">
      <table class="grid rv-table">
        <thead><tr><th>编号</th><th>类别 A → B</th><th>严重级别</th><th>标题 / 方程式</th><th>操作</th></tr></thead>
        <tbody>
          ${e.rules.map((r) => `
          <tr>
            <td><b>${escapeHtml(r.id)}</b></td>
            <td class="item-meta">${escapeHtml(catLabel(r.source))} → ${escapeHtml(catLabel(r.target))}
              ${r.directional ? '<span class="badge badge-blocked">有向</span>' : ""}</td>
            <td>
              <select data-rv-sev="${r.id}">
                <option value="high" ${r.severity === "high" ? "selected" : ""}>严重</option>
                <option value="medium" ${r.severity === "medium" ? "selected" : ""}>警示</option>
                <option value="low" ${r.severity === "low" ? "selected" : ""}>提示</option>
              </select>
            </td>
            <td class="item-meta">${escapeHtml(r.title)}<br>${escapeHtml(r.reaction)}</td>
            <td class="rv-row-actions">
              <button type="button" class="btn btn-small" data-rv-editrule="${r.id}">编辑依据</button>
              <button type="button" class="btn btn-small btn-danger" data-rv-delrule="${r.id}">移除</button>
            </td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>
    <div id="rvRuleFormHost"></div>
    <div class="form-actions">
      <button type="button" class="btn" id="rvPreviewDraft">▶ 预览判定</button>
      <button type="button" class="btn" id="rvSaveDraft">💾 保存草稿</button>
      <button type="button" class="btn btn-primary" id="rvPublishDraft">🚩 保存并发布</button>
    </div>`;

  host.querySelector("[data-rv-back]").addEventListener("click", renderRvList);
  host.querySelector("#rvNote").addEventListener("input", (ev) => (e.note = ev.target.value));
  $$("select[data-rv-sev]", host).forEach((sel) => {
    sel.addEventListener("change", () => {
      const r = e.rules.find((x) => x.id === sel.dataset.rvSev);
      if (r) r.severity = sel.value;
    });
  });
  $$("button[data-rv-editrule]", host).forEach((b) =>
    b.addEventListener("click", () => openRvRuleForm(host, b.dataset.rvEditrule)));
  $$("button[data-rv-delrule]", host).forEach((b) =>
    b.addEventListener("click", () => {
      e.rules = e.rules.filter((x) => x.id !== b.dataset.rvDelrule);
      renderRvEditor();
    }));
  host.querySelector("#rvAddRule").addEventListener("click", () => openRvRuleForm(host, null));
  host.querySelector("#rvPreviewDraft").addEventListener("click", () => saveRvDraft(true).then(() => previewRvVersion(e.id)));
  host.querySelector("#rvSaveDraft").addEventListener("click", () => saveRvDraft(false));
  host.querySelector("#rvPublishDraft").addEventListener("click", async () => {
    try {
      await saveRvDraft(false, true);
      await api(`/api/plans/${state.rvPlanId}/rule-versions/${e.id}/publish`, { method: "POST" });
      await loadRvVersions(); await loadPlans();
      renderRvList();
      toast("草稿已发布并生效");
    } catch (err) { toast(err.message, true); }
  });
}

function openRvRuleForm(host, ruleId) {
  const e = rv.edit;
  const existing = ruleId ? e.rules.find((x) => x.id === ruleId) : null;
  const r = existing ? JSON.parse(JSON.stringify(existing)) : {
    id: "", source: "", target: "", directional: false, severity: "medium",
    title: "", reaction: "", rationale: "", references: [], builtin: false,
  };
  const formHost = $("#rvRuleFormHost") || host;
  formHost.innerHTML = `
    <div class="rv-rule-form">
      <div class="card-head"><h3>${existing ? "编辑规则依据" : "新增规则"}</h3></div>
      <div class="form-row">
        <label>编号<input type="text" id="rvRId" value="${escapeHtml(r.id)}" ${existing ? "disabled" : ""} placeholder="C101" /></label>
        <label>级别
          <select id="rvRSeverity">
            <option value="high" ${r.severity === "high" ? "selected" : ""}>严重（命中即中止）</option>
            <option value="medium" ${r.severity === "medium" ? "selected" : ""}>警示（继续）</option>
            <option value="low" ${r.severity === "low" ? "selected" : ""}>提示</option>
          </select>
        </label>
      </div>
      <div class="form-row">
        <label>类别 A<input type="text" id="rvRSource" value="${escapeHtml(r.source)}" placeholder="strong_acid" /></label>
        <label>类别 B<input type="text" id="rvRTarget" value="${escapeHtml(r.target)}" placeholder="cyanide" /></label>
      </div>
      <label class="switch"><input type="checkbox" id="rvRDirectional" ${r.directional ? "checked" : ""}/> 有向规则（仅 A→B）</label>
      <label>标题<input type="text" id="rvRTitle" value="${escapeHtml(r.title)}" /></label>
      <label>反应方程式<textarea id="rvRReaction" rows="2">${escapeHtml(r.reaction)}</textarea></label>
      <label>判定依据 / 机理解释<textarea id="rvRRationale" rows="3">${escapeHtml(r.rationale)}</textarea></label>
      <label>参考文献（每行一条）<textarea id="rvRRefs" rows="2">${escapeHtml(r.references.join("\n"))}</textarea></label>
      <div class="form-actions">
        <button type="button" class="btn btn-primary" id="rvRSave">确认</button>
        <button type="button" class="btn btn-ghost" id="rvRCancel">取消</button>
      </div>
    </div>`;
  formHost.querySelector("#rvRCancel").addEventListener("click", () => (formHost.innerHTML = ""));
  formHost.querySelector("#rvRSave").addEventListener("click", () => {
    const data = {
      ...r,
      id: $("#rvRId").value.trim(),
      source: $("#rvRSource").value.trim(),
      target: $("#rvRTarget").value.trim(),
      directional: $("#rvRDirectional").checked,
      severity: $("#rvRSeverity").value,
      title: $("#rvRTitle").value.trim(),
      reaction: $("#rvRReaction").value.trim(),
      rationale: $("#rvRRationale").value.trim(),
      references: $("#rvRRefs").value.split("\n").map((s) => s.trim()).filter(Boolean),
    };
    if (!data.id || !data.source || !data.target) { toast("编号和类别 A/B 必填", true); return; }
    if (data.source === data.target) { toast("两个类别不能相同", true); return; }
    const other = e.rules.find((x) => x.id === data.id);
    if (other && other !== existing) { toast(`规则编号 ${data.id} 已存在`, true); return; }
    if (existing) {
      const idx = e.rules.findIndex((x) => x.id === ruleId);
      e.rules[idx] = data;
    } else {
      e.rules.push(data);
    }
    formHost.innerHTML = "";
    renderRvEditor();
  });
}

async function saveRvDraft(silent = false, _andPublish = false) {
  const e = rv.edit;
  if (!e) return false;
  try {
    const updated = await api(`/api/plans/${state.rvPlanId}/rule-versions/${e.id}`, {
      method: "PUT",
      body: { note: e.note, rules: e.rules },
    });
    const idx = rv.versions.findIndex((x) => x.id === e.id);
    if (idx >= 0) rv.versions[idx] = updated;
    if (!silent) toast("草稿已保存");
    return true;
  } catch (err) {
    toast(err.message, true);
    return false;
  }
}

async function previewRvVersion(id) {
  try {
    const report = await api(
      `/api/plans/${state.rvPlanId}/simulate?persist=false&rule_version_id=${id}`,
      { method: "POST" },
    );
    const v = rv.versions.find((x) => x.id === id);
    openModal(`
      <button class="btn btn-ghost modal-close">✕ 关闭</button>
      <h3>预览：按 v${v.version_no}（${escapeHtml((rvStatusMeta[v.status] || [v.status])[0])}）判定</h3>
      <p class="hint">该结果不落盘、不影响正式判定；正式推演只读取当前生效版本。</p>
      <div id="rvPreviewHost"></div>`);
    $("#modalBox").classList.add("modal-wide");
    renderReport(report, { container: $("#rvPreviewHost"), hideExport: true });
  } catch (err) { toast(err.message, true); }
}

/* ---------- 版本差异 ---------- */

function rvDiffOptions(selectedBase, selectedTarget) {
  const opt = (val, label, sel) =>
    `<option value="${val}" ${String(sel) === String(val) ? "selected" : ""}>${escapeHtml(label)}</option>`;
  const globalOpt = (sel) => opt("global", `全局限定规则图（${rv.globalRevision || state.revision || "-"}）`, sel);
  const verOpts = (sel) => rv.versions.map((v) =>
    opt(v.id, `v${v.version_no} · ${(rvStatusMeta[v.status] || [v.status])[0]} · ${v.rule_count} 条`, sel)).join("");
  return {
    baseHtml: '<option value="">— 选择基准 —</option>' + globalOpt(selectedBase) + verOpts(selectedBase),
    targetHtml: '<option value="global">全局限定规则图（当前）</option>' + verOpts(selectedTarget),
  };
}

function openRvDiff(prefId) {
  const host = $("#rvManagerBody");
  const effId = rv.effectiveId;
  // 默认对照 = 当前生效版本（无则全局）；默认基准 = 最近一个已替代版本（无则全局）
  const newestSuperseded = rv.versions
    .filter((v) => v.status === "superseded")
    .sort((a, b) => b.version_no - a.version_no)[0];
  let targetSel = effId ?? "global";
  let baseSel = prefId
    ?? newestSuperseded?.id
    ?? (targetSel === "global"
      ? (rv.versions.find((v) => v.status !== "draft")?.id ?? "global")
      : "global");
  if (String(baseSel) === String(targetSel) && baseSel !== "global") baseSel = "global";
  const opts = rvDiffOptions(baseSel, targetSel);
  host.innerHTML = `
    <div class="card-head">
      <h3 style="margin:0">🔀 规则版本差异</h3>
      <button type="button" class="btn btn-small" data-rv-back>← 返回版本列表</button>
    </div>
    <div class="diff-picker">
      <label>基准（旧）<select id="rvDiffBase">${opts.baseHtml}</select></label>
      <span class="diff-arrow">→</span>
      <label>对照（新）<select id="rvDiffTarget">${opts.targetHtml}</select></label>
      <button type="button" class="btn btn-primary" id="rvRunDiff">🔍 比较</button>
      <button type="button" class="btn hidden" id="rvExportDiff">⬇ 导出差异 JSON</button>
    </div>
    <div id="rvDiffBody"></div>`;
  host.querySelector("[data-rv-back]").addEventListener("click", renderRvList);
  host.querySelector("#rvRunDiff").addEventListener("click", runRvDiff);
  host.querySelector("#rvExportDiff").addEventListener("click", () => {
    if (rv.diff) downloadJson(rv.diff, `plan-${state.rvPlanId}-rule-diff.json`);
  });
}

async function runRvDiff() {
  const base = $("#rvDiffBase").value;
  const target = $("#rvDiffTarget").value || "global";
  if (!base) { toast("请选择基准版本", true); return; }
  try {
    const data = await api(
      `/api/plans/${state.rvPlanId}/rule-versions/diff?base=${encodeURIComponent(base)}&target=${encodeURIComponent(target)}`
    );
    rv.diff = data;
    renderRvDiffResult(data);
    $("#rvExportDiff").classList.remove("hidden");
  } catch (err) { toast(err.message, true); }
}

function rvSideLabel(side) {
  if (side.kind === "global") return `全局规则图 ${escapeHtml(side.rule_revision || "")}`;
  return `v${side.version_no} · ${escapeHtml(side.status_label)}`;
}

function renderRvDiffResult(d) {
  const host = $("#rvDiffBody");
  const c = d.changes;
  const tags = {
    added: '<span class="badge badge-ok diff-tag">🟢 新增规则</span>',
    removed: '<span class="badge badge-blocked diff-tag">🔴 删除规则</span>',
    severity: '<span class="badge badge-medium diff-tag">🔶 严重级别变化</span>',
    basis: '<span class="badge badge-low diff-tag">📝 判定依据变化</span>',
    unchanged: '<span class="badge badge-blocked diff-tag">⚪ 一致</span>',
  };
  const sev = (s) => s ? `<span class="badge badge-${s}">${sevLabel[s]}</span>` : "—";
  host.innerHTML = `
    <div class="diff-sides" style="margin:10px 0">
      <div class="diff-side"><div class="item-title">基准</div><div class="item-meta">${rvSideLabel(d.base)}</div>
        <div class="item-meta">${d.rule_count.base} 条规则</div></div>
      <div class="diff-arrow-big">→</div>
      <div class="diff-side"><div class="item-title">对照</div><div class="item-meta">${rvSideLabel(d.target)}</div>
        <div class="item-meta">${d.rule_count.target} 条规则</div></div>
    </div>
    <p class="hint">🟢 新增 ${c.added} ｜ 🔴 删除 ${c.removed} ｜ 🔶 级别变化 ${c.severity}
      ｜ 📝 依据变化 ${c.basis} ｜ ⚪ 一致 ${c.unchanged}</p>
    <div class="finding-list">
      ${d.rules.filter((e) => e.change !== "unchanged").map((e) => {
        const cur = e.target || e.base;
        return `
        <div class="finding-card ${e.target_severity || e.base_severity || ""}">
          <div class="fc-title">${tags[e.change]} <b>[${escapeHtml(e.rule_id)}]</b> ${escapeHtml(cur.title || "")}</div>
          <div class="fc-meta">${escapeHtml(catLabel(cur.source))} → ${escapeHtml(catLabel(cur.target))}</div>
          <div class="fc-meta">严重级别：${sev(e.base_severity)} → ${sev(e.target_severity)}</div>
          ${e.changed_fields.length ? `<div class="fc-meta">变化字段：${e.field_labels.map((f) => `<span class="badge badge-low">${escapeHtml(f)}</span>`).join(" ")}</div>` : ""}
          <div class="fc-meta">${escapeHtml(cur.reaction || "")}</div>
        </div>`;
      }).join("") || '<p class="hint">两个版本完全一致。</p>'}
    </div>`;
}

/* ---------------- 工具 ---------------- */

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtTime(iso) {
  try {
    const d = new Date(iso);
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  } catch {
    return iso;
  }
}

/* ---------------- 启动 ---------------- */

(async function init() {
  state.stepRows = [makeStepRow()];
  renderStepRows();
  renderCategoryChips();
  try {
    await Promise.all([loadReagents(), loadPlans(), loadRules()]);
  } catch (err) {
    toast("初始化失败：" + err.message, true);
  }
})();
