"use strict";
const $ = (id) => document.getElementById(id);
const form = $("ask-form");
const question = $("question");
const contextFields = ["airline", "fare_type", "reason", "booking_channel"];
const examples = {
  baggage: {question: "Peach 的手提行李有什么重量和件数限制？", context: {airline: "peach"}},
  change: {question: "Standard Plus 因个人原因改签，官网办理需要手续费吗？", context: {airline: "peach", fare_type: "standard_plus", reason: "voluntary", booking_channel: "direct"}},
  cancel: {question: "Standard 因个人原因取消，官网购买的机票以什么方式退款？", context: {airline: "peach", fare_type: "standard", reason: "voluntary", booking_channel: "direct"}},
  code_overview: {question: "分析 osTicket 的仓库结构和主要入口", task: "code_analysis", context: {}},
  code_login: {question: "osTicket 客服登录相关代码在哪里？", task: "code_analysis", context: {}},
  code_api: {question: "osTicket API 返回 401 时，应该查看哪些代码？", task: "code_analysis", context: {}}
};
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function count() { $("char-count").textContent = `${question.value.length} / 1500`; }
question.addEventListener("input", count);
document.querySelectorAll("[data-example]").forEach(button => button.addEventListener("click", () => {
  const sample = examples[button.dataset.example];
  question.value = sample.question;
  contextFields.forEach(field => $(field).value = sample.context[field] || "");
  $("task").value = sample.task || "travel_policy";
  $("file_path").value = "";
  updateTask();
  count(); question.focus();
}));
function switchView(json) {
  $("answer-view").hidden = json; $("json-view").hidden = !json;
  ["tab-answer", "tab-json"].forEach((id, index) => {
    const selected = Boolean(index) === json;
    $(id).setAttribute("aria-selected", String(selected)); $(id).classList.toggle("selected", selected);
  });
}
$("tab-answer").addEventListener("click", () => switchView(false));
$("tab-json").addEventListener("click", () => switchView(true));
document.querySelector(".result-tabs").addEventListener("keydown", event => {
  if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
    event.preventDefault(); const json = event.target.id !== "tab-json";
    switchView(json); $(json ? "tab-json" : "tab-answer").focus();
  }
});
function showWorkspace(library) {
  $("workspace").hidden = library; $("library").hidden = !library;
  $("breadcrumb").textContent = library ? "公开资料库" : "客服协助代理";
  for (const [id, active] of [["nav-ask", !library], ["nav-library", library]]) {
    $(id).classList.toggle("active", active);
    if (active) $(id).setAttribute("aria-current", "page"); else $(id).removeAttribute("aria-current");
  }
}
$("nav-ask").addEventListener("click", () => showWorkspace(false));
$("nav-library").addEventListener("click", () => {showWorkspace(true); loadLibrary();});
const statusNames = {answered: "有据可答", needs_clarification: "需要补充条件", insufficient_evidence: "证据不足", upstream_error: "知识服务不可用"};
function safeLink(url) {
  const parsed = new URL(url);
  const policy = ["www.flypeach.com", "cs.flypeach.com"].includes(parsed.hostname);
  const code = parsed.hostname === "github.com" && /^\/osTicket\/osTicket\/blob\/[a-f0-9]{40}\//.test(parsed.pathname);
  if (parsed.protocol !== "https:" || parsed.username || parsed.password || !(policy || code)) throw new Error("Invalid source URL");
  return parsed.href;
}
function render(data) {
  $("empty-state").hidden = true;
  const target = $("result"); target.hidden = false; target.replaceChildren();
  const row = node("div", undefined, "status-row");
  row.append(node("span", statusNames[data.status], `status-badge ${data.status}`), node("span", data.status, "status-code"));
  target.append(row, node("p", data.message, "result-message"));
  const codeRoute = data.retrieval_backend === "mcp_stdio" ? " → File Search MCP（stdio）" : " · 本地检索";
  target.append(node("p", data.delegated_to ? `${data.agent} → ${data.delegated_to}${codeRoute}` : `${data.agent || "客服协助代理"} · 政策检索`, "agent-route"));
  if (data.repository) target.append(node("p", `osTicket · 提交 ${data.repository.commit_sha.slice(0, 12)} · ${data.repository.indexed_files} 个已索引文件`, "tiny"));
  if (data.answer) target.append(node("p", data.answer, "answer-text"));
  if (data.clarifying_questions.length) {
    const list = node("ul", undefined, "clarify-list");
    data.clarifying_questions.forEach(text => list.append(node("li", text)));
    target.append(list, node("p", "请修改左侧问题或适用条件后重新提交。", "tiny"));
  }
  if (data.sources.length) {
    target.append(node("div", `证据来源 · ${data.sources.length} 段`, "section-label"));
    data.sources.forEach(source => {
      const card = node("div", undefined, "citation");
      const link = node("a", source.title + " ↗"); link.href = safeLink(source.url); link.target = "_blank"; link.rel = "noopener noreferrer";
      const code = source.evidence_kind === "code_excerpt";
      const evidence = code ? source.evidence.split("\n").map((line, i) => `${source.line_start + i} | ${line}`).join("\n") : source.evidence;
      const details = node("details"); details.append(node("summary", code ? "展开代码证据" : "查看中文证据摘要"), node(code ? "pre" : "p", evidence));
      const provenance = code ? `提交 ${source.commit_sha.slice(0, 12)} · L${source.line_start}–L${source.line_end}` : `核对日期 ${source.reviewed_at} · ${source.chunk_id} · 非原文引用`;
      card.append(link, node("small", source.section), node("small", provenance), details);
      if (code && source.matched_line) {
        const labels = {complete_symbol: "完整声明体（词法识别）", partial_symbol: "部分声明体 · 已达片段预算", line_window: "按行摘取 · 未确认声明边界"};
        card.append(node("small", `${labels[source.context_kind] || labels.line_window} · 命中 L${source.matched_line}${source.symbol_name ? ` · ${source.symbol_name}` : ""}`));
      }
      target.append(card);
    });
  }
  if (data.agent_trace && data.agent_trace.length) {
    const trace = node("details", undefined, "agent-trace"); trace.append(node("summary", "查看代理调用记录"));
    const list = node("ol");
    data.agent_trace.forEach(step => list.append(node("li", `${step.agent} · ${step.action}：${step.detail}`)));
    trace.append(list); target.append(trace);
  }
  target.append(node("p", data.scope, "boundary"));
  $("latency").textContent = `${data.latency_ms} ms · 服务端`;
  $("json-output").textContent = JSON.stringify(data, null, 2);
  if (window.matchMedia("(max-width: 880px)").matches) {
    document.querySelector(".result-card").scrollIntoView({behavior: "smooth", block: "start"});
  }
}
form.addEventListener("submit", async event => {
  event.preventDefault();
  if (!question.value.trim() || question.value.trim().length < 2) {question.setCustomValidity("请输入至少两个字符的问题。"); question.reportValidity(); question.setCustomValidity(""); return;}
  const context = {};
  contextFields.forEach(field => {if ($("task").value !== "code_analysis" && $(field).value) context[field] = $(field).value;});
  const payload = {question: question.value.trim(), context, task: $("task").value};
  if ($("task").value === "code_analysis") {
    payload.repository = "https://github.com/osTicket/osTicket";
    if ($("file_path").value.trim()) payload.file_path = $("file_path").value.trim();
  }
  const button = $("submit"); button.disabled = true; button.textContent = "正在核对证据…";
  document.querySelectorAll("[data-example]").forEach(el => el.disabled = true);
  $("result").setAttribute("aria-busy", "true"); switchView(false);
  $("latency").textContent = "";
  try {
    const response = await fetch("/ask", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload), signal: AbortSignal.timeout(30000)});
    const data = await response.json();
    if (!Object.hasOwn(statusNames, data.status)) throw new Error("Invalid API response");
    render(data);
  } catch (_) {
    $("empty-state").hidden = true; $("result").hidden = false;
    $("result").replaceChildren(node("strong", "未能连接本地服务"), node("p", "请确认 FastAPI 正在运行，再重新提交。此次未取得有效回答。", "result-message"));
    $("json-output").textContent = "未收到有效 API 响应。";
  } finally {
    button.disabled = false; button.textContent = "提交给客服协助代理 ↗";
    document.querySelectorAll("[data-example]").forEach(el => el.disabled = false);
    $("result").setAttribute("aria-busy", "false");
  }
});
async function loadLibrary() {
  try {
    const response = await fetch("/knowledge", {signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error("Unavailable");
    const data = await response.json(); const list = $("library-list"); list.replaceChildren();
    for (const document of data.documents) {
      const row = node("div", undefined, "library-row"); const link = node("a", document.title + " ↗");
      link.href = safeLink(document.url); link.target = "_blank"; link.rel = "noopener noreferrer";
      row.append(link, node("small", `核对日期：${document.reviewed_at} · 官方公开页面`)); list.append(row);
    }
    $("library-version").textContent = `${data.version} · ${data.chunk_count} 段摘要 · ${data.review_window_days} 天复核窗口`;
  } catch (_) { $("library-list").textContent = "资料库暂时无法读取，请确认本地服务正在运行。"; }
}
async function health() {
  try {
    const response = await fetch("/health", {signal: AbortSignal.timeout(10000)});
    const data = await response.json();
    if (!response.ok) throw new Error("Unavailable");
    $("corpus-summary").textContent = `${data.documents} 个官方来源 · ${data.chunks} 段摘要`;
    $("review-date").textContent = `${data.status === "review_required" ? "需重新复核" : "资料核对"} ${data.reviewed_at}`;
  } catch (_) { $("corpus-summary").textContent = "知识库暂不可用"; $("review-date").textContent = "等待服务恢复"; }
}
health();

function updateTask() {
  const code = $("task").value === "code_analysis";
  $("code-context").hidden = !code;
  $("policy-context").hidden = code;
  question.placeholder = code ? "例如：osTicket API 返回 401 时，应该查看哪些代码？" : "例如：Peach 的手提行李有什么重量和件数限制？";
  if (code) repositoryHealth();
}
async function repositoryHealth() {
  try {
    const response = await fetch("/repositories", {signal: AbortSignal.timeout(10000)});
    const data = await response.json();
    if (!response.ok) throw new Error("Unavailable");
    const backend = data.retrieval_backend === "mcp_stdio" ? "File Search MCP 已连接" : "本地检索";
    $("repo-status").textContent = `${backend} · ${data.indexed_files} 个文件 · 提交 ${data.commit_sha.slice(0, 12)}`;
  } catch (_) { $("repo-status").textContent = "索引未就绪，请按代码分析指南建立本地索引。"; }
}
$("task").addEventListener("change", updateTask);
