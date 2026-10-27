const planForm = document.querySelector("#plan-form");
const outcomeForm = document.querySelector("#outcome-form");
const goalInput = document.querySelector("#goal");
const minutesInput = document.querySelector("#minutes");
const minutesOutput = document.querySelector("#minutes-output");
const planButton = document.querySelector("#plan-button");
const planEmpty = document.querySelector("#plan-empty");
const planLoading = document.querySelector("#plan-loading");
const planResult = document.querySelector("#plan-result");
const planError = document.querySelector("#plan-error");
const planDuration = document.querySelector("#plan-duration");
const recallSummary = document.querySelector("#recall-summary");
const planSteps = document.querySelector("#plan-steps");
const evidenceList = document.querySelector("#evidence-list");
const evidenceCount = document.querySelector("#evidence-count");
const outcomeSection = document.querySelector("#outcome-section");
const outcomeButton = document.querySelector("#outcome-button");
const outcomeStatus = document.querySelector("#outcome-status");
const memoryCount = document.querySelector("#memory-count");
const memoryList = document.querySelector("#memory-list");

let lastGoal = "";
let lastMinutes = 30;

minutesInput.addEventListener("input", () => {
  minutesOutput.value = `${minutesInput.value} 分钟`;
});

planForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const goal = goalInput.value.trim();
  const minutes = Number(minutesInput.value);
  if (!goal) {
    showPlanError("请先写下一个具体的学习目标。");
    return;
  }

  setPlanState("loading");
  planButton.disabled = true;
  try {
    const response = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal, minutes }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "生成计划失败，请稍后重试。");
    }
    lastGoal = goal;
    lastMinutes = minutes;
    renderPlan(payload);
    setPlanState("result");
    outcomeSection.hidden = false;
    outcomeStatus.textContent = "";
  } catch (error) {
    showPlanError(error.message || "无法连接学习记忆服务。");
  } finally {
    planButton.disabled = false;
  }
});

outcomeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const reflection = document.querySelector("#reflection").value.trim();
  const completed = document.querySelector("#completed").checked;
  if (!reflection) {
    outcomeStatus.textContent = "请写一句复盘，再保存。";
    return;
  }
  outcomeButton.disabled = true;
  outcomeStatus.textContent = "正在写入 PowerContext";
  try {
    const response = await fetch("/api/outcomes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        goal: lastGoal,
        minutes: lastMinutes,
        reflection,
        completed,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "保存失败。");
    }
    outcomeStatus.textContent = "已保存。下一次计划会再次召回这条复盘。";
    outcomeForm.reset();
    document.querySelector("#completed").checked = true;
    await loadMemories();
  } catch (error) {
    outcomeStatus.textContent = error.message || "保存失败。";
  } finally {
    outcomeButton.disabled = false;
  }
});

function renderPlan(plan) {
  planDuration.textContent = `${plan.duration_minutes} 分钟`;
  recallSummary.textContent = plan.recall_summary;
  planSteps.replaceChildren();
  plan.evidence.length = Math.min(plan.evidence.length, 6);

  plan.steps.forEach((step, index) => {
    const item = document.createElement("li");
    const number = document.createElement("span");
    const text = document.createElement("div");
    number.textContent = String(index + 1).padStart(2, "0");
    text.textContent = step;
    item.append(number, text);
    planSteps.append(item);
  });

  evidenceList.replaceChildren();
  evidenceCount.textContent = `${plan.evidence.length} 条引用`;
  if (plan.evidence.length === 0) {
    const empty = document.createElement("p");
    empty.className = "evidence-item";
    empty.textContent = "没有检索到相关历史记忆。";
    evidenceList.append(empty);
    return;
  }

  plan.evidence.forEach((item) => {
    const wrapper = document.createElement("div");
    const text = document.createElement("p");
    const citation = document.createElement("code");
    wrapper.className = "evidence-item";
    text.textContent = item.text;
    citation.textContent = `${item.citation.artifact_id}@${item.citation.revision}`;
    wrapper.append(text, citation);
    evidenceList.append(wrapper);
  });
}

function setPlanState(state) {
  planEmpty.hidden = state !== "empty";
  planLoading.hidden = state !== "loading";
  planResult.hidden = state !== "result";
  planError.hidden = state !== "error";
}

function showPlanError(message) {
  planError.textContent = message;
  setPlanState("error");
}

async function loadMemories() {
  try {
    const response = await fetch("/api/memories");
    if (!response.ok) {
      throw new Error("读取记忆失败");
    }
    const payload = await response.json();
    memoryCount.textContent = `${payload.entries.length} 条长期记忆`;
    memoryList.replaceChildren();
    payload.entries.forEach((entry) => {
      const row = document.createElement("div");
      const kind = document.createElement("span");
      const text = document.createElement("p");
      const state = document.createElement("span");
      row.className = "memory-row";
      kind.className = "memory-kind";
      text.className = "memory-text";
      state.className = "memory-state";
      kind.textContent = entry.kind;
      text.textContent = entry.text;
      state.textContent = entry.state;
      row.append(kind, text, state);
      memoryList.append(row);
    });
  } catch (error) {
    memoryCount.textContent = "记忆服务不可用";
    memoryList.replaceChildren();
    const row = document.createElement("div");
    row.className = "memory-row";
    row.textContent = error.message;
    memoryList.append(row);
  }
}

loadMemories();

const query = new URLSearchParams(window.location.search);
if (query.get("demo") === "1") {
  goalInput.value = "复习线性代数里的矩阵相似与特征值";
  minutesInput.value = "30";
  minutesOutput.value = "30 分钟";
  planForm.requestSubmit();
}
