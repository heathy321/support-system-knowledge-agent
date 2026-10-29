"use strict";
const $ = (id) => document.getElementById(id);
const form = $("ask-form");
const question = $("question");
let clarificationId = null;
let conversationMessages = [];
let replyExpected = false;
let conversationEpoch = 0;
function showConversation() {
  const list = $("conversation-messages"); list.replaceChildren();
  conversationMessages.forEach(message => {
    const item = node("li"); item.append(node("strong", message.role === "user" ? "You: " : "Assistant: "), node("span", message.content)); list.append(item);
  });
  $("conversation-history").hidden = conversationMessages.length === 0;
}
$("new-question").addEventListener("click", async () => {
  const resetEpoch = ++conversationEpoch;
  const oldId = clarificationId;
  clarificationId = null; replyExpected = false; conversationMessages = [];
  showConversation(); question.value = ""; count();
  question.placeholder = "What are you trying to do? Describe the problem and any error message.";
  $("conversation-status").textContent = "Ask a new question.";
  $("result").hidden = true; $("empty-state").hidden = false; $("latency").textContent = "";
  delete document.querySelector(".result-card").dataset.status;
  $("json-output").textContent = "Submit a question to view the raw API response.";
  switchView(false); question.focus();
  $("submit").textContent = "Get answer ↗";
  if (oldId) {
    try {
      const response = await fetch("/conversation/reset", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({clarification_id: oldId}), signal: AbortSignal.timeout(5000)});
      if (!response.ok) throw new Error("Reset failed");
    } catch (_) {
      // The local reference is already gone; no old context will be submitted.
      if (conversationEpoch === resetEpoch) $("conversation-status").textContent = "New question ready. The previous server context will expire automatically.";
    }
  }
});
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function count() {
  $("char-count").textContent = `${question.value.length} / 1500`;
  const meta = document.querySelector(".input-meta");
  meta.style.setProperty("--fill", String(question.value.length / 1500));
  meta.classList.toggle("near-limit", question.value.length > 1350);
}
question.addEventListener("input", count);
question.addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {event.preventDefault(); form.requestSubmit();}
});
// Pointer-tracked highlight on cards (purely visual).
document.querySelectorAll(".card").forEach(card => card.addEventListener("pointermove", event => {
  const box = card.getBoundingClientRect();
  card.style.setProperty("--mx", `${event.clientX - box.left}px`);
  card.style.setProperty("--my", `${event.clientY - box.top}px`);
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
  $("breadcrumb").textContent = library ? "Sources and scope" : "Support System Agent";
  for (const [id, active] of [["nav-ask", !library], ["nav-library", library]]) {
    $(id).classList.toggle("active", active);
    if (active) $(id).setAttribute("aria-current", "page"); else $(id).removeAttribute("aria-current");
  }
}
$("nav-ask").addEventListener("click", () => showWorkspace(false));
$("nav-library").addEventListener("click", () => {showWorkspace(true); loadLibrary(); loadDocumentLibrary();});
const statusNames = {answered: "Answered with evidence", needs_clarification: "Clarification needed", insufficient_evidence: "Insufficient evidence", upstream_error: "Retrieval or generation failed"};
function safeLink(url) {
  const parsed = new URL(url);
  const code = parsed.hostname === "github.com" && /^\/osTicket\/osTicket\/blob\/[a-f0-9]{40}\//.test(parsed.pathname);
  const doc = parsed.hostname === "docs.osticket.com" && parsed.pathname.startsWith("/en/v1.17.7/");
  if (parsed.protocol !== "https:" || parsed.username || parsed.password || !(code || doc)) throw new Error("Invalid source URL");
  return parsed.href;
}
function render(data) {
  $("empty-state").hidden = true;
  const target = $("result"); target.hidden = false; target.replaceChildren();
  const row = node("div", undefined, "status-row");
  const label = {engineering_review: "Additional help needed", checks_available: "Checks you can try", resolved_reported: "Resolved — reported by you"}[data.resolution] || statusNames[data.status];
  row.append(node("span", label, `status-badge ${data.resolution === "engineering_review" ? "needs_clarification" : data.status}`));
  target.append(row);
  const engineering = node("details", undefined, "engineering-details");
  engineering.append(node("summary", "Engineering details and processing information"));
  engineering.append(node("p", `${data.status} · ${data.reason_code}: ${data.message}`, "result-message"));
  const generation = data.generation || {backend: "offline"};
  const intent = data.intent_generation;
  if (intent && intent.backend === "gemini") {
    engineering.append(node("p", `Intent classification · ${intent.model || "Gemini"} · ${intent.status} · ${intent.latency_ms} ms · ${intent.total_tokens ?? "Unreported"} tokens`, "agent-route"));
  }
  const generationNames = {skipped: "Skipped: retrieval is not answerable", completed: "Completed · Human review required", abstained: "The model found insufficient evidence", error: "Failed"};
  engineering.append(node("p", generation.backend === "gemini" ? `Gemini · ${generation.model || "Model configuration unavailable"} · ${generationNames[generation.status] || generation.status}` : "Offline evidence · No model called", "agent-route"));
  if (generation.backend === "gemini" && generation.model) {
    engineering.append(node("p", `Generation ${generation.latency_ms} ms · Input ${generation.input_tokens ?? "Not reported"} / Output ${generation.output_tokens ?? "Not reported"} / Thinking ${generation.thought_tokens ?? "Not reported"} / Total ${generation.total_tokens ?? "Not reported"} tokens (provider reported)`, "tiny"));
  }
  const codeRoute = data.retrieval_backend === "mcp_stdio" ? " → File Search MCP (stdio)" : " · Local retrieval";
  engineering.append(node("p", data.delegated_to ? `${data.agent} → ${data.delegated_to}${codeRoute}` : `${data.agent || "Support System Agent"} · ${data.mode === "documentation" ? "Document retrieval" : data.mode === "routing" ? "Awaiting routing clarification" : "Scope check"}`, "agent-route"));
  if (data.repository) engineering.append(node("p", `osTicket · Commit ${data.repository.commit_sha.slice(0, 12)} · ${data.repository.indexed_files} indexed files`, "tiny"));
  if (data.documentation) engineering.append(node("p", `Docs ${data.documentation.document_version} · ${data.documentation.chunks} summaries · Reviewed ${data.documentation.reviewed_at}`, "tiny"));
  (data.warnings || []).forEach(w => engineering.append(node("p", w, "boundary")));
  (data.branches || []).forEach(b => engineering.append(node("p", `${b.branch === "documentation" ? "Documentation branch" : "Code branch"}: ${statusNames[b.status]} · ${b.reason_code}`, "tiny")));
  if (data.answer) {
    if (["engineering_review", "checks_available"].includes(data.resolution) && generation.status !== "completed") {
      engineering.append(node("p", data.answer, "answer-text"));
    } else target.append(node("p", data.answer, "answer-text"));
  }
  if (data.next_step) target.append(node("p", data.next_step, "next-step"));
  if (data.support_checks?.length) {
    const section = node("section");
    section.append(node("h3", "Read-only checks"), node("p", "Use only settings you are authorized to inspect. These checks do not establish the cause or authorize configuration changes.", "tiny"));
    const checks = node("ol", undefined, "clarify-list");
    data.support_checks.forEach(check => {
      const item = node("li", check.text);
      item.append(node("p", `Evidence: ${check.citation_ids.join(", ")}`, "tiny"));
      checks.append(item);
    });
    section.append(checks); target.append(section);
  }
  if (data.handoff) {
    const handoff = node("section", undefined, "handoff");
    handoff.append(node("h3", "Handoff for additional help"), node("p", "The question, check results, evidence and limitations are bundled below. Add these details before sharing:"));
    const missing = node("ul");
    data.handoff.details_to_add.forEach(item => missing.append(node("li", item)));
    const download = node("button", "Download handoff", "primary"); download.type = "button";
    download.addEventListener("click", () => {
      const url = URL.createObjectURL(new Blob([JSON.stringify(data.handoff, null, 2)], {type: "application/json"}));
      const link = node("a"); link.href = url; link.download = `support-handoff-${data.request_id}.json`;
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    handoff.append(missing, download, node("p", "Prepared locally. Nothing has been sent to an engineer.", "tiny"));
    target.append(handoff);
  }
  if (generation.status === "completed") {
    const links = node("ul", undefined, "tiny");
    (data.claims || []).forEach((claim, i) => links.append(node("li", `Claim ${i + 1} citations: ${claim.citation_ids.join(", ")}`)));
    target.append(links);
  }
  const replyQuestions = [...data.clarifying_questions, ...(data.follow_up_questions || [])];
  if (replyQuestions.length) {
    const list = node("ul", undefined, "clarify-list");
    replyQuestions.forEach(text => list.append(node("li", text)));
    target.append(list, node("p", data.conversation?.state === "awaiting_reply" ? "Type your reply in the question box. Your earlier question will be included." : data.next_step || "Include all relevant details in a new question.", "tiny"));
  }
  if (data.sources.length) {
    target.append(node("div", `Evidence sources · ${data.sources.length} ${data.sources.length === 1 ? "excerpt" : "excerpts"}`, "section-label"));
    data.sources.forEach(source => {
      const card = node("div", undefined, "citation");
      const link = node("a", source.title + " ↗"); link.href = safeLink(source.url); link.target = "_blank"; link.rel = "noopener noreferrer";
      const isCode = source.evidence_kind === "code_excerpt";
      const evidence = isCode ? source.evidence.split("\n").map((line, i) => `${source.line_start + i} | ${line}`).join("\n") : source.evidence;
      const details = node("details"); details.append(node("summary", isCode ? "Expand code evidence" : "Expand document summary (not a verbatim quote)"), node("pre", evidence));
      const provenance = isCode ? `Code · Commit ${source.commit_sha.slice(0, 12)} · L${source.line_start}–L${source.line_end}` : `Official documentation · ${source.document_version} · Reviewed ${source.reviewed_at}`;
      card.append(link, node("small", source.section), node("small", provenance), node("small", `Citation ID: ${source.chunk_id}`), details);
      if (source.matched_line) {
        const labels = {complete_symbol: "Complete declaration (lexical boundaries)", partial_symbol: "Partial declaration · Excerpt budget reached", line_window: "Line window · Declaration boundaries unconfirmed"};
        card.append(node("small", `${labels[source.context_kind] || labels.line_window} · Match at L${source.matched_line}${source.symbol_name ? ` · ${source.symbol_name}` : ""}`));
      }
      target.append(card);
    });
  }
  if (data.agent_trace && data.agent_trace.length) {
    const trace = node("details", undefined, "agent-trace"); trace.append(node("summary", "View agent trace"));
    const list = node("ol");
    data.agent_trace.forEach(step => list.append(node("li", `${step.agent} · ${step.action}: ${step.detail}`)));
    trace.append(list); engineering.append(trace);
  }
  target.append(node("p", data.scope, "boundary"), engineering);
  $("latency").textContent = `${data.latency_ms} ms · Server`;
  $("json-output").textContent = JSON.stringify(data, null, 2);
  [...target.children].forEach((child, index) => child.style.setProperty("--i", String(index)));
  document.querySelector(".result-card").dataset.status = data.resolution === "engineering_review" ? "needs_clarification" : data.status;
  if (window.matchMedia("(max-width: 880px)").matches) {
    document.querySelector(".result-card").scrollIntoView({behavior: "smooth", block: "start"});
  }
}
form.addEventListener("submit", async event => {
  event.preventDefault();
  if (!question.value.trim() || question.value.trim().length < 2) {question.setCustomValidity("Enter a question with at least two characters."); question.reportValidity(); question.setCustomValidity(""); return;}
  const submitted = question.value.trim();
  conversationEpoch++;
  const payload = {question: submitted};
  if (clarificationId) payload.clarification_id = clarificationId;
  else {conversationMessages = []; showConversation();}
  const button = $("submit"); button.disabled = true; button.textContent = "Checking evidence…";
  $("new-question").disabled = true; question.disabled = true;
  $("result").setAttribute("aria-busy", "true"); switchView(false);
  $("latency").textContent = "";
  const resultCard = document.querySelector(".result-card"); resultCard.classList.add("is-busy");
  try {
    const response = await fetch("/ask", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload), signal: AbortSignal.timeout(90000)});
    const data = await response.json();
    if (!Object.hasOwn(statusNames, data.status)) throw new Error("Invalid API response");
    render(data);
    const context = data.conversation || {};
    clarificationId = context.clarification_id || null;
    replyExpected = context.state === "awaiting_reply";
    if (data.status !== "upstream_error" && !["expired", "limit_reached", "retry", "unavailable"].includes(context.state)) {
      conversationMessages.push({role: "user", content: submitted});
      const prompts = [...(data.support_checks || []).map(check => check.text), ...data.clarifying_questions, ...(data.follow_up_questions || [])];
      if (prompts.length) conversationMessages.push({role: "assistant", content: prompts.join("\n")});
      showConversation(); question.value = ""; count();
    }
    question.placeholder = replyExpected ? "Reply with the requested details or check results. You do not need to repeat your question." : "Ask a new question, or enter all relevant details to try again.";
    $("conversation-status").textContent = replyExpected
      ? `Replying to your earlier question · ${context.user_turns} user message(s) · Context expires after 15 minutes of inactivity.`
      : clarificationId ? "Earlier context retained. Retry or edit your reply; no automatic retry was made."
        : context.state === "expired" || context.state === "limit_reached" ? data.next_step
        : "No pending context. Your next question starts a new conversation.";
  } catch (_) {
    $("empty-state").hidden = true; $("result").hidden = false;
    $("result").replaceChildren(node("strong", "Could not reach the local service"), node("p", "Check that FastAPI is running, then resubmit. No valid answer was received.", "result-message"));
    resultCard.dataset.status = "upstream_error";
    $("json-output").textContent = "No valid API response received.";
  } finally {
    button.disabled = false; button.textContent = replyExpected ? "Send reply ↗" : "Get answer ↗";
    $("new-question").disabled = false; question.disabled = false;
    if (replyExpected) question.focus();
    $("result").setAttribute("aria-busy", "false"); resultCard.classList.remove("is-busy");
  }
});
let repositoryRequest = null;
async function loadRepository() {
  if (!repositoryRequest) repositoryRequest = fetch("/repositories", {signal: AbortSignal.timeout(30000)})
    .then(async response => {if (!response.ok) throw new Error("Unavailable"); return response.json();})
    .catch(error => {repositoryRequest = null; throw error;});
  return repositoryRequest;
}
async function loadLibrary() {
  const list = $("library-list"); list.replaceChildren();
  try {
    const data = await loadRepository();
    for (const [label, value] of [["Repository", data.repository], ["Pinned commit", data.commit_sha], ["Indexed files", data.indexed_files], ["Skipped entries", data.skipped_files], ["Index SHA-256", data.index_sha256]]) {
      const row = node("div", undefined, "library-row"); row.append(node("strong", label), node("small", String(value))); list.append(row);
    }
    $("library-version").textContent = `Index created: ${data.indexed_at} · ${data.retrieval_backend}`;
  } catch (_) { list.textContent = "Code service or index unavailable. Check MCP dependencies and the local index."; }
}
async function repositoryHealth() {
  try {
    const data = await loadRepository();
    const backend = data.retrieval_backend === "mcp_stdio" ? "File Search MCP connected" : "Local retrieval";
    $("repo-summary").textContent = `${data.indexed_files} indexed files`;
    $("snapshot-version").textContent = `Commit ${data.commit_sha.slice(0, 12)}`;
    document.body.classList.add("service-online");
  } catch (_) {
    $("repo-summary").textContent = "Code service not ready";
    document.body.classList.add("service-offline");
  }
}
repositoryHealth();

let documentationRequest = null;
function loadDocumentation() {
  if (!documentationRequest) documentationRequest = fetch("/documentation", {signal: AbortSignal.timeout(10000)})
    .then(async r => {if (!r.ok) throw new Error("Unavailable"); return r.json();})
    .catch(error => {documentationRequest = null; throw error;});
  return documentationRequest;
}
async function loadDocumentLibrary() {
  const list = $("docs-list"); list.replaceChildren();
  try {
    const d = await loadDocumentation();
    list.append(node("p", `${d.document_version} · ${d.chunks} reviewed summaries · Reviewed ${d.reviewed_at}`, "tiny"));
    for (const source of d.sources) {
      const row = node("div", undefined, "library-row");
      const link = node("a", source.title + " ↗"); link.href = safeLink(source.url); link.target = "_blank"; link.rel = "noopener noreferrer";
      row.append(link, node("small", `Captured ${source.fetched_at} · Page SHA-256 ${source.source_sha256}`)); list.append(row);
    }
    list.append(node("p", `Corpus ${d.corpus_version} · SHA-256 ${d.corpus_sha256}`, "tiny"));
  } catch (_) { list.textContent = "Document corpus not ready; the code branch remains independently available."; }
}
fetch("/generation", {signal: AbortSignal.timeout(10000)})
  .then(async response => {if (!response.ok) throw new Error("Unavailable"); return response.json();})
  .then(config => {
    $("generation-notice").hidden = !config.available;
    $("generation-status").textContent = config.available
      ? "Answers are synthesized automatically from retrieved evidence."
      : config.status === "llm_not_enabled"
        ? "Answers use reviewed evidence. No model service is enabled."
        : "The answer service needs administrator attention. Evidence retrieval remains available; answer generation may fail.";
  }).catch(() => {$("generation-status").textContent = "Answer service configuration is unavailable.";});
