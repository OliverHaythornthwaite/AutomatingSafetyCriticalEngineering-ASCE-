const modelSelect = document.getElementById('modelSelect');
const modelsPane = document.getElementById('models');
const healthStatus = document.getElementById('healthStatus');
const reviewStatus = document.getElementById('reviewStatus');
let currentModels = [];
const reviewOutput = document.getElementById('reviewOutput');
const traceabilityPanel = document.getElementById('traceabilityPanel');
const traceabilityOutput = document.getElementById('traceabilityOutput');
const skillSelect = document.getElementById('skillSelect');
const skillDescription = document.getElementById('skillDescription');
const skillFields = document.getElementById('skillFields');
const skillModeRadio = document.getElementById('skillModeRadio');
const customModeRadio = document.getElementById('customModeRadio');
const skillModePanel = document.getElementById('skillModePanel');
const customModePanel = document.getElementById('customModePanel');
const documentStatus = document.getElementById('documentStatus');
const fileInput = document.getElementById('fileInput');
const referenceList = document.getElementById('referenceList');
const addReferenceBtn = document.getElementById('addReferenceBtn');
const removeReferenceBtn = document.getElementById('removeReferenceBtn');
const saveConfigBtn = document.getElementById('saveConfigBtn');
const reviewDocumentList = document.getElementById('reviewDocumentList');
const reviewDocumentStatus = document.getElementById('reviewDocumentStatus');
const reviewFileInput = document.getElementById('reviewFileInput');
const addReviewDocBtn = document.getElementById('addReviewDocBtn');
const removeReviewDocBtn = document.getElementById('removeReviewDocBtn');
const reviewModeToggleBtn = document.getElementById('reviewModeToggleBtn');
const reviewDocFileMode = document.getElementById('reviewDocFileMode');
const reviewDocTextMode = document.getElementById('reviewDocTextMode');
const CONFIG_STORAGE_KEY = 'ascs-reviewer-config';
const reviewDocuments = [];
const referenceEntries = [];
let reviewSkills = [];
let skillAnswerSets = {};
let reviewInputMode = 'files';
let promptMode = 'skill';
let preferredModelName = '';
let preferredSkillId = 'general-review';
let renderedSkillId = '';

function readConfig() {
  try {
    const stored = localStorage.getItem(CONFIG_STORAGE_KEY);
    if (stored) {
      return JSON.parse(stored);
    }
  } catch (error) {
    console.warn('Unable to read saved configuration', error);
  }
  return null;
}

function saveConfig() {
  captureCurrentSkillAnswers();
  const config = {
    selectedModel: modelSelect.value || '',
    promptMode,
    selectedSkillId: skillSelect.value || preferredSkillId,
    skillAnswerSets,
    customPrompt: getCustomPrompt(),
    d0178cContext: document.getElementById('d0178cContext').value,
    reviewDocumentText: document.getElementById('documentText').value,
    reviewInputMode,
  };
  localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(config));
  reviewStatus.textContent = 'Configuration saved.';
}

function applyConfig(config) {
  if (!config) {
    return;
  }
  if (typeof config.d0178cContext === 'string') {
    document.getElementById('d0178cContext').value = config.d0178cContext;
  }
  if (typeof config.reviewDocumentText === 'string') {
    document.getElementById('documentText').value = config.reviewDocumentText;
  }
  if (config.reviewInputMode === 'text' || config.reviewInputMode === 'files') {
    setReviewInputMode(config.reviewInputMode);
  }
  if (typeof config.selectedModel === 'string') {
    preferredModelName = config.selectedModel;
  }
  if (config.promptMode === 'skill' || config.promptMode === 'custom') {
    setPromptMode(config.promptMode);
  }
  if (typeof config.selectedSkillId === 'string') {
    preferredSkillId = config.selectedSkillId;
  }
  if (config.skillAnswerSets && typeof config.skillAnswerSets === 'object' && !Array.isArray(config.skillAnswerSets)) {
    skillAnswerSets = config.skillAnswerSets;
  }
  if (config.customPrompt && typeof config.customPrompt === 'object') {
    setCustomPrompt(config.customPrompt);
  }
}

async function loadSkills() {
  try {
    const data = await fetchJson('/api/skills');
    reviewSkills = Array.isArray(data.skills) ? data.skills : [];
    skillSelect.innerHTML = '';
    reviewSkills.forEach((skill) => {
      const option = document.createElement('option');
      option.value = skill.id;
      option.textContent = skill.name;
      skillSelect.appendChild(option);
    });
    if (!reviewSkills.length) {
      skillDescription.textContent = 'No review skills are installed.';
      return;
    }
    const selected = reviewSkills.some((skill) => skill.id === preferredSkillId)
      ? preferredSkillId
      : reviewSkills[0].id;
    skillSelect.value = selected;
    preferredSkillId = selected;
    renderSelectedSkill();
  } catch (error) {
    skillDescription.textContent = 'Unable to load review skills: ' + error.message;
    skillFields.innerHTML = '';
  }
}

function setPromptMode(mode) {
  promptMode = mode === 'custom' ? 'custom' : 'skill';
  skillModeRadio.checked = promptMode === 'skill';
  customModeRadio.checked = promptMode === 'custom';
  skillModePanel.hidden = promptMode !== 'skill';
  customModePanel.hidden = promptMode !== 'custom';
}

function renderSelectedSkill() {
  const skill = reviewSkills.find((item) => item.id === skillSelect.value);
  skillFields.innerHTML = '';
  if (!skill) {
    skillDescription.textContent = 'Select a review skill.';
    return;
  }
  preferredSkillId = skill.id;
  renderedSkillId = skill.id;
  skillDescription.textContent = skill.description;
  const savedAnswers = skillAnswerSets[skill.id] || {};
  (skill.inputs || []).forEach((field) => {
    const wrapper = document.createElement('div');
    wrapper.className = 'skill-field';
    const label = document.createElement('label');
    label.htmlFor = 'skill-input-' + field.id;
    label.textContent = field.label;
    if (field.required) {
      label.append(' *');
    }

    let input;
    if (field.type === 'select' || field.type === 'multiselect') {
      input = document.createElement('select');
      input.multiple = field.type === 'multiselect';
      if (input.multiple) {
        input.size = Math.min(Math.max((field.options || []).length, 3), 6);
      }
      (field.options || []).forEach((choice) => {
        const option = document.createElement('option');
        option.value = choice.value;
        option.textContent = choice.label;
        input.appendChild(option);
      });
    } else if (field.type === 'textarea') {
      input = document.createElement('textarea');
      input.rows = 3;
    } else {
      input = document.createElement('input');
      input.type = 'text';
    }

    input.id = 'skill-input-' + field.id;
    input.dataset.skillInput = field.id;
    input.required = Boolean(field.required);
    if (field.placeholder) {
      input.placeholder = field.placeholder;
    }
    const value = Object.prototype.hasOwnProperty.call(savedAnswers, field.id) ? savedAnswers[field.id] : field.default;
    if (field.type === 'multiselect') {
      const selectedValues = Array.isArray(value) ? value : [];
      Array.from(input.options).forEach((option) => {
        option.selected = selectedValues.includes(option.value);
      });
    } else if (typeof value === 'string') {
      input.value = value;
    }

    wrapper.appendChild(label);
    wrapper.appendChild(input);
    if (field.help) {
      const help = document.createElement('div');
      help.className = 'field-help';
      help.textContent = field.help;
      wrapper.appendChild(help);
    }
    skillFields.appendChild(wrapper);
  });
}

function captureCurrentSkillAnswers() {
  const skillId = renderedSkillId;
  if (!skillId) {
    return {};
  }
  const answers = {};
  skillFields.querySelectorAll('[data-skill-input]').forEach((input) => {
    answers[input.dataset.skillInput] = input.multiple
      ? Array.from(input.selectedOptions).map((option) => option.value)
      : input.value;
  });
  skillAnswerSets[skillId] = answers;
  return answers;
}

function getCustomPrompt() {
  return {
    reviewer_role: document.getElementById('customReviewerRole').value,
    objective: document.getElementById('customObjective').value,
    review_method: document.getElementById('customReviewMethod').value,
    additional_checks: document.getElementById('customAdditionalChecks').value,
  };
}

function setCustomPrompt(customPrompt) {
  const fields = {
    reviewer_role: 'customReviewerRole',
    objective: 'customObjective',
    review_method: 'customReviewMethod',
    additional_checks: 'customAdditionalChecks',
  };
  Object.entries(fields).forEach(([key, elementId]) => {
    if (typeof customPrompt[key] === 'string') {
      document.getElementById(elementId).value = customPrompt[key];
    }
  });
}

function renderReferenceEntries() {
  referenceList.innerHTML = '';
  if (!referenceEntries.length) {
    const placeholder = document.createElement('option');
    placeholder.textContent = 'No reference documents selected';
    placeholder.disabled = true;
    referenceList.appendChild(placeholder);
    return;
  }
  referenceEntries.forEach((entry, index) => {
    const option = document.createElement('option');
    option.value = String(index);
    option.textContent = entry.name;
    referenceList.appendChild(option);
  });
}

function setReviewInputMode(mode) {
  reviewInputMode = mode === 'text' ? 'text' : 'files';
  reviewDocFileMode.style.display = reviewInputMode === 'files' ? 'block' : 'none';
  reviewDocTextMode.style.display = reviewInputMode === 'text' ? 'block' : 'none';
  reviewModeToggleBtn.textContent = reviewInputMode === 'files' ? 'Switch to text entry' : 'Switch to file selection';
}

function renderReviewDocuments() {
  reviewDocumentList.innerHTML = '';
  if (!reviewDocuments.length) {
    const placeholder = document.createElement('option');
    placeholder.textContent = 'No review documents selected';
    placeholder.disabled = true;
    reviewDocumentList.appendChild(placeholder);
    return;
  }
  reviewDocuments.forEach((entry, index) => {
    const option = document.createElement('option');
    option.value = String(index);
    option.textContent = entry.name;
    reviewDocumentList.appendChild(option);
  });
}

function getSelectedEntryIndex(selectElement, entries) {
  const selectedOption = selectElement.selectedOptions[0];
  const selectedValue = selectedOption?.value ?? '';
  const valueIndex = Number(selectedValue);
  if (Number.isInteger(valueIndex) && valueIndex >= 0 && entries[valueIndex]) {
    return valueIndex;
  }

  const selectedIndex = selectElement.selectedIndex;
  if (selectedIndex >= 0 && entries[selectedIndex]) {
    return selectedIndex;
  }

  return -1;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `Request failed with status ${response.status}.`);
  }
  return data;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function refreshModels(options = {}) {
  const { pollForModel = null, expectedStatus = null, maxAttempts = 1, delayMs = 1200 } = options;
  const selectedModelName = modelSelect.value || preferredModelName;
  modelsPane.textContent = 'Loading…';

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      const data = await fetchJson('/api/models');
      const models = data?.models || [];
      currentModels = models;
      modelSelect.innerHTML = '';
      if (models.length === 0) {
        modelsPane.innerHTML = '<div class="small">No local models detected. Pull one with: ollama pull llama3.2</div>';
        return;
      }
      models.forEach((model) => {
        const option = document.createElement('option');
        option.value = model.name;
        option.textContent = model.name;
        modelSelect.appendChild(option);
      });
      modelsPane.innerHTML = models.map((model) => `
        <div class="model-row">
          <span class="pill ${model.status === 'online' ? '' : 'offline'}">${model.name} · ${model.status}</span>
          <div class="row" style="margin:0;">
            <button class="secondary" style="width:auto; padding:0.35rem 0.6rem; margin-top:0;" data-model="${model.name}" data-action="start">Start</button>
            <button class="secondary" style="width:auto; padding:0.35rem 0.6rem; margin-top:0;" data-model="${model.name}" data-action="ready">Check ready</button>
            <button class="secondary" style="width:auto; padding:0.35rem 0.6rem; margin-top:0;" data-model="${model.name}" data-action="stop">Stop</button>
          </div>
        </div>
      `).join('');
      modelsPane.querySelectorAll('button[data-model]').forEach((button) => {
        button.addEventListener('click', () => {
          const action = button.getAttribute('data-action') || 'start';
          if (action === 'stop') {
            stopModel(button.getAttribute('data-model'));
          } else if (action === 'ready') {
            checkModelReady(button.getAttribute('data-model'));
          } else {
            startModel(button.getAttribute('data-model'));
          }
        });
      });

      const preferredModel = models.find((model) => model.name === selectedModelName) || models.find((model) => model.status === 'online') || models[0];
      if (preferredModel) {
        modelSelect.value = preferredModel.name;
        preferredModelName = preferredModel.name;
      }

      if (pollForModel) {
        const targetModel = models.find((model) => model.name === pollForModel);
        const targetStatus = targetModel?.status || null;
        if (expectedStatus && targetStatus === expectedStatus) {
          return;
        }
        if (!expectedStatus && targetStatus && targetStatus !== 'pending') {
          return;
        }
      } else {
        return;
      }
    } catch (error) {
      modelsPane.textContent = error.message;
      return;
    }

    if (attempt < maxAttempts - 1) {
      await sleep(delayMs);
    }
  }
}

async function checkHealth() {
  try {
    const data = await fetchJson('/api/health');
    healthStatus.textContent = `Ollama endpoint: ${data.ollama_base_url}\nStatus: ${data.status.toUpperCase()}\nModel count: ${data.model_count ?? 'n/a'}`;
    if (data.error) {
      healthStatus.textContent += `\nError: ${data.error}`;
    }
  } catch (error) {
    healthStatus.textContent = `Connection error: ${error.message}`;
  }
}

async function startModel(modelName) {
  if (!modelName) {
    return;
  }
  try {
    healthStatus.textContent = `Loading ${modelName} and checking readiness...`;
    const data = await fetchJson('/api/models/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: modelName }) });
    if (data.error) {
      healthStatus.textContent = `Start failed: ${data.error}`;
      return;
    }
    if (!data.ok) {
      healthStatus.textContent = `Start failed: ${data.error || data.note || 'The model did not become ready.'}`;
      await refreshModels();
      return;
    }
    healthStatus.textContent = `Starting ${modelName}…`;
    await refreshModels({ pollForModel: modelName, expectedStatus: 'online', maxAttempts: 8, delayMs: 1200 });
    const refreshedModel = currentModels.find((model) => model.name === modelName);
    if (refreshedModel?.status === 'online') {
      healthStatus.textContent = data.latency_seconds ? `Ready: ${modelName} responded in ${data.latency_seconds}s.` : `Started ${modelName}`;
    } else {
      healthStatus.textContent = `Start requested for ${modelName}. The model may still be loading.`;
    }
  } catch (error) {
    healthStatus.textContent = `Start failed: ${error.message}`;
  }
}

async function checkModelReady(modelName) {
  if (!modelName) {
    return;
  }
  try {
    healthStatus.textContent = `Checking whether ${modelName} can respond...`;
    const data = await fetchJson('/api/models/ready', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: modelName }) });
    await refreshModels();
    if (data.error) {
      if (String(data.error).toLowerCase() === 'not found') {
        healthStatus.textContent = 'Ready check endpoint is unavailable. Restart the ASCS Reviewer server.';
        return;
      }
      healthStatus.textContent = `Ready check failed: ${data.error}`;
      return;
    }
    if (data.ready || data.status === 'ready') {
      healthStatus.textContent = data.latency_seconds ? `Ready: ${modelName} responded in ${data.latency_seconds}s.` : `Ready: ${modelName} responded.`;
      return;
    }
    healthStatus.textContent = `Not ready: ${data.error || data.reason || 'The model did not answer the readiness probe.'}`;
  } catch (error) {
    healthStatus.textContent = `Ready check failed: ${error.message}`;
  }
}

async function stopModel(modelName) {
  if (!modelName) {
    return;
  }
  try {
    const data = await fetchJson('/api/models/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: modelName }) });
    if (data.error) {
      healthStatus.textContent = `Stop failed: ${data.error}`;
      return;
    }
    if (data.status === 'not-running') {
      healthStatus.textContent = `${modelName} is already not running.`;
      await refreshModels();
      return;
    }
    healthStatus.textContent = `Stopping ${modelName}…`;
    await refreshModels({ pollForModel: modelName, expectedStatus: 'offline', maxAttempts: 8, delayMs: 1200 });
    const refreshedModel = currentModels.find((model) => model.name === modelName);
    if (refreshedModel?.status === 'offline') {
      healthStatus.textContent = `Stopped ${modelName}`;
    } else {
      healthStatus.textContent = `Stop requested for ${modelName}. The model list will refresh again shortly.`;
    }
  } catch (error) {
    healthStatus.textContent = `Stop failed: ${error.message}`;
  }
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = '';
  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

function readFileAsDocument(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const buffer = reader.result;
      const isTextLike = file.type.startsWith('text/') || /\.(txt|md|rtf|json|csv|tsv|log|ya?ml|xml|html?|toml|ini|cfg|conf|rst|py|c|h|cc|hh|cpp|hpp|cxx|hxx|js|jsx|ts|tsx|java|cs|sql|sh|bat|ps1|m|mm|s|asm)$/i.test(file.name);
      const document = {
        name: file.name,
        data_base64: arrayBufferToBase64(buffer),
        mime_type: file.type || '',
        path: '',
      };
      if (isTextLike) {
        document.content = new TextDecoder('utf-8', { fatal: false }).decode(buffer);
      }
      resolve(document);
    };
    reader.onerror = () => reject(new Error(`Unable to read ${file.name}`));
    reader.readAsArrayBuffer(file);
  });
}

async function handleFileSelection(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length) {
    documentStatus.textContent = 'No files selected.';
    return;
  }
  try {
    const docs = await Promise.all(files.map(readFileAsDocument));
    const addedEntries = docs.filter((doc) => !referenceEntries.some((entry) => entry.name === doc.name));
    addedEntries.forEach((doc) => {
      referenceEntries.push(doc);
    });
    renderReferenceEntries();
    documentStatus.textContent = `Added ${addedEntries.length} file(s) to the reference list.`;
  } catch (error) {
    documentStatus.textContent = error.message;
  } finally {
    event.target.value = '';
  }
}

async function handleReviewDocumentSelection(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length) {
    reviewDocumentStatus.textContent = 'No review documents selected.';
    return;
  }
  try {
    const docs = await Promise.all(files.map(readFileAsDocument));
    const addedEntries = docs.filter((doc) => !reviewDocuments.some((entry) => entry.name === doc.name));
    addedEntries.forEach((doc) => {
      reviewDocuments.push(doc);
    });
    renderReviewDocuments();
    reviewDocumentStatus.textContent = `Added ${addedEntries.length} review document file(s).`;
  } catch (error) {
    reviewDocumentStatus.textContent = error.message;
  } finally {
    event.target.value = '';
  }
}

function removeSelectedReference() {
  const selectedIndex = getSelectedEntryIndex(referenceList, referenceEntries);
  if (selectedIndex < 0) {
    documentStatus.textContent = 'Select an entry to remove.';
    return;
  }
  const removedEntry = referenceEntries.splice(selectedIndex, 1)[0];
  renderReferenceEntries();
  documentStatus.textContent = `Removed ${removedEntry?.name || 'reference entry'}.`;
}

function removeSelectedReviewDocument() {
  const selectedIndex = getSelectedEntryIndex(reviewDocumentList, reviewDocuments);
  if (selectedIndex < 0) {
    reviewDocumentStatus.textContent = 'Select a review document to remove.';
    return;
  }
  const removedEntry = reviewDocuments.splice(selectedIndex, 1)[0];
  renderReviewDocuments();
  reviewDocumentStatus.textContent = `Removed ${removedEntry?.name || 'review document'}.`;
}

function buildReviewPayload() {
  const payload = {
    model: modelSelect.value,
    prompt_mode: promptMode,
    document_text: document.getElementById('documentText').value,
    d0178c_context: document.getElementById('d0178cContext').value,
    reference_documents: referenceEntries.filter((entry) => entry.content || entry.data_base64),
  };
  if (promptMode === 'custom') {
    payload.custom_prompt = getCustomPrompt();
  } else {
    payload.skill_id = skillSelect.value || preferredSkillId;
    payload.skill_answers = captureCurrentSkillAnswers();
  }
  if (reviewInputMode === 'files' && reviewDocuments.length) {
    payload.documents = reviewDocuments;
    payload.document_text = '';
  }
  return payload;
}

async function runReview() {
  reviewStatus.textContent = 'Reviewing with high effort. Large local models can take several minutes...';
  reviewOutput.textContent = 'Generating complete-document review...';
  try {
    const payload = buildReviewPayload();
    const data = await fetchJson('/api/reviewer/review', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (data.error) {
      reviewStatus.textContent = `Review failed: ${data.error}`;
      reviewOutput.textContent = `Review failed: ${data.error}`;
      return;
    }
    const reviewResult = data.review_result || { summary: data.review || 'No review generated.', sections: [], atomic_comments: [] };
    window.latestReviewResult = reviewResult;
    const reviewMethod = data.skill_name ? ` using ${data.skill_name}` : '';
    reviewStatus.textContent = `Review completed with ${data.model}${reviewMethod} across ${data.source_count || 0} source document(s)`;
    renderReviewOutput(reviewResult);
  } catch (error) {
    reviewStatus.textContent = error.message;
    reviewOutput.textContent = error.message;
  }
}

async function runTraceabilityAnalysis() {
  traceabilityPanel.style.display = 'flex';
  traceabilityOutput.textContent = 'Building traceability analysis...';
  reviewStatus.textContent = 'Building traceability analysis.';
  try {
    const data = await fetchJson('/api/traceability/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildReviewPayload()) });
    if (data.error) {
      traceabilityOutput.textContent = `Traceability analysis failed: ${data.error}`;
      reviewStatus.textContent = `Traceability analysis failed: ${data.error}`;
      return;
    }
    window.latestTraceabilityAnalysis = data;
    renderTraceabilityAnalysis(data);
    reviewStatus.textContent = `Traceability analysis completed with ${data.summary?.requirement_count || 0} requirement(s).`;
    traceabilityPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    traceabilityOutput.textContent = `Traceability analysis failed: ${error.message}`;
    reviewStatus.textContent = `Traceability analysis failed: ${error.message}`;
  }
}

function renderTraceabilityAnalysis(data) {
  const artefacts = data?.artefacts || [];
  const forward = data?.forward || [];
  const reverse = data?.reverse || [];
  const unresolved = data?.unresolved_mentions || [];
  const ambiguous = data?.ambiguous_references || [];
  const duplicates = data?.duplicate_ids || [];
  const coverageByType = data?.coverage_by_type || [];
  const gaps = data?.gaps || [];
  const integrityIssues = data?.integrity_issues || [];
  const matrix = data?.matrix || [];
  const summary = data?.summary || {};
  const html = [];

  html.push(`<div class="trace-summary">
    <span class="trace-metric"><b>${escapeHtml(summary.coverage_percent ?? 0)}%</b> linked</span>
    <span class="trace-metric"><b>${escapeHtml(summary.requirement_count || 0)}</b> requirements</span>
    <span class="trace-metric"><b>${escapeHtml(summary.complete_requirement_count || 0)}</b> complete</span>
    <span class="trace-metric trace-metric-warning"><b>${escapeHtml(summary.gap_count || 0)}</b> gaps</span>
    <span class="trace-metric trace-metric-error"><b>${escapeHtml(summary.unresolved_reference_count || 0)}</b> unresolved</span>
    <span class="trace-metric trace-metric-error"><b>${escapeHtml(summary.duplicate_id_count || 0)}</b> duplicate IDs</span>
  </div>`);

  html.push('<h3>Coverage by lifecycle level</h3>');
  if (!coverageByType.length) {
    html.push('<div class="muted">No classified requirements were available for coverage analysis.</div>');
  } else {
    html.push('<div class="trace-table-wrap"><table class="trace-table"><thead><tr><th>Level</th><th>Requirements</th><th>Linked</th><th>Complete</th><th>Coverage</th></tr></thead><tbody>');
    coverageByType.forEach((item) => {
      html.push(`<tr><td>${escapeHtml(item.artefact_type)}</td><td>${escapeHtml(item.requirement_count)}</td><td>${escapeHtml(item.linked_count)}</td><td>${escapeHtml(item.complete_count)}</td><td>${escapeHtml(item.coverage_percent)}%</td></tr>`);
    });
    html.push('</tbody></table></div>');
  }

  if (gaps.length || integrityIssues.length) {
    html.push('<h3>Traceability findings</h3><div class="trace-issue-list">');
    gaps.forEach((gap) => {
      html.push(`<div class="trace-issue trace-issue-warning"><strong>${escapeHtml(gap.requirement_id)}</strong> <span>${escapeHtml(gap.kind)}</span><div>${escapeHtml(gap.message)} ${escapeHtml(gap.document)}</div></div>`);
    });
    integrityIssues.forEach((issue) => {
      html.push(`<div class="trace-issue trace-issue-${escapeHtml(issue.severity || 'warning')}"><strong>${escapeHtml(issue.kind)}</strong><div>${escapeHtml(issue.message)}</div></div>`);
    });
    html.push('</div>');
  }

  html.push('<h3>Traceability matrix</h3>');
  if (!matrix.length) {
    html.push('<div class="muted">No resolved requirement relationships were detected.</div>');
  } else {
    html.push('<div class="trace-table-wrap"><table class="trace-table trace-matrix"><thead><tr><th>Upstream</th><th>Level</th><th>Downstream</th><th>Level</th><th>Link</th></tr></thead><tbody>');
    matrix.forEach((link) => {
      html.push(`<tr><td title="${escapeHtml(link.source_document)}">${escapeHtml(link.source)}</td><td>${escapeHtml(link.source_type)}</td><td title="${escapeHtml(link.target_document)}">${escapeHtml(link.target)}</td><td>${escapeHtml(link.target_type)}</td><td>${escapeHtml(link.relationship_kind)}</td></tr>`);
    });
    html.push('</tbody></table></div>');
  }

  html.push('<h3>Requirements by artefact</h3>');
  if (!artefacts.length) {
    html.push('<div class="muted">No artefacts were available for analysis.</div>');
  }
  artefacts.forEach((artefact) => {
    html.push(`<div class="trace-artefact"><div><strong>${escapeHtml(artefact.name)}</strong> <span class="pill secondary">${escapeHtml(artefact.role)}</span> <span class="pill secondary">${escapeHtml(artefact.artefact_type)}</span></div>`);
    const requirements = artefact.requirements || [];
    if (!requirements.length) {
      html.push('<div class="muted">No requirement IDs detected.</div></div>');
      return;
    }
    html.push('<div class="trace-table-wrap"><table class="trace-table"><thead><tr><th>ID</th><th>Status</th><th>Up</th><th>Down</th><th>Content</th><th>Mentions</th></tr></thead><tbody>');
    requirements.forEach((requirement) => {
      const status = requirement.trace_status || 'unlinked';
      html.push(`<tr><td>${escapeHtml(requirement.id)}</td><td><span class="trace-status trace-status-${escapeHtml(status)}">${escapeHtml(status)}</span></td><td>${escapeHtml(requirement.upstream_link_count || 0)}</td><td>${escapeHtml(requirement.downstream_link_count || 0)}</td><td>${escapeHtml(requirement.content)}</td><td>${escapeHtml((requirement.mentions || []).join(', ') || '-')}</td></tr>`);
    });
    html.push('</tbody></table></div></div>');
  });

  html.push(`<details class="trace-details"><summary>Forward and reverse link lists</summary>${renderTraceLinks('Forward trace SRATS -> HLR -> LLR -> LLRV', forward)}${renderTraceLinks('Reverse trace LLRV -> LLR -> HLR -> SRATS', reverse)}</details>`);
  if (unresolved.length) {
    html.push('<h3>Unresolved mentions</h3><pre class="trace-copy-block">');
    html.push(escapeHtml(unresolved.map((item) => `${item.source_id} (${item.source_document}) mentions ${item.mentioned_id}`).join('\n')));
    html.push('</pre>');
  }
  if (ambiguous.length) {
    html.push('<h3>Ambiguous mentions</h3><pre class="trace-copy-block">');
    html.push(escapeHtml(ambiguous.map((item) => `${item.source_id} (${item.source_document}) mentions ${item.mentioned_id}, which has ${item.candidate_uids.length} definitions`).join('\n')));
    html.push('</pre>');
  }
  if (duplicates.length) {
    html.push('<h3>Duplicate requirement definitions</h3><pre class="trace-copy-block">');
    html.push(escapeHtml(duplicates.map((item) => `${item.id}: ${item.occurrences.map((entry) => `${entry.document} block ${entry.source_block}`).join('; ')}`).join('\n')));
    html.push('</pre>');
  }
  traceabilityOutput.innerHTML = html.join('');
}

function renderTraceLinks(title, links) {
  if (!links.length) {
    return `<h3>${escapeHtml(title)}</h3><div class="muted">No explicit requirement ID links detected.</div>`;
  }
  const lines = links.map((link) => `${link.source_id} [${link.source_type}] (${link.source_document}) -> ${link.target_id} [${link.target_type}] (${link.target_document}) {${link.relationship_kind || 'link'}}`);
  return `<h3>${escapeHtml(title)}</h3><pre class="trace-copy-block">${escapeHtml(lines.join('\n'))}</pre>`;
}

function buildReviewText(reviewResult) {
  const sections = (reviewResult?.sections || []).map((section) => `## ${section.title}\n${normalizeIndentedIssues(section.content || '')}`).join('\n\n');
  const comments = (reviewResult?.atomic_comments || []).map((comment) => {
    const rule = comment.violated_rule || 'Not found in provided reference material';
    const ruleEvidence = comment.rule_evidence ? `\n  Rule evidence: ${comment.rule_evidence}` : '';
    return `- ${comment.id}: ${comment.issue}\n  Location: ${stripPageFromLocation(comment.location || 'Not specified')}\n  Rule violated: ${rule}${ruleEvidence}\n  ${comment.comment}\n  Suggested resolution: ${comment.suggested_resolution || 'N/A'}`;
  }).join('\n\n');
  return [
    `Summary\n${reviewResult?.summary || 'No summary available.'}`,
    sections || 'No sectional review output available.',
    comments ? `Atomic comments\n${comments}` : 'Atomic comments\nNone.'
  ].filter(Boolean).join('\n\n');
}

function normalizeIndentedIssues(content) {
  const lines = String(content || '').split(/\r?\n/);
  let insideIssue = false;
  return lines.map((line) => {
    const trimmed = line.trim();
    if (!trimmed) {
      insideIssue = false;
      return '';
    }
    if (/^(?:[-*]\s*)?Location:/i.test(trimmed)) {
      insideIssue = true;
      return `  ${stripPageFromLocation(trimmed.replace(/^[-*]\s*/, ''))}`;
    }
    if (insideIssue) {
      return `    ${trimmed}`;
    }
    return line;
  }).join('\n');
}

function splitSectionIssueBlocks(content) {
  const text = normalizeIndentedIssues(content || '');
  const matches = Array.from(text.matchAll(/(^|\n)\s*(?:(?:[-*]|\d+[\).])\s*)?Location:/gi));
  if (!matches.length) {
    return { intro: text.trim(), issues: [] };
  }

  const intro = text.slice(0, matches[0].index).trim();
  const issues = matches.map((match, index) => {
    const start = match.index + match[1].length;
    const end = index + 1 < matches.length ? matches[index + 1].index : text.length;
    return text.slice(start, end).trim();
  }).filter(Boolean);
  return { intro, issues };
}

function renderSectionContent(content) {
  const parsed = splitSectionIssueBlocks(content || '');
  const parts = [];
  if (parsed.intro) {
    parts.push(`<div class="review-section-content">${escapeHtml(parsed.intro)}</div>`);
  }
  parsed.issues.forEach((issue) => {
    parts.push(renderFindingBlock(issue));
  });
  if (!parts.length) {
    parts.push('<div class="review-section-content">No content.</div>');
  }
  return parts.join('');
}

function parseIssueFields(block) {
  const fields = {};
  String(block || '').split(/\r?\n/).forEach((line) => {
    const match = line.trim().match(/^(Location|Rule violated|Rule evidence|Issue|Evidence|Target fix):\s*(.*)$/i);
    if (match) {
      const key = match[1].toLowerCase().replace(/\s+/g, '_');
      fields[key] = fields[key] ? `${fields[key]} ${match[2].trim()}` : match[2].trim();
    } else if (line.trim() && fields.evidence) {
      fields.evidence += ` ${line.trim()}`;
    }
  });
  return fields;
}

function renderFindingBlock(block) {
  const fields = parseIssueFields(block);
  if (!fields.issue && !fields.location) {
    return `<pre class="review-issue-block">${escapeHtml(block)}</pre>`;
  }
  return renderFindingCard(fields);
}

function renderFindingCard(fields) {
  return `
    <article class="finding-card">
      <div class="finding-card-head">
        <strong>${escapeHtml(fields.issue || 'Issue')}</strong>
        <span class="finding-location">${escapeHtml(stripPageFromLocation(fields.location || 'Not specified'))}</span>
      </div>
      <div class="finding-meta">
        <span><b>Rules</b> ${escapeHtml(fields.rule_violated || 'Not specified')}</span>
        ${fields.rule_evidence ? `<span><b>Rule basis</b> ${escapeHtml(fields.rule_evidence)}</span>` : ''}
      </div>
      ${fields.evidence ? `<p class="finding-evidence">${escapeHtml(fields.evidence.replace(/^Evidence:\s*/i, ''))}</p>` : ''}
      ${fields.target_fix ? `<div class="finding-fix"><b>Fix</b> ${escapeHtml(fields.target_fix)}</div>` : ''}
    </article>
  `;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function stripPageFromLocation(value) {
  return String(value || '')
    .replace(/\bpage\s+(?:not available in source|\d+(?:\s*\([^)]*\))?)\s*,?\s*/gi, '')
    .replace(/\|\s*page\s+(?:not available in source|\d+(?:\s*\([^)]*\))?)\s*\|?/gi, '|')
    .replace(/\s*\|\s*/g, ' | ')
    .replace(/^\|\s*|\s*\|$/g, '')
    .replace(/\s+,/g, ',')
    .replace(/^[\s,-]+|[\s,-]+$/g, '');
}

function hasReviewResult(reviewResult) {
  return Boolean(
    reviewResult &&
    (
      reviewResult.summary ||
      (Array.isArray(reviewResult.sections) && reviewResult.sections.length) ||
      (Array.isArray(reviewResult.atomic_comments) && reviewResult.atomic_comments.length)
    )
  );
}

function buildExportFileName() {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const modelName = (modelSelect.value || 'model').replace(/[^a-z0-9._-]+/gi, '-').replace(/^-+|-+$/g, '') || 'model';
  return `review-output-${modelName}-${timestamp}.txt`;
}

function renderReviewOutput(reviewResult) {
  const sections = reviewResult?.sections || [];
  const comments = reviewResult?.atomic_comments || [];
  if (!sections.length && !comments.length) {
    reviewOutput.innerHTML = `<div class="small">${reviewResult?.summary || 'No review output available.'}</div>`;
    return;
  }

  const html = [];
  html.push(`<div class="small" style="margin-bottom:0.6rem;"><strong>Summary:</strong> ${escapeHtml(reviewResult?.summary || 'No summary available.')}</div>`);
  sections.forEach((section) => {
    html.push(`<section class="review-section-box"><h3>${escapeHtml(section.title)}</h3>${renderSectionContent(section.content || 'No content.')}</section>`);
  });
  if (comments.length) {
    html.push(`<section class="review-section-box atomic-comments-box"><h3>Atomic comments</h3><div class="atomic-comment-list">${comments.map((comment) => {
      const rule = comment.violated_rule || 'Not found in provided reference material';
      return renderFindingCard({
        issue: `${comment.id}: ${comment.issue}`,
        location: comment.location || 'Not specified',
        rule_violated: rule,
        rule_evidence: comment.rule_evidence || '',
        evidence: comment.comment || 'N/A',
        target_fix: comment.suggested_resolution || 'N/A',
      });
    }).join('')}</div></section>`);
  }
  reviewOutput.innerHTML = html.join('');
}

async function exportReview(contentOverride = null) {
  const latestReviewResult = window.latestReviewResult || null;
  if (!contentOverride && !hasReviewResult(latestReviewResult)) {
    reviewStatus.textContent = 'Run a review before exporting a text file.';
    return;
  }

  const content = contentOverride || buildReviewText(latestReviewResult);
  const defaultName = buildExportFileName();

  if ('showSaveFilePicker' in window) {
    try {
      const handle = await window.showSaveFilePicker({
        suggestedName: defaultName,
        types: [{ description: 'Text files', accept: { 'text/plain': ['.txt'] } }],
      });
      const writable = await handle.createWritable();
      await writable.write(content);
      await writable.close();
      reviewStatus.textContent = `Review exported to ${handle.name}`;
      return;
    } catch (error) {
      if (error && error.name === 'AbortError') {
        reviewStatus.textContent = 'Export cancelled.';
        return;
      }
      console.warn('Unable to use save picker', error);
    }
  }

  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = defaultName;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  reviewStatus.textContent = `Review exported to ${defaultName}`;
}

function exportTraceabilityAnalysis() {
  const analysis = window.latestTraceabilityAnalysis || null;
  if (!analysis) {
    reviewStatus.textContent = 'Run traceability analysis before exporting JSON.';
    return;
  }

  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const defaultName = `traceability-analysis-${timestamp}.json`;
  const blob = new Blob([`${JSON.stringify(analysis, null, 2)}\n`], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = defaultName;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  reviewStatus.textContent = `Traceability analysis exported to ${defaultName}`;
}

document.getElementById('refreshBtn').addEventListener('click', refreshModels);
document.getElementById('healthBtn').addEventListener('click', checkHealth);
document.getElementById('reviewBtn').addEventListener('click', runReview);
document.getElementById('traceabilityBtn').addEventListener('click', runTraceabilityAnalysis);
document.getElementById('downloadReviewTextBtn').addEventListener('click', () => exportReview());
document.getElementById('downloadTraceabilityBtn').addEventListener('click', exportTraceabilityAnalysis);
addReferenceBtn.addEventListener('click', () => fileInput.click());
removeReferenceBtn.addEventListener('click', removeSelectedReference);
addReviewDocBtn.addEventListener('click', () => reviewFileInput.click());
removeReviewDocBtn.addEventListener('click', removeSelectedReviewDocument);
reviewModeToggleBtn.addEventListener('click', () => {
  setReviewInputMode(reviewInputMode === 'files' ? 'text' : 'files');
});
saveConfigBtn.addEventListener('click', saveConfig);
skillSelect.addEventListener('change', () => {
  captureCurrentSkillAnswers();
  renderSelectedSkill();
});
skillModeRadio.addEventListener('change', () => setPromptMode('skill'));
customModeRadio.addEventListener('change', () => setPromptMode('custom'));
modelSelect.addEventListener('change', () => {
  preferredModelName = modelSelect.value;
});
fileInput.addEventListener('change', handleFileSelection);
reviewFileInput.addEventListener('change', handleReviewDocumentSelection);

const savedConfig = readConfig();
applyConfig(savedConfig);
setReviewInputMode(reviewInputMode);
setPromptMode(promptMode);
checkHealth();
refreshModels();
loadSkills();
