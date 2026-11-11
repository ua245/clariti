const state = { settings: null, reviews: [], activeReview: null };
let activeBatchId = null;
const statusElement = document.querySelector("#status");

function csrfToken() {
  const prefix = "clariti_csrf=";
  return document.cookie.split("; ").find((value) => value.startsWith(prefix))?.slice(prefix.length);
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = csrfToken();
  if (options.method && options.method !== "GET" && token) {
    headers.set("X-CSRF-Token", token);
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `Request failed (${response.status}).`);
  }
  return response.json();
}

function setStatus(message, isError = false) {
  statusElement.textContent = message;
  statusElement.style.color = isError ? "#b00020" : "#111";
}

function element(tag, text) {
  const result = document.createElement(tag);
  result.textContent = text;
  return result;
}

function renderChecklist(template, selectedIds = null) {
  const list = document.querySelector("#checklist");
  list.replaceChildren();
  for (const item of template.items) {
    const card = document.createElement("article");
    card.className = "card";
    const selectLabel = document.createElement("label");
    selectLabel.className = "checkbox";
    const selectItem = document.createElement("input");
    selectItem.type = "checkbox";
    selectItem.name = "checklist-item";
    selectItem.value = item.id;
    selectItem.checked = selectedIds === null || selectedIds.includes(item.id);
    selectItem.disabled = selectedIds !== null;
    selectLabel.append(selectItem, document.createTextNode(" Include in review"));
    card.append(selectLabel);
    card.append(element("strong", item.question));
    card.append(element("p", `Evidence: ${item.evidence_needed.join(" ")}`));
    card.append(element("p", `Criteria: ${item.assessment_criteria.join(" ")}`));
    list.append(card);
  }
  document.querySelector("#checklist-json").value = JSON.stringify(template, null, 2);
}

function renderReviews() {
  const select = document.querySelector("#review-select");
  select.replaceChildren(new Option("Select a review", ""));
  for (const review of state.reviews) {
    select.add(new Option(`${review.website} (${review.created_at_utc})`, review.review_id));
  }
  if (state.activeReview) select.value = state.activeReview.review_id;
}

function renderEvidence(evidence) {
  const list = document.querySelector("#evidence-list");
  list.replaceChildren();
  for (const item of evidence) {
    const card = document.createElement("article");
    card.className = "card";
    card.append(element("strong", `${item.evidence_type}: ${item.evidence_id}`));
    card.append(element("p", `Captured: ${item.captured_at_utc}; status: ${item.redaction_status}`));
    card.append(element("p", `Limitations: ${item.limitations || "None supplied."}`));
    if (item.text_content !== null) {
      const text = document.createElement("pre");
      text.textContent = item.text_content;
      card.append(text);
    }

    function renderFindings(imported) {
      const list = document.querySelector("#draft-findings");
      list.replaceChildren();
      if (!imported) return;
      for (const finding of imported.findings) {
        const card = document.createElement("article");
        card.className = "card";
        card.append(element("strong", `${finding.checklist_id}: ${finding.status}`));
        card.append(element("p", finding.observation));
        card.append(element("p", `Reason: ${finding.reason}`));
        card.append(element("p", `Evidence: ${finding.evidence_ids.join(", ") || "None"}`));
        list.append(card);
      }
    }
    if (item.evidence_type === "screenshot") {
      const image = document.createElement("img");
      image.src = `/api/evidence/${encodeURIComponent(item.evidence_id)}/artifact`;
      image.alt = `Stored screenshot evidence ${item.evidence_id}`;
      card.append(image);
    }
    list.append(card);
  }
}

async function openReview(reviewId) {
  if (!reviewId) {
    state.activeReview = null;
    await bootstrap();
    renderEvidence([]);
    return;
  }
  state.activeReview = await request(`/api/reviews/${encodeURIComponent(reviewId)}`);
  renderChecklist(
    state.activeReview.checklist_snapshot,
    state.activeReview.selected_checklist_ids
  );
  renderEvidence(state.activeReview.evidence);
  renderFindings(state.activeReview.latest_companion_import);
  renderReviews();
  setStatus(`Opened review ${state.activeReview.review_id}.`);
}

async function bootstrap() {
  const data = await request("/api/bootstrap");
  state.settings = data.settings;
  state.reviews = data.reviews;
  document.querySelector("#persistent-notice").textContent = data.notice;
  document.querySelector("#companion-name").value = data.settings.companion_name;
  document.querySelector("#companion-url").value = data.settings.companion_url;
  renderChecklist(data.template, state.activeReview ? state.activeReview.selected_checklist_ids : null);
  renderReviews();
}

document.querySelector("#review-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const created = await request("/api/reviews", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        website: document.querySelector("#website").value,
        scope: document.querySelector("#scope").value,
        selected_checklist_ids: [...document.querySelectorAll('input[name="checklist-item"]:checked')]
          .map((input) => input.value)
      })
    });
    await bootstrap();
    await openReview(created.review_id);
    event.target.reset();
  } catch (error) { setStatus(error.message, true); }
});

document.querySelector("#review-select").addEventListener("change", async (event) => {
  try { await openReview(event.target.value); } catch (error) { setStatus(error.message, true); }
});

document.querySelector("#text-evidence-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.activeReview) return setStatus("Open a review before adding evidence.", true);
  try {
    await request(`/api/reviews/${state.activeReview.review_id}/evidence/text`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: document.querySelector("#evidence-text").value,
        source_url: document.querySelector("#text-source-url").value || null,
        limitations: document.querySelector("#text-limitations").value
      })
    });
    event.target.reset();
    await openReview(state.activeReview.review_id);
  } catch (error) { setStatus(error.message, true); }
});

document.querySelector("#screenshot-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.activeReview) return setStatus("Open a review before adding evidence.", true);
  try {
    const form = new FormData();
    form.append("screenshot", document.querySelector("#screenshot").files[0]);
    form.append("source_url", document.querySelector("#screenshot-source-url").value);
    form.append("limitations", document.querySelector("#screenshot-limitations").value);
    form.append("reviewed_confirmation", document.querySelector("#reviewed-confirmation").checked);
    await request(`/api/reviews/${state.activeReview.review_id}/evidence/screenshot`, {
      method: "POST", body: form
    });
    event.target.reset();
    await openReview(state.activeReview.review_id);
  } catch (error) { setStatus(error.message, true); }
});

document.querySelector("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    state.settings = await request("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: document.querySelector("#companion-name").value,
        url: document.querySelector("#companion-url").value
      })
    });
    setStatus("Companion configuration saved.");
  } catch (error) { setStatus(error.message, true); }
});

document.querySelector("#reset-companion").addEventListener("click", async () => {
  try {
    state.settings = await request("/api/settings/reset", { method: "POST" });
    document.querySelector("#companion-name").value = state.settings.companion_name;
    document.querySelector("#companion-url").value = state.settings.companion_url;
    setStatus("Companion configuration reset to default.");
  } catch (error) { setStatus(error.message, true); }
});

document.querySelector("#open-companion").addEventListener("click", () => {
  if (!state.settings?.companion_url) return setStatus("Save a valid Companion URL first.", true);
  window.open(state.settings.companion_url, "_blank", "noopener");
});

document.querySelector("#prepare-handoff").addEventListener("click", async () => {
  if (!state.activeReview) return setStatus("Open a review before preparing a handoff.", true);
  try {
    const result = await request(`/api/reviews/${state.activeReview.review_id}/handoffs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        evidence_ids: state.activeReview.evidence.map((item) => item.evidence_id),
        evidence_review_confirmed: document.querySelector("#handoff-confirmation").checked
      })
    });
    activeBatchId = result.batch_id;
    document.querySelector("#handoff-prompt").value = result.prompt;
    setStatus("Manual handoff prepared. Copy prompt and upload reviewed files yourself.");
  } catch (error) { setStatus(error.message, true); }
});

document.querySelector("#copy-prompt").addEventListener("click", async () => {
  const prompt = document.querySelector("#handoff-prompt").value;
  if (!prompt) return setStatus("Prepare a handoff first.", true);
  try {
    await navigator.clipboard.writeText(prompt);
    setStatus("Review prompt copied.");
  } catch { setStatus("Clipboard copy failed. Select and copy the prompt manually.", true); }
});

document.querySelector("#download-attachments").addEventListener("click", async () => {
  if (!activeBatchId) return setStatus("Prepare a handoff first.", true);
  try {
    const attachments = await request(`/api/handoffs/${activeBatchId}/attachments`);
    for (const item of attachments) {
      if (item.download_url) window.open(item.download_url, "_blank", "noopener");
    }
    setStatus("Opened downloadable screenshot files. Copy text evidence from prompt.");
  } catch (error) { setStatus(error.message, true); }
});

document.querySelector("#import-response").addEventListener("click", async () => {
  if (!activeBatchId) return setStatus("Prepare a handoff before importing results.", true);
  try {
    const result = await request(`/api/handoffs/${activeBatchId}/imports`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ response_text: document.querySelector("#companion-response").value })
    });
    renderFindings({ findings: result.findings });
    setStatus("Draft findings imported. Human review remains required.");
  } catch (error) { setStatus(error.message, true); }
});

document.querySelector("#save-template").addEventListener("click", async () => {
  try {
    const template = JSON.parse(document.querySelector("#checklist-json").value);
    await request("/api/checklist-templates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(template)
    });
    await bootstrap();
    setStatus(`Checklist ${template.version} saved for new reviews.`);
  } catch (error) { setStatus(error.message, true); }
});

bootstrap().catch((error) => setStatus(error.message, true));
