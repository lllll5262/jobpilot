const state = {
  agent: "supervisor",
  preferredAgent: null,
  loading: false,
  lastMessage: "",
  context: { userId: 1, jobId: null, resumeId: null, interviewId: null, questionId: null },
  usage: { conversations: 0, resumes: 0, interviews: 0 },
  optimization: { tab: "history", selectedJobId: null, jobs: [] },
  conversations: [],
  activeConversationId: null,
};

const CONVERSATION_STORAGE_KEY = "jobpilot-conversations-v1";
const MAX_LOCAL_CONVERSATIONS = 20;

const agentInfo = {
  supervisor: { name: "Supervisor", title: "JobPilot AI 助手", icon: "✦", color: "green", description: "理解需求、选择专业 Agent，并组合任务结果" },
  job: { name: "Job Analyst", title: "Job Agent", icon: "◇", color: "green", description: "负责解析 JD、岗位匹配和差距分析" },
  resume: { name: "Resume Expert", title: "Resume Agent", icon: "▤", color: "blue", description: "负责简历解析、候选人画像和针对性优化" },
  interview: { name: "Interview Coach", title: "Interview Agent", icon: "◎", color: "orange", description: "负责模拟面试、答案评价与薄弱点追问" },
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const feed = $("#chat-feed");
const input = $("#message-input");

function currentTime() {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date());
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

function conversationTime(updatedAt) {
  const elapsed = Date.now() - Number(updatedAt || 0);
  if (elapsed < 60_000) return "刚刚";
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)} 分钟前`;
  if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)} 小时前`;
  if (elapsed < 172_800_000) return "昨天";
  return `${Math.floor(elapsed / 86_400_000)} 天前`;
}

function renderRecents() {
  const conversations = [...state.conversations].sort((left, right) => right.updatedAt - left.updatedAt);
  $("#recent-list").innerHTML = conversations.map((conversation) => `
    <button class="recent-chat ${conversation.id === state.activeConversationId ? "active" : ""}" type="button" data-conversation-id="${escapeHtml(conversation.id)}">
      <span>›</span><strong>${escapeHtml(conversation.title)}</strong><time>${conversationTime(conversation.updatedAt)}</time>
    </button>`).join("");
}

function activeConversation() {
  return state.conversations.find((conversation) => conversation.id === state.activeConversationId);
}

function persistConversations() {
  const ordered = [...state.conversations]
    .sort((left, right) => right.updatedAt - left.updatedAt)
    .slice(0, MAX_LOCAL_CONVERSATIONS);
  state.conversations = ordered;
  localStorage.setItem(CONVERSATION_STORAGE_KEY, JSON.stringify(ordered));
}

function saveActiveConversation() {
  const conversation = activeConversation();
  if (!conversation) return;
  conversation.messagesHtml = feed.innerHTML;
  conversation.context = { ...state.context };
  conversation.agent = state.agent;
  conversation.preferredAgent = state.preferredAgent;
  conversation.lastMessage = state.lastMessage;
  persistConversations();
}

function touchActiveConversation(title) {
  const conversation = activeConversation();
  if (!conversation) return;
  if (conversation.title === "新对话" && title) {
    conversation.title = title.replace(/\s+/g, " ").trim().slice(0, 36);
  }
  conversation.updatedAt = Date.now();
}

function createConversation() {
  saveActiveConversation();
  const previousContext = state.context;
  const conversation = {
    id: globalThis.crypto?.randomUUID?.() || `conversation-${Date.now()}`,
    title: "新对话",
    updatedAt: Date.now(),
    messagesHtml: "",
    context: {
      userId: previousContext.userId || 1,
      resumeId: previousContext.resumeId || null,
      jobId: null,
      interviewId: null,
      questionId: null,
    },
    agent: "supervisor",
    preferredAgent: null,
    lastMessage: "",
  };
  state.conversations.unshift(conversation);
  state.activeConversationId = conversation.id;
  state.context = { ...conversation.context };
  state.preferredAgent = null;
  state.lastMessage = "";
  setAgent("supervisor");
  welcome();
  conversation.messagesHtml = feed.innerHTML;
  persistConversations();
  localStorage.setItem("jobpilot-context", JSON.stringify(state.context));
  renderRecents();
  input.focus();
}

function openConversation(conversationId) {
  if (state.loading || conversationId === state.activeConversationId) return;
  saveActiveConversation();
  const conversation = state.conversations.find((item) => item.id === conversationId);
  if (!conversation) return;
  state.activeConversationId = conversation.id;
  state.context = {
    userId: 1,
    jobId: null,
    resumeId: null,
    interviewId: null,
    questionId: null,
    ...conversation.context,
  };
  state.preferredAgent = conversation.preferredAgent || null;
  state.lastMessage = conversation.lastMessage || "";
  feed.innerHTML = conversation.messagesHtml || "";
  setAgent(conversation.agent || "supervisor");
  if (!feed.children.length) welcome();
  localStorage.setItem("jobpilot-context", JSON.stringify(state.context));
  renderRecents();
  scrollToBottom();
}

function addUserMessage(text) {
  const article = document.createElement("article");
  article.className = "message user-message";
  article.innerHTML = `<span class="user-avatar">J</span><div class="message-body"><div class="message-meta"><strong>我</strong><time>${currentTime()}</time></div><div class="message-content"><p>${escapeHtml(text).replace(/\n/g, "<br>")}</p></div></div>`;
  feed.append(article);
  scrollToBottom();
}

function addAssistantMessage(content, options = {}) {
  const node = $("#assistant-message-template").content.cloneNode(true);
  const article = node.querySelector("article");
  article.querySelector("time").textContent = currentTime();
  article.querySelector(".message-content").innerHTML = content;
  if (options.loading) article.dataset.loading = "true";
  feed.append(node);
  scrollToBottom();
  return article;
}

function welcome() {
  feed.innerHTML = "";
  addAssistantMessage(`
    <p>你好，我是 JobPilot AI。我会根据你的需求，将任务交给最合适的专业 Agent。</p>
    <p>现在可以帮你完成：</p>
    <ul><li>查看简历与候选人能力画像</li><li>结合目标岗位给出简历优化建议</li><li>根据简历开始无限轮模拟面试</li><li>评价答案、指出错误并针对薄弱点追问</li></ul>
    <p>开始前可点击下方“上下文”，填写岗位 ID 或简历 ID。</p>`);
}

function scrollToBottom() {
  requestAnimationFrame(() => feed.scrollTo({ top: feed.scrollHeight, behavior: "smooth" }));
}

function setLoading(loading) {
  state.loading = loading;
  $("#send-button").disabled = loading;
  input.disabled = loading;
}

function readNumber(id) {
  const raw = $(id).value.trim();
  return raw ? Number(raw) : null;
}

function saveContext() {
  state.context = {
    userId: readNumber("#user-id") || 1,
    jobId: readNumber("#job-id"),
    resumeId: readNumber("#resume-id"),
    interviewId: readNumber("#interview-id"),
    questionId: $("#question-id").value.trim() || null,
  };
  localStorage.setItem("jobpilot-context", JSON.stringify(state.context));
  saveActiveConversation();
  closeContext();
}

function openContext() {
  $("#user-id").value = state.context.userId || 1;
  $("#job-id").value = state.context.jobId || "";
  $("#resume-id").value = state.context.resumeId || "";
  $("#interview-id").value = state.context.interviewId || "";
  $("#question-id").value = state.context.questionId || "";
  $("#context-modal").hidden = false;
  $("#job-id").focus();
}

function closeContext() { $("#context-modal").hidden = true; }

function closeOptimization() { $("#optimization-modal").hidden = true; }

function renderJobPicker() {
  const picker = $("#job-picker");
  if (!state.optimization.jobs.length) {
    picker.innerHTML = '<p class="empty-hint">还没有历史岗位，请切换到“粘贴新 JD”。</p>';
    return;
  }
  picker.innerHTML = state.optimization.jobs.map((record) => `
    <label class="job-option ${record.id === state.optimization.selectedJobId ? "selected" : ""}">
      <input type="radio" name="optimization-job" value="${record.id}" ${record.id === state.optimization.selectedJobId ? "checked" : ""} />
      <span><strong>${escapeHtml(record.job?.job_title || `岗位 ${record.id}`)}</strong><small>岗位 ID：${record.id} · 必备技能：${escapeHtml((record.job?.required_skills || []).slice(0, 5).join("、") || "暂无")}</small></span>
    </label>`).join("");
}

function setOptimizationTab(tab) {
  state.optimization.tab = tab;
  $$('[data-optimization-tab]').forEach((button) => button.classList.toggle("active", button.dataset.optimizationTab === tab));
  $("#optimization-history-panel").hidden = tab !== "history";
  $("#optimization-paste-panel").hidden = tab !== "paste";
}

async function openResumeOptimization() {
  setAgent("resume", true);
  state.optimization.selectedJobId = state.context.jobId;
  $("#optimization-context-hint").textContent = state.context.resumeId
    ? `将使用简历 ID ${state.context.resumeId}；未指定时使用当前 Profile 对应的最新简历。`
    : "将使用当前候选人画像对应的最新简历；如未上传，请先点击附件按钮上传 PDF。";
  $("#optimization-modal").hidden = false;
  setOptimizationTab("history");
  $("#job-picker").innerHTML = '<p class="empty-hint">正在读取历史岗位…</p>';
  try {
    const response = await fetch(`/users/${state.context.userId}/jobs?limit=50&offset=0`);
    state.optimization.jobs = await readApiResponse(response);
    if (!state.optimization.selectedJobId && state.optimization.jobs.length) {
      state.optimization.selectedJobId = state.optimization.jobs[0].id;
    }
    renderJobPicker();
  } catch (error) {
    $("#job-picker").innerHTML = `<p class="empty-hint">历史岗位读取失败：${escapeHtml(error.message)}</p>`;
  }
}

function startResumeOptimization() {
  if (state.optimization.tab === "history") {
    if (!state.optimization.selectedJobId) {
      $("#optimization-context-hint").textContent = "请选择一个历史岗位，或切换到“粘贴新 JD”。";
      return;
    }
    state.context.jobId = state.optimization.selectedJobId;
    localStorage.setItem("jobpilot-context", JSON.stringify(state.context));
    closeOptimization();
    sendMessage("针对这个岗位优化我的简历");
    return;
  }
  const jdText = $("#optimization-jd").value.trim();
  if (jdText.length < 60) {
    $("#optimization-context-hint").textContent = "请粘贴较完整的岗位 JD（至少 60 个字符）。";
    return;
  }
  closeOptimization();
  sendMessage(`请针对以下岗位优化我的简历：\n${jdText}`);
}

function buildPayload(message) {
  const payload = {};
  const lower = message.toLowerCase();
  const looksLikeJd = message.length >= 60 && /(岗位职责|工作职责|任职要求|职位要求|岗位要求|工作内容|技能要求|职位描述|学历|经验|优先|熟悉|掌握)/i.test(message);
  if (looksLikeJd) payload.jd_text = message;
  if (state.context.jobId && /(岗位|面试|优化|jd)/i.test(lower)) payload.job_id = state.context.jobId;
  // 面试服务始终使用当前 Profile 绑定的简历，不接收 resume_id。只有 Resume Agent
  // 请求才附带该字段，避免“根据我的简历开始面试”把跨领域参数传给 Interview Agent。
  if (
    state.context.resumeId &&
    /(简历|画像|profile|优化)/i.test(lower) &&
    !/(面试|interview)/i.test(lower)
  ) payload.resume_id = state.context.resumeId;
  const isInterviewCommand = /(薄弱|查看|开始|创建|生成题|当前题)/i.test(lower);
  const isActiveAnswer = Boolean(
    state.context.interviewId &&
    state.context.questionId &&
    !isInterviewCommand &&
    !/(简历|画像|profile|优化)/i.test(lower)
  );
  if (state.context.interviewId && (isActiveAnswer || /(面试|问题|薄弱|追问)/i.test(lower))) {
    payload.interview_id = state.context.interviewId;
  }
  if (isActiveAnswer) {
    payload.question_id = state.context.questionId;
    payload.answer = message;
  }
  return payload;
}

function buildDispatchMessage(message, payload) {
  if (state.preferredAgent === "job") {
    return payload.jd_text ? message : `请分析以下岗位是否适合我：${message}`;
  }
  if (state.preferredAgent === "resume") {
    return payload.jd_text ? `请针对这个岗位优化简历：${message}` : `请交给 Resume Agent 处理：${message}`;
  }
  if (state.preferredAgent === "interview") {
    if (payload.answer) {
      return `请交给 Interview Agent 评价我对当前问题的回答并继续提问。我的回答：${message}`;
    }
    return payload.jd_text ? `请根据这个岗位开始面试：${message}` : `请交给 Interview Agent 处理：${message}`;
  }
  return message;
}

async function readApiResponse(response) {
  const body = await response.json();
  if (!response.ok || body.code !== 0) {
    const details = body.data?.reason || body.data?.errors?.[0]?.msg;
    throw new Error(details ? `${body.message}：${details}` : (body.message || `请求失败（${response.status}）`));
  }
  return body.data;
}

async function uploadResume(file) {
  if (!file || state.loading) return;
  if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
    addAssistantMessage("<p><strong>文件格式不支持</strong></p><p>请上传可复制文本的 PDF 简历，当前阶段暂不支持图片和 OCR。</p>");
    return;
  }

  addUserMessage(`上传简历：${file.name}`);
  touchActiveConversation(`上传简历：${file.name}`);
  const loadingCard = addAssistantMessage('<p>正在解析并保存简历，然后更新候选人画像…</p><span class="typing-dots"><i></i><i></i><i></i></span>', { loading: true });
  setLoading(true);
  try {
    const formData = new FormData();
    formData.append("file", file);
    const resumeResponse = await fetch(`/users/${state.context.userId}/resumes/parse`, {
      method: "POST",
      body: formData,
    });
    const resume = await readApiResponse(resumeResponse);
    state.context.resumeId = resume.id;
    localStorage.setItem("jobpilot-context", JSON.stringify(state.context));

    let profileMessage = "候选人画像尚未更新。";
    try {
      const profileResponse = await fetch(`/users/${state.context.userId}/profiles/build`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resume_id: resume.id }),
      });
      const profile = await readApiResponse(profileResponse);
      profileMessage = `候选人画像已更新（Profile ID：${profile.id}）。`;
    } catch (profileError) {
      profileMessage = `简历已保存，但更新候选人画像失败：${escapeHtml(profileError.message)}`;
    }

    const parsed = resume.resume || {};
    loadingCard.querySelector(".message-content").innerHTML = `
      <p><strong>简历上传成功：${escapeHtml(resume.filename || file.name)}</strong></p>
      <p>简历 ID：${resume.id}，技能 ${parsed.skills?.length || 0} 项，项目经历 ${parsed.projects?.length || 0} 项，实习经历 ${parsed.internships?.length || 0} 项。</p>
      <p>${profileMessage}</p>`;
    loadingCard.removeAttribute("data-loading");
    state.usage.resumes += 1;
    updateUsage();
    setAgent("resume");
  } catch (error) {
    loadingCard.querySelector(".message-content").innerHTML = `<p><strong>简历上传失败</strong></p><p>${escapeHtml(error.message)}</p>`;
  } finally {
    saveActiveConversation();
    renderRecents();
    setLoading(false);
    $("#resume-file").value = "";
  }
}

function humanizeResult(data) {
  const result = data.result || {};
  if (result.message) {
    return `<p>${escapeHtml(result.message).replace(/\n/g, "<br>")}</p>`;
  }
  if (result.final_answer && result.analysis && result.job) {
    const match = result.analysis.result || {};
    const missing = (match.missing_skills || []).map((skill) => `<li>${escapeHtml(skill)}</li>`).join("");
    return `<p><strong>${escapeHtml(result.job.job?.job_title || "岗位分析")}</strong></p>
      <p>${escapeHtml(result.final_answer).replace(/\n/g, "<br>")}</p>
      <p><strong>匹配分数：${match.match_score ?? "-"} · ${escapeHtml(match.recommendation || "")}</strong></p>
      ${missing ? `<p>待补充技能：</p><ul>${missing}</ul>` : ""}`;
  }
  if (result.current_question) {
    const q = result.current_question;
    return `<p><strong>当前面试题</strong></p><p>${escapeHtml(q.question)}</p><p style="color:#7b8499">考察主题：${escapeHtml(q.topic || "综合能力")}</p>`;
  }
  if (result.next_question || result.evaluation) {
    const evaluation = result.evaluation || {};
    const errors = (evaluation.errors || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    const next = result.next_question;
    return `<p><strong>本轮评价：${evaluation.score ?? "-"} 分 · ${escapeHtml(evaluation.quality || "已评价")}</strong></p>${errors ? `<p>需要改进：</p><ul>${errors}</ul>` : "<p>回答较为完善。</p>"}<p><strong>正确答案</strong></p><p>${escapeHtml(evaluation.correct_answer || "暂无")}</p>${next ? `<p><strong>下一题</strong></p><p>${escapeHtml(next.question)}</p>` : ""}`;
  }
  if (result.rounds && result.current_question) return `<p>${escapeHtml(result.current_question.question)}</p>`;
  if (result.plan || result.job_title) {
    const question = result.current_question || result.rounds?.at(-1)?.question;
    return `<p><strong>${escapeHtml(result.job_title || "面试已创建")}</strong></p><p>面试会话已创建${result.id ? `，ID 为 ${result.id}` : ""}。</p>${question ? `<p><strong>第一题</strong></p><p>${escapeHtml(question.question)}</p>` : ""}`;
  }
  if (result.weak_points) {
    if (!result.weak_points.length) return "<p>当前还没有记录到明显薄弱点，继续完成面试后会自动汇总。</p>";
    return `<p><strong>面试薄弱点</strong></p><ul>${result.weak_points.map((item) => `<li>${escapeHtml(item.topic)}：出现 ${item.occurrences} 次，最近 ${item.latest_score} 分</li>`).join("")}</ul>`;
  }
  if (result.profile) {
    const skills = Object.entries(result.profile.skills || {}).map(([skill, level]) => `${skill}（${level}）`).join("、");
    return `<p><strong>当前候选人画像</strong></p><p>技能：${escapeHtml(skills || "暂无")}</p><p>领域：${escapeHtml((result.profile.domains || []).join("、") || "暂无")}</p>`;
  }
  if (result.resume) {
    return `<p><strong>${escapeHtml(result.filename || "当前简历")}</strong></p><p>技能：${escapeHtml((result.resume.skills || []).join("、") || "暂无")}</p><p>项目经历：${result.resume.projects?.length || 0} 项，教育经历：${result.resume.education?.length || 0} 项。</p>`;
  }
  if (result.suggestions) {
    const suggestions = result.suggestions.map((item, index) => `
      <section class="optimization-suggestion">
        <h4>${index + 1}. ${escapeHtml(item.section)} · ${escapeHtml(item.location)}</h4>
        <p class="original"><strong>原文：</strong>${escapeHtml(item.original_text)}</p>
        <p class="suggested"><strong>建议修改为：</strong>${escapeHtml(item.suggested_text)}</p>
        <p><strong>修改理由：</strong>${escapeHtml(item.reason)}</p>
        <small>覆盖 JD 关键词：${escapeHtml((item.jd_keywords || []).join("、") || "无")}</small>
      </section>`).join("");
    const analyses = (result.project_analysis || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("");
    const issues = (result.issues || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    return `<div class="optimization-result"><p><strong>简历优化建议</strong></p>${analyses ? `<div class="optimization-summary">${analyses}</div>` : ""}${issues ? `<div><strong>问题定位</strong><ul>${issues}</ul></div>` : ""}${suggestions || "<p>当前没有能在不新增事实的前提下安全生成的逐句修改建议。</p>"}<p style="color:#7b8499">${escapeHtml(result.limitation || "")}</p></div>`;
  }
  return `<p>任务已由 <strong>${escapeHtml(data.target_agent || "专业")}</strong> Agent 完成。</p><pre style="white-space:pre-wrap;background:#f7f8fc;padding:12px;border-radius:8px">${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
}

function updateContextFromResponse(data) {
  const result = data.result || {};
  if (result.job?.id) state.context.jobId = result.job.id;
  const session = result.session || result;
  if (session.id && (data.target_agent === "interview" || session.rounds)) state.context.interviewId = session.id;
  const question = result.next_question || session.current_question || session.rounds?.at(-1)?.question;
  if (question?.question_id) state.context.questionId = question.question_id;
  localStorage.setItem("jobpilot-context", JSON.stringify(state.context));
}

async function sendMessage(forcedMessage) {
  const message = (forcedMessage || input.value).trim();
  if (!message || state.loading) return;
  state.lastMessage = message;
  touchActiveConversation(message);
  input.value = "";
  addUserMessage(message);
  const loadingCard = addAssistantMessage('<span class="typing-dots"><i></i><i></i><i></i></span>', { loading: true });
  setLoading(true);
  try {
    const payload = buildPayload(message);
    const response = await fetch(`/users/${state.context.userId}/supervisor`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: buildDispatchMessage(message, payload), payload }),
    });
    const data = await readApiResponse(response);
    loadingCard.querySelector(".message-content").innerHTML = humanizeResult(data);
    loadingCard.removeAttribute("data-loading");
    updateContextFromResponse(data);
    setAgent(data.target_agent || "supervisor");
    state.usage.conversations += 1;
    if (data.target_agent === "resume") state.usage.resumes += 1;
    if (data.target_agent === "interview") state.usage.interviews += 1;
    updateUsage();
  } catch (error) {
    loadingCard.querySelector(".message-content").innerHTML = `<p><strong>暂时无法完成请求</strong></p><p>${escapeHtml(error.message)}</p><p style="color:#7b8499">请检查服务是否启动、上下文 ID 是否填写正确，然后重试。</p>`;
  } finally {
    saveActiveConversation();
    renderRecents();
    setLoading(false);
    input.focus();
  }
}

function updateUsage() {
  $("#conversation-count").textContent = `${state.usage.conversations} / 50`;
  $("#resume-count").textContent = `${state.usage.resumes} / 20`;
  $("#interview-count").textContent = String(state.usage.interviews);
  $$(".usage-item em")[0].style.width = `${Math.min(100, state.usage.conversations * 2)}%`;
  $$(".usage-item em")[1].style.width = `${Math.min(100, state.usage.resumes * 5)}%`;
  $$(".usage-item em")[2].style.width = `${Math.min(100, state.usage.interviews * 5)}%`;
}

function setAgent(agent, userSelected = false) {
  state.agent = agent;
  if (userSelected) state.preferredAgent = agent === "supervisor" ? null : agent;
  const info = agentInfo[agent];
  $("#header-agent-name").textContent = info.title;
  $("#current-agent-name").textContent = info.name;
  $("#current-agent-description").textContent = info.description;
  $("#current-agent-icon").className = `agent-icon ${info.color}`;
  $("#current-agent-icon").textContent = info.icon;
  $("#inline-agent span").textContent = info.name;
  $("#agent-menu").classList.remove("open");
  if (agent === "resume") input.placeholder = "询问简历、Profile 或针对岗位的优化建议";
  else if (agent === "job") input.placeholder = "直接粘贴岗位 JD，我会自动解析并进行匹配分析";
  else if (agent === "interview") input.placeholder = "开始模拟面试，或输入当前问题的回答";
  else input.placeholder = "给 JobPilot 发送消息，或输入 / 选择指令";
}

function bindEvents() {
  $("#send-button").addEventListener("click", () => sendMessage());
  $("#attachment-button").addEventListener("click", () => $("#resume-file").click());
  $("#resume-file").addEventListener("change", (event) => uploadResume(event.target.files[0]));
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); }
  });
  $$("[data-command]").forEach((button) => button.addEventListener("click", () => { input.value = button.dataset.command; input.focus(); }));
  $("#new-chat").addEventListener("click", createConversation);
  $("#recent-list").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-conversation-id]");
    if (button) openConversation(button.dataset.conversationId);
  });
  $("#agent-switch").addEventListener("click", () => $("#agent-menu").classList.toggle("open"));
  $("#side-switch").addEventListener("click", () => $("#agent-menu").classList.toggle("open"));
  $$('[data-agent]').forEach((button) => button.addEventListener("click", () => setAgent(button.dataset.agent, true)));
  $("#theme-toggle").addEventListener("click", () => document.body.classList.toggle("dark"));
  $("#mobile-menu").addEventListener("click", () => $("#sidebar").classList.add("open"));
  $("#collapse-sidebar").addEventListener("click", () => $("#sidebar").classList.remove("open"));
  $("#context-button").addEventListener("click", openContext);
  $("#details-button").addEventListener("click", openContext);
  $("#close-context").addEventListener("click", closeContext);
  $("#cancel-context").addEventListener("click", closeContext);
  $("#save-context").addEventListener("click", saveContext);
  $("#close-optimization").addEventListener("click", closeOptimization);
  $("#cancel-optimization").addEventListener("click", closeOptimization);
  $("#start-optimization").addEventListener("click", startResumeOptimization);
  $("#optimization-modal").addEventListener("click", (event) => { if (event.target.id === "optimization-modal") closeOptimization(); });
  $$('[data-optimization-tab]').forEach((button) => button.addEventListener("click", () => setOptimizationTab(button.dataset.optimizationTab)));
  $("#job-picker").addEventListener("change", (event) => {
    if (event.target.name !== "optimization-job") return;
    state.optimization.selectedJobId = Number(event.target.value);
    renderJobPicker();
  });
  $$('[data-action]').forEach((button) => button.addEventListener("click", () => {
    $$(".nav-item").forEach((item) => item.classList.toggle("active", item === button));
    const action = button.dataset.action;
    if (action === "optimize_resume") openResumeOptimization();
    else if (action === "get_resume") sendMessage("查看我的最新简历");
    else if (action === "create_interview_plan") { setAgent("interview", true); sendMessage("根据我的简历开始模拟面试"); }
    else if (action === "get_weak_points") { setAgent("interview", true); sendMessage("查看我的面试薄弱点"); }
  }));
  $("#context-modal").addEventListener("click", (event) => { if (event.target.id === "context-modal") closeContext(); });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); createConversation(); }
    if (event.key === "Escape") { closeContext(); closeOptimization(); $("#agent-menu").classList.remove("open"); }
  });
  feed.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-tool]");
    if (!button) return;
    if (button.dataset.tool === "retry") sendMessage(state.lastMessage);
    if (button.dataset.tool === "copy") {
      const text = button.closest(".message-body").querySelector(".message-content").innerText;
      await navigator.clipboard.writeText(text);
      button.textContent = "✓ 已复制";
    }
  });
}

function init() {
  const saved = localStorage.getItem("jobpilot-context");
  if (saved) {
    try { state.context = { ...state.context, ...JSON.parse(saved) }; } catch (_) { /* 忽略损坏的本地设置 */ }
  }
  const savedConversations = localStorage.getItem(CONVERSATION_STORAGE_KEY);
  if (savedConversations) {
    try {
      const parsed = JSON.parse(savedConversations);
      if (Array.isArray(parsed)) state.conversations = parsed.filter((item) => item?.id && item?.title);
    } catch (_) { /* 忽略损坏的本地会话记录 */ }
  }
  if (state.conversations.length) {
    state.conversations.sort((left, right) => right.updatedAt - left.updatedAt);
    state.activeConversationId = state.conversations[0].id;
    const conversation = state.conversations[0];
    state.context = { ...state.context, ...conversation.context };
    state.preferredAgent = conversation.preferredAgent || null;
    state.lastMessage = conversation.lastMessage || "";
    feed.innerHTML = conversation.messagesHtml || "";
    setAgent(conversation.agent || "supervisor");
    if (!feed.children.length) welcome();
  } else {
    createConversation();
  }
  renderRecents();
  updateUsage();
  bindEvents();
}

init();
