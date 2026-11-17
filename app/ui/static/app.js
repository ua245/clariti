const state = { settings: null, reviews: [], activeReview: null, template: null };
let activeBatchId = null;

const statusElement = document.querySelector("#status");
const workspace = document.querySelector("#workspace");
const activeMeta = document.querySelector("#active-review-meta");
const approvalMeta = document.querySelector("#approval-meta");

function csrfToken() {
  const prefix = "clariti_csrf=";
  return document.cookie
    .split("; ")
    .find((value) => value.startsWith(prefix))
    ?.slice(prefix.length);
}

function formatError(detail) {
  if (!detail) return "Request failed.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => item.msg || JSON.stringify(item))
      .join("; ");
  }
  return String(detail);
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
    throw new Error(formatError(data.detail) || `Request failed (${response.status}).`);
  }
  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return response.json();
  return response.text();
}

function setStatus(message, isError = false) {
  statusElement.textContent = message;
  statusElement.dataset.error = isError ? "true" : "false";
}

function element(tag, text) {
  const result = document.createElement(tag);
  result.textContent = text;
  return result;
}

function selectedChecklistIds() {
  return [...document.querySelectorAll('input[name="checklist-item"]:checked')].map(
    (input) => input.value
  );
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
    selectLabel.append(selectItem, document.createTextNode(` ${item.question}`));
    card.append(selectLabel);
    card.append(element("p", `${item.category} · ${item.capture_recipe}`));
    list.append(card);
  }
  document.querySelector("#checklist-json").value = JSON.stringify(template, null, 2);
}

function renderReviews() {
  const select = document.querySelector("#review-select");
  select.replaceChildren(new Option("Select a review", ""));
  for (const review of state.reviews) {
    select.add(
      new Option(`${review.website} (${review.created_at_utc})`, review.review_id)
    );
  }
  if (state.activeReview) select.value = state.activeReview.review_id;
}

function renderEvidence(evidence) {
  const list = document.querySelector("#evidence-list");
  list.replaceChildren();
  if (!evidence.length) {
    list.append(element("p", "No evidence yet."));
    list.lastChild.className = "empty";
    return;
  }
  for (const item of evidence) {
    const card = document.createElement("article");
    card.className = "card";
    card.append(element("strong", `${item.evidence_type}: ${item.evidence_id}`));
    card.append(
      element(
        "p",
        `Captured ${item.captured_at_utc} · ${item.redaction_status}`
      )
    );
    if (item.limitations) {
      card.append(element("p", `Limitations: ${item.limitations}`));
    }
    if (item.text_content !== null) {
      const text = document.createElement("pre");
      text.textContent = item.text_content;
      card.append(text);
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

function renderFindings(review) {
  const list = document.querySelector("#draft-findings");
  list.replaceChildren();
  const findings = review?.effective_findings || [];
  if (!findings.length) {
    list.append(element("p", "Import Companion results to see draft findings."));
    list.lastChild.className = "empty";
    return;
  }
  for (const finding of findings) {
    const card = document.createElement("article");
    card.className = "card";
    const title = document.createElement("strong");
    title.textContent = finding.checklist_id;
    const pill = document.createElement("span");
    pill.className = "status-pill";
    pill.textContent = finding.status;
    title.append(pill);
    card.append(title);
    if (finding.observation) card.append(element("p", finding.observation));
    card.append(element("p", `Reason: ${finding.reason}`));
    card.append(
      element("p", `Evidence: ${(finding.evidence_ids || []).join(", ") || "None"}`)
    );
    if (finding.reviewer_edited) {
      card.append(element("p", "Updated by reviewer edit."));
    }
    list.append(card);
  }
}

function renderEditOptions(review) {
  const select = document.querySelector("#edit-checklist");
  select.replaceChildren();
  for (const checklistId of review.selected_checklist_ids) {
    select.add(new Option(checklistId, checklistId));
  }
  const evidenceField = document.querySelector("#edit-evidence");
  evidenceField.placeholder = review.evidence.map((item) => item.evidence_id).join(", ");
}

function renderApproval(review) {
  if (review.current_approval) {
    approvalMeta.textContent =
      `Signed off by ${review.current_approval.reviewer_name} ` +
      `at revision ${review.current_approval.review_revision} ` +
      `(${review.current_approval.approved_at_utc}).`;
  } else {
    approvalMeta.textContent =
      `Revision ${review.revision}. Sign-off unlocks final exports.`;
  }
}

function showWorkspace(show) {
  workspace.hidden = !show;
  activeMeta.hidden = !show;
}

async function openReview(reviewId) {
  stopHitlPoll();
  setHitlControls(false);
  if (!reviewId) {
    state.activeReview = null;
    activeBatchId = null;
    showWorkspace(false);
    renderChecklist(state.template, null);
    renderEvidence([]);
    renderFindings(null);
    setStatus("Select or create a review to continue.");
    return;
  }
  state.activeReview = await request(`/api/reviews/${encodeURIComponent(reviewId)}`);
  const imported = state.activeReview.latest_companion_import;
  activeBatchId = imported ? imported.batch_id : activeBatchId;
  showWorkspace(true);
  activeMeta.textContent =
    `${state.activeReview.website} · scope: ${state.activeReview.scope} · ` +
    `checklist ${state.activeReview.checklist_version} · revision ${state.activeReview.revision}`;
  renderChecklist(
    state.activeReview.checklist_snapshot,
    state.activeReview.selected_checklist_ids
  );
  renderEvidence(state.activeReview.evidence);
  renderFindings(state.activeReview);
  renderEditOptions(state.activeReview);
  renderApproval(state.activeReview);
  renderReviews();
  setStatus(`Opened review ${state.activeReview.review_id}.`);
}

async function bootstrap() {
  const data = await request("/api/bootstrap");
  state.settings = data.settings;
  state.reviews = data.reviews;
  state.template = data.template;
  document.querySelector("#persistent-notice").textContent = data.notice;
  document.querySelector("#companion-name").value = data.settings.companion_name;
  document.querySelector("#companion-url").value = data.settings.companion_url;
  renderChecklist(
    data.template,
    state.activeReview ? state.activeReview.selected_checklist_ids : null
  );
  renderReviews();
}

function exportReview(formatName, final) {
  if (!state.activeReview) return setStatus("Open a review first.", true);
  const url =
    `/api/reviews/${encodeURIComponent(state.activeReview.review_id)}` +
    `/exports/${formatName}?final=${final ? "true" : "false"}`;
  window.location.assign(url);
}

document.querySelector("#new-review-panel").addEventListener("toggle", (event) => {
  if (!state.template) return;
  if (event.target.open) {
    renderChecklist(state.template, null);
  } else if (state.activeReview) {
    renderChecklist(
      state.activeReview.checklist_snapshot,
      state.activeReview.selected_checklist_ids
    );
  }
});

document.querySelector("#review-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const ids = selectedChecklistIds();
    if (!ids.length) return setStatus("Select at least one checklist item.", true);
    const created = await request("/api/reviews", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        website: document.querySelector("#website").value,
        scope: document.querySelector("#scope").value,
        selected_checklist_ids: ids,
      }),
    });
    document.querySelector("#new-review-panel").open = false;
    await bootstrap();
    await openReview(created.review_id);
    event.target.reset();
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.querySelector("#review-select").addEventListener("change", async (event) => {
  try {
    await openReview(event.target.value);
  } catch (error) {
    setStatus(error.message, true);
  }
});

let hitlPollTimer = null;

function selectedCaptureMode() {
  return document.querySelector('input[name="capture-mode"]:checked')?.value || "sitemap";
}

function setHitlControls(active) {
  document.querySelector("#capture-continue").hidden = !active;
  document.querySelector("#capture-cancel").hidden = !active;
  document.querySelector("#capture-hitl-status").hidden = !active;
  document.querySelector("#capture-website").disabled = active;
}

function stopHitlPoll() {
  if (hitlPollTimer) {
    clearInterval(hitlPollTimer);
    hitlPollTimer = null;
  }
}

function renderHitlStatus(data) {
  const el = document.querySelector("#capture-hitl-status");
  const parts = [
    `HITL status: ${data.status || "unknown"}`,
    data.page_url ? `URL: ${data.page_url}` : null,
    data.hint || null,
    data.error || null,
  ].filter(Boolean);
  el.textContent = parts.join(" · ");
}

async function pollHitlStatus() {
  if (!state.activeReview) return;
  try {
    const data = await request(
      `/api/reviews/${state.activeReview.review_id}/capture/status`
    );
    renderHitlStatus(data);
    if (data.status === "waiting_for_human") {
      setHitlControls(true);
      setStatus(
        data.hint ||
          "Complete Cloudflare/login/consent in the browser window, then click Continue."
      );
    } else if (["completed", "cancelled", "failed", "idle"].includes(data.status)) {
      stopHitlPoll();
      if (data.status !== "waiting_for_human") {
        setHitlControls(false);
      }
      if (data.status === "failed") {
        setStatus(data.error || "HITL capture failed.", true);
      }
    }
  } catch (error) {
    stopHitlPoll();
    setHitlControls(false);
    setStatus(error.message, true);
  }
}

document.querySelector("#capture-website").addEventListener("click", async () => {
  if (!state.activeReview) return setStatus("Open a review first.", true);
  const button = document.querySelector("#capture-website");
  const mode = selectedCaptureMode();
  try {
    button.disabled = true;
    stopHitlPoll();
    if (mode === "hitl" || mode === "sitemap") {
      setStatus(
        mode === "sitemap"
          ? "Opening headed browser for full sitemap scrape…"
          : "Opening headed browser for human-assisted capture…"
      );
      const result = await request(`/api/reviews/${state.activeReview.review_id}/capture`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          confirmed: document.querySelector("#capture-confirmation").checked,
          mode,
        }),
      });
      setHitlControls(true);
      renderHitlStatus(result);
      setStatus(
        result.message ||
          "Complete Cloudflare/login/consent yourself in the browser, then Continue."
      );
      hitlPollTimer = setInterval(pollHitlStatus, 1500);
      return;
    }
    setHitlControls(false);
    setStatus(
      mode === "sitemap_headless"
        ? "Running headless sitemap scrape… this can take several minutes."
        : "Scanning homepage… this can take up to a minute."
    );
    const result = await request(`/api/reviews/${state.activeReview.review_id}/capture`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        confirmed: document.querySelector("#capture-confirmation").checked,
        mode,
      }),
    });
    await openReview(state.activeReview.review_id);
    if (mode === "sitemap_headless") {
      setStatus(
        `Sitemap scrape complete: ${result.sitemap_url_count || 0} URL(s), ` +
          `${result.page_text_count || 0} page text(s), ` +
          `${result.screenshot_count} screenshot(s) from ${result.final_url}.`
      );
    } else {
      setStatus(
        `Scan complete: ${result.screenshot_count} screenshot(s) from ${result.final_url}.`
      );
    }
  } catch (error) {
    setHitlControls(false);
    setStatus(error.message, true);
  } finally {
    if (selectedCaptureMode() !== "hitl" || !hitlPollTimer) {
      button.disabled = false;
    }
  }
});

document.querySelector("#capture-continue").addEventListener("click", async () => {
  if (!state.activeReview) return setStatus("Open a review first.", true);
  const button = document.querySelector("#capture-continue");
  try {
    button.disabled = true;
    setStatus("Resuming scan with your browser session…");
    const result = await request(
      `/api/reviews/${state.activeReview.review_id}/capture/continue`,
      { method: "POST" }
    );
    if (result.status === "waiting_for_human") {
      setHitlControls(true);
      renderHitlStatus(result);
      setStatus(
        result.message ||
          "Another challenge appeared. Complete it in the browser, then Continue again."
      );
      if (!hitlPollTimer) hitlPollTimer = setInterval(pollHitlStatus, 1500);
      return;
    }
    stopHitlPoll();
    setHitlControls(false);
    document.querySelector("#capture-website").disabled = false;
    await openReview(state.activeReview.review_id);
    if (result.mode === "sitemap") {
      setStatus(
        `Headed sitemap scrape complete: ${result.sitemap_url_count || 0} URL(s), ` +
          `${result.page_text_count || 0} page text(s), ` +
          `${result.screenshot_count} screenshot(s) from ${result.final_url}.`
      );
    } else {
      setStatus(
        `HITL scan complete: ${result.screenshot_count} screenshot(s) from ${result.final_url}.`
      );
    }
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#capture-cancel").addEventListener("click", async () => {
  if (!state.activeReview) return setStatus("Open a review first.", true);
  try {
    await request(`/api/reviews/${state.activeReview.review_id}/capture/cancel`, {
      method: "POST",
    });
    stopHitlPoll();
    setHitlControls(false);
    document.querySelector("#capture-website").disabled = false;
    document.querySelector("#capture-hitl-status").hidden = true;
    setStatus("HITL capture cancelled.");
  } catch (error) {
    setStatus(error.message, true);
  }
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
        limitations: document.querySelector("#text-limitations").value,
      }),
    });
    event.target.reset();
    await openReview(state.activeReview.review_id);
    setStatus("Text evidence saved.");
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.querySelector("#screenshot-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.activeReview) return setStatus("Open a review before adding evidence.", true);
  try {
    const form = new FormData();
    form.append("screenshot", document.querySelector("#screenshot").files[0]);
    const source = document.querySelector("#screenshot-source-url").value;
    if (source) form.append("source_url", source);
    form.append("limitations", document.querySelector("#screenshot-limitations").value);
    form.append(
      "reviewed_confirmation",
      document.querySelector("#reviewed-confirmation").checked
    );
    await request(`/api/reviews/${state.activeReview.review_id}/evidence/screenshot`, {
      method: "POST",
      body: form,
    });
    event.target.reset();
    await openReview(state.activeReview.review_id);
    setStatus("Screenshot evidence saved.");
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.querySelector("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    state.settings = await request("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: document.querySelector("#companion-name").value,
        url: document.querySelector("#companion-url").value,
      }),
    });
    setStatus("Companion settings saved.");
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.querySelector("#reset-companion").addEventListener("click", async () => {
  try {
    state.settings = await request("/api/settings/reset", { method: "POST" });
    document.querySelector("#companion-name").value = state.settings.companion_name;
    document.querySelector("#companion-url").value = state.settings.companion_url;
    setStatus("Companion settings reset.");
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.querySelector("#open-companion").addEventListener("click", () => {
  if (!state.settings?.companion_url) {
    return setStatus("Save a valid Companion URL first.", true);
  }
  window.open(state.settings.companion_url, "_blank", "noopener");
});

document.querySelector("#prepare-handoff").addEventListener("click", async () => {
  if (!state.activeReview) return setStatus("Open a review first.", true);
  if (!state.activeReview.evidence.length) {
    return setStatus("Add evidence before preparing a handoff.", true);
  }
  try {
    const result = await request(
      `/api/reviews/${state.activeReview.review_id}/handoffs`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          evidence_ids: state.activeReview.evidence.map((item) => item.evidence_id),
          evidence_review_confirmed:
            document.querySelector("#handoff-confirmation").checked,
        }),
      }
    );
    activeBatchId = result.batch_id;
    document.querySelector("#handoff-prompt").value = result.prompt;
    const shots = result.screenshot_count || 0;
    setStatus(
      shots
        ? `Handoff ready with ${shots} screenshot(s). Download the package and upload screenshots/ with the Companion.`
        : "Handoff ready. Copy the prompt; no screenshots were included."
    );
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.querySelector("#copy-prompt").addEventListener("click", async () => {
  const prompt = document.querySelector("#handoff-prompt").value;
  if (!prompt) return setStatus("Prepare a handoff first.", true);
  try {
    await navigator.clipboard.writeText(prompt);
    setStatus("Prompt copied.");
  } catch {
    setStatus("Clipboard copy failed. Select and copy the prompt manually.", true);
  }
});

document.querySelector("#download-package").addEventListener("click", () => {
  if (!activeBatchId) return setStatus("Prepare a handoff first.", true);
  window.location.assign(`/api/handoffs/${encodeURIComponent(activeBatchId)}/package`);
  setStatus("Downloading handoff zip (prompt + screenshots + text).");
});

document.querySelector("#download-attachments").addEventListener("click", async () => {
  if (!activeBatchId) return setStatus("Prepare a handoff first.", true);
  try {
    const attachments = await request(`/api/handoffs/${activeBatchId}/attachments`);
    let opened = 0;
    for (const item of attachments) {
      if (item.download_url) {
        window.open(item.download_url, "_blank", "noopener");
        opened += 1;
      }
    }
    setStatus(
      opened
        ? "Opened screenshot downloads. Prefer the full package zip for Companion upload."
        : "No screenshot files in this handoff. Copy text evidence from the prompt."
    );
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.querySelector("#import-response").addEventListener("click", async () => {
  if (!activeBatchId) return setStatus("Prepare a handoff before importing results.", true);
  try {
    await request(`/api/handoffs/${activeBatchId}/imports`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        response_text: document.querySelector("#companion-response").value,
      }),
    });
    await openReview(state.activeReview.review_id);
    setStatus("Draft findings imported. Human review remains required.");
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.querySelector("#edit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.activeReview) return setStatus("Open a review first.", true);
  try {
    const evidenceIds = document
      .querySelector("#edit-evidence")
      .value.split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    await request(`/api/reviews/${state.activeReview.review_id}/edits`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        checklist_id: document.querySelector("#edit-checklist").value,
        status: document.querySelector("#edit-status").value,
        notes: document.querySelector("#edit-notes").value,
        reason: document.querySelector("#edit-reason").value,
        evidence_ids: evidenceIds,
      }),
    });
    event.target.reset();
    await openReview(state.activeReview.review_id);
    setStatus("Reviewer edit saved. Previous sign-off no longer applies.");
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.querySelector("#approval-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.activeReview) return setStatus("Open a review first.", true);
  try {
    await request(`/api/reviews/${state.activeReview.review_id}/approvals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reviewer_name: document.querySelector("#reviewer-name").value,
      }),
    });
    await openReview(state.activeReview.review_id);
    setStatus("Sign-off recorded for the current revision.");
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.querySelector("#export-csv").addEventListener("click", () => exportReview("csv", false));
document.querySelector("#export-pdf").addEventListener("click", () => exportReview("pdf", false));
document
  .querySelector("#export-csv-final")
  .addEventListener("click", () => exportReview("csv", true));
document
  .querySelector("#export-pdf-final")
  .addEventListener("click", () => exportReview("pdf", true));

document.querySelector("#save-template").addEventListener("click", async () => {
  try {
    const template = JSON.parse(document.querySelector("#checklist-json").value);
    await request("/api/checklist-templates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(template),
    });
    await bootstrap();
    setStatus(`Checklist ${template.version} saved for new reviews.`);
  } catch (error) {
    setStatus(error.message, true);
  }
});

bootstrap()
  .then(() => setStatus("Ready. Create or open a review."))
  .catch((error) => setStatus(error.message, true));
