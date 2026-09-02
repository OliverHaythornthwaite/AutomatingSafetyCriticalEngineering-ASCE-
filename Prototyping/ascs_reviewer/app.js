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
const ragStoreInput = document.getElementById('ragStoreInput');
const ragStatus = document.getElementById('ragStatus');
const chunkTokenDetails = document.getElementById('chunkTokenDetails');
const ragEnabled = document.getElementById('ragEnabled');
const ragScope = document.getElementById('ragScope');
const benchmarkStatus = document.getElementById('benchmarkStatus');
const benchmarkResultsBody = document.getElementById('benchmarkResults');
const providerModeBtn = document.getElementById('providerModeBtn');
const providerModeLabel = document.getElementById('providerModeLabel');
const ollamaAccessPanel = document.getElementById('ollamaAccessPanel');
const hostedAccessPanel = document.getElementById('hostedAccessPanel');
const hostedBaseUrl = document.getElementById('hostedBaseUrl');
const hostedModel = document.getElementById('hostedModel');
const hostedApiKey = document.getElementById('hostedApiKey');
const hostedHealthBtn = document.getElementById('hostedHealthBtn');
const hostedBenchmarkBtn = document.getElementById('hostedBenchmarkBtn');
const hostedStatus = document.getElementById('hostedStatus');
const ollamaModelSelection = document.getElementById('ollamaModelSelection');
const hostedModelSelection = document.getElementById('hostedModelSelection');
const hostedModelSummary = document.getElementById('hostedModelSummary');
const contextWindow = document.getElementById('contextWindow');
const contextWindowStatus = document.getElementById('contextWindowStatus');
const hostedContextLimit = document.getElementById('hostedContextLimit');
const CONFIG_STORAGE_KEY = 'ascs-reviewer-config';
const reviewDocuments = [];
const referenceEntries = [];
let indexedReferenceDocuments = [];
let reviewSkills = [];
let skillAnswerSets = {};
let reviewInputMode = 'files';
let promptMode = 'skill';
let preferredModelName = '';
let preferredSkillId = 'general-review';
let renderedSkillId = '';
let modelAccessMode = 'ollama';
let hostedDetectedModelName = '';
let preferredContextWindow = 32768;
const benchmarkResults = new Map();
const REQUIRED_SERVER_CAPABILITIES = ['context-window-v1', 'model-context-discovery-v1', 'hosted-model-v1', 'model-benchmark-v1', 'rag-store-v1', 'rag-document-lifecycle-v1', 'indexed-reference-workflow-v1', 'staged-retrieval-v1', 'chunk-token-count-v1'];

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
    reviewDocumentText: document.getElementById('documentText').value,
    reviewInputMode,
    ragEnabled: ragEnabled.checked,
    ragScope: ragScope.value,
    modelAccessMode,
    hostedBaseUrl: hostedBaseUrl.value.trim(),
    hostedModel: hostedModel.value.trim(),
    contextWindow: contextWindow.value,
    hostedContextLimit: hostedContextLimit.value,
  };
  localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(config));
  reviewStatus.textContent = 'Configuration saved.';
}

function applyConfig(config) {
  if (!config) {
    return;
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
  if (typeof config.hostedBaseUrl === 'string' && config.hostedBaseUrl.trim()) {
    hostedBaseUrl.value = config.hostedBaseUrl.trim();
  }
  if (typeof config.hostedModel === 'string') {
    hostedModel.value = config.hostedModel;
  }
  if (config.modelAccessMode === 'hosted' || config.modelAccessMode === 'ollama') {
    setModelAccessMode(config.modelAccessMode);
  }
  const savedContextWindow = Number(config.contextWindow);
  if (savedContextWindow >= 8192 && savedContextWindow <= 131072) {
    preferredContextWindow = savedContextWindow;
    if (Array.from(contextWindow.options).some((option) => Number(option.value) === savedContextWindow)) {
      contextWindow.value = String(savedContextWindow);
    }
  }
  if (config.hostedContextLimit && Number(config.hostedContextLimit) > 0) {
    hostedContextLimit.value = String(config.hostedContextLimit);
  }
  if (typeof config.ragEnabled === 'boolean') {
    ragEnabled.checked = config.ragEnabled;
  }
  if (['12', '24', '40'].includes(String(config.ragScope))) {
    ragScope.value = String(config.ragScope);
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

function buildModelProviderPayload() {
  if (modelAccessMode === 'hosted') {
    return {
      mode: 'hosted',
      base_url: hostedBaseUrl.value.trim(),
      model: hostedModel.value.trim(),
      api_key: hostedApiKey.value.trim(),
      context_limit: Number(hostedContextLimit.value) || null,
    };
  }
  const selectedModel = currentModels.find((model) => model.name === modelSelect.value);
  return { mode: 'ollama', model: modelSelect.value, context_limit: Number(selectedModel?.max_context_length) || null };
}

function syncHostedModelSummary() {
  const modelName = hostedModel.value.trim();
  const serverName = hostedBaseUrl.value.trim();
  hostedModelSummary.value = modelName
    ? `${modelName}${serverName ? ` via ${serverName}` : ''}`
    : 'Configure the hosted model in Model access';
}

function getActiveContextLimit() {
  if (modelAccessMode === 'hosted') {
    return Number(hostedContextLimit.value) || null;
  }
  const selectedModel = currentModels.find((model) => model.name === modelSelect.value);
  return Number(selectedModel?.max_context_length) || null;
}

function syncContextWindowOptions() {
  const contextLimit = getActiveContextLimit();
  const previousSelection = preferredContextWindow;
  contextWindow.querySelectorAll('option[data-model-maximum]').forEach((option) => option.remove());
  const hasExactOption = Array.from(contextWindow.options).some((option) => Number(option.value) === contextLimit);
  if (contextLimit && contextLimit >= 8192 && contextLimit <= 131072 && !hasExactOption) {
    const maximumOption = document.createElement('option');
    maximumOption.value = String(contextLimit);
    maximumOption.dataset.modelMaximum = 'true';
    maximumOption.textContent = `${Number.isInteger(contextLimit / 1024) ? `${contextLimit / 1024}K` : contextLimit.toLocaleString()} tokens — model maximum`;
    contextWindow.appendChild(maximumOption);
    Array.from(contextWindow.options)
      .sort((left, right) => Number(left.value) - Number(right.value))
      .forEach((option) => contextWindow.appendChild(option));
  }
  const options = Array.from(contextWindow.options);
  options.forEach((option) => {
    option.disabled = !contextLimit || Number(option.value) > contextLimit;
  });
  const validOptions = options.filter((option) => !option.disabled);
  contextWindow.disabled = validOptions.length === 0;
  const previousOption = options.find((option) => Number(option.value) === previousSelection);
  if (previousOption && !previousOption.disabled) {
    contextWindow.value = previousOption.value;
  } else if (validOptions.length) {
    contextWindow.value = validOptions[validOptions.length - 1].value;
  }

  const selectedName = modelAccessMode === 'hosted' ? hostedModel.value.trim() : modelSelect.value;
  if (!selectedName) {
    contextWindowStatus.textContent = 'Select a model to check its supported context size.';
  } else if (!contextLimit) {
    contextWindowStatus.textContent = modelAccessMode === 'hosted'
      ? 'The hosted model limit is unknown. Check the server or enter its maximum context before reviewing.'
      : `Ollama did not report a context limit for ${selectedName}; explicit context choices are disabled.`;
  } else if (!validOptions.length) {
    contextWindowStatus.textContent = `${selectedName} reports a ${contextLimit.toLocaleString()}-token maximum, below the available review settings.`;
  } else {
    contextWindowStatus.textContent = `${selectedName} supports up to ${contextLimit.toLocaleString()} tokens. Oversized context choices are disabled.`;
  }
}

function validateContextSelection() {
  const contextLimit = getActiveContextLimit();
  if (!contextLimit) {
    throw new Error('The selected model context limit is unknown. Refresh local models, or check/configure the hosted server first.');
  }
  const selectedContext = Number(contextWindow.value);
  if (!selectedContext || selectedContext > contextLimit) {
    throw new Error(`Choose a context window no larger than ${contextLimit.toLocaleString()} tokens for the selected model.`);
  }
  return { selectedContext, contextLimit };
}

function setModelAccessMode(mode) {
  modelAccessMode = mode === 'hosted' ? 'hosted' : 'ollama';
  const hosted = modelAccessMode === 'hosted';
  ollamaAccessPanel.hidden = hosted;
  hostedAccessPanel.hidden = !hosted;
  ollamaModelSelection.hidden = hosted;
  hostedModelSelection.hidden = !hosted;
  providerModeLabel.textContent = hosted ? 'Mode: Hosted model server' : 'Mode: Local Ollama';
  providerModeBtn.textContent = hosted ? 'Switch to local Ollama' : 'Switch to hosted server';
  syncHostedModelSummary();
  syncContextWindowOptions();
}

function validateHostedProvider(provider) {
  if (!provider.base_url) throw new Error('Enter the hosted model server URL.');
  if (!provider.model) throw new Error('Enter the hosted model identifier.');
}

async function checkHostedServer() {
  const provider = buildModelProviderPayload();
  try {
    validateHostedProvider(provider);
    hostedHealthBtn.disabled = true;
    hostedStatus.textContent = `Checking ${provider.base_url}...`;
    const data = await fetchJson('/api/hosted/health', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: provider.model, model_provider: provider }),
    });
    if (data.error) throw new Error(data.error);
    if (data.max_context_length) {
      hostedContextLimit.value = String(data.max_context_length);
      hostedDetectedModelName = provider.model;
    }
    syncContextWindowOptions();
    const availability = data.model_available
      ? `${provider.model} is available.`
      : `${provider.model} was not listed by the server.`;
    const listed = data.available_models?.length
      ? `\nModels: ${data.available_models.join(', ')}`
      : '\nThe server did not return a model catalogue; direct review requests may still work.';
    const contextDetail = data.max_context_length
      ? ` Maximum context: ${Number(data.max_context_length).toLocaleString()} tokens.`
      : ' The server did not report a context maximum; enter the configured server limit manually.';
    hostedStatus.textContent = `Hosted server ONLINE (${data.latency_seconds}s). ${availability}${contextDetail}${listed}`;
  } catch (error) {
    hostedStatus.textContent = `Hosted connection failed: ${error.message}`;
  } finally {
    hostedHealthBtn.disabled = false;
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
  const selectedDocumentId = referenceEntries[getSelectedEntryIndex(referenceList, referenceEntries)]?.rag_document_id || '';
  referenceList.innerHTML = '';
  if (!referenceEntries.length) {
    const placeholder = document.createElement('option');
    placeholder.textContent = 'No reference documents selected';
    placeholder.disabled = true;
    referenceList.appendChild(placeholder);
    renderChunkTokenDetails();
    return;
  }
  referenceEntries.forEach((entry, index) => {
    const option = document.createElement('option');
    option.value = String(index);
    const tokenDetail = entry.rag_token_count ? `, ~${entry.rag_token_count.toLocaleString()} tokens` : '';
    const indexedDetail = ` (indexed, ${entry.rag_chunk_count || 0} chunk(s)${tokenDetail})`;
    option.textContent = `${entry.name}${indexedDetail}`;
    if (entry.rag_document_id === selectedDocumentId) option.selected = true;
    referenceList.appendChild(option);
  });
  if (referenceList.selectedIndex < 0) referenceList.selectedIndex = 0;
  renderChunkTokenDetails();
}

function renderChunkTokenDetails() {
  chunkTokenDetails.innerHTML = '';
  const selectedIndex = getSelectedEntryIndex(referenceList, referenceEntries);
  const entry = selectedIndex >= 0 ? referenceEntries[selectedIndex] : null;
  const documentInfo = indexedReferenceDocuments.find((document) => document.document_id === entry?.rag_document_id);
  if (!documentInfo || !Array.isArray(documentInfo.chunks) || !documentInfo.chunks.length) {
    chunkTokenDetails.textContent = referenceEntries.length
      ? 'Token details are not available for this reference.'
      : 'Select an indexed reference to see its per-chunk token counts.';
    return;
  }
  const heading = document.createElement('strong');
  heading.textContent = `${documentInfo.name}: ${documentInfo.chunk_count} chunk(s), ~${Number(documentInfo.token_count || 0).toLocaleString()} tokens total`;
  const list = document.createElement('ol');
  list.className = 'chunk-token-list';
  documentInfo.chunks.forEach((chunk, index) => {
    const item = document.createElement('li');
    const chunkLabel = chunk.id || `chunk-${index + 1}`;
    item.textContent = `${chunkLabel}: ~${Number(chunk.token_count || 0).toLocaleString()} tokens`;
    list.appendChild(item);
  });
  chunkTokenDetails.append(heading, list);
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

function featureErrorMessage(error, featureName) {
  const message = String(error?.message || error || 'Unknown error');
  if (/\b404\b|not found/i.test(message)) {
    return `${featureName} is unavailable because the running ASCS Reviewer server is outdated. Restart the server, then reload this page.`;
  }
  return `${featureName} failed: ${message}`;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function formatByteSize(value) {
  if (value === null || value === undefined || value === '') return '';
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let amount = bytes;
  let unitIndex = -1;
  do {
    amount /= 1024;
    unitIndex += 1;
  } while (amount >= 1024 && unitIndex < units.length - 1);
  return `${amount >= 10 ? amount.toFixed(1) : amount.toFixed(2)} ${units[unitIndex]}`;
}

function formatModelDate(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString();
}

function formatModelDateTime(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString();
}

function renderModelMetadata(model) {
  const metadata = [
    ['Family', model.family],
    ['Parameters', model.parameter_size],
    ['Quantization', model.quantization_level],
    ['Format', model.format ? String(model.format).toUpperCase() : ''],
    ['Disk size', formatByteSize(model.size)],
    ['Updated', formatModelDate(model.modified_at)],
    ['Maximum context', model.max_context_length ? Number(model.max_context_length).toLocaleString() + ' tokens' : 'Not reported'],
    ['Loaded context', model.context_length ? Number(model.context_length).toLocaleString() + ' tokens' : ''],
    ['Memory', formatByteSize(model.size_vram)],
    ['Loaded until', formatModelDateTime(model.expires_at)],
  ].filter(([, value]) => value !== null && value !== undefined && value !== '');

  if (metadata.length === 0) {
    return '<span class="model-meta-empty">No additional model metadata reported.</span>';
  }
  return metadata.map(([label, value]) => `
    <span class="model-meta-item"><b>${escapeHtml(label)}</b>${escapeHtml(value)}</span>
  `).join('');
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
          <div class="model-summary">
            <span class="pill ${model.status === 'online' ? '' : 'offline'}">${escapeHtml(model.name)} · ${escapeHtml(model.status)}</span>
            <div class="model-meta">${renderModelMetadata(model)}</div>
          </div>
          <div class="row model-actions">
            <button class="secondary model-action" data-model="${escapeHtml(model.name)}" data-action="start">Start</button>
            <button class="secondary model-action model-action-ready" data-model="${escapeHtml(model.name)}" data-action="ready">Check ready</button>
            <button class="secondary model-action model-action-test" data-model="${escapeHtml(model.name)}" data-action="benchmark">Test</button>
            <button class="secondary model-action" data-model="${escapeHtml(model.name)}" data-action="stop">Stop</button>
          </div>
        </div>
      `).join('');
      modelsPane.querySelectorAll('button[data-model]').forEach((button) => {
        button.addEventListener('click', () => {
          const buttonModel = button.getAttribute('data-model');
          if (Array.from(modelSelect.options).some((option) => option.value === buttonModel)) {
            modelSelect.value = buttonModel;
            preferredModelName = buttonModel;
            syncContextWindowOptions();
          }
          const action = button.getAttribute('data-action') || 'start';
          if (action === 'stop') {
            stopModel(buttonModel);
          } else if (action === 'benchmark') {
            runModelBenchmark(buttonModel, button);
          } else if (action === 'ready') {
            checkModelReady(buttonModel);
          } else {
            startModel(buttonModel);
          }
        });
      });

      const preferredModel = models.find((model) => model.name === selectedModelName) || models.find((model) => model.status === 'online') || models[0];
      if (preferredModel) {
        modelSelect.value = preferredModel.name;
        preferredModelName = preferredModel.name;
      }
      syncContextWindowOptions();

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
    const capabilities = Array.isArray(data.capabilities) ? data.capabilities : [];
    const missingCapabilities = REQUIRED_SERVER_CAPABILITIES.filter((capability) => !capabilities.includes(capability));
    healthStatus.textContent = `Ollama endpoint: ${data.ollama_base_url}\nStatus: ${data.status.toUpperCase()}\nModel count: ${data.model_count ?? 'n/a'}\nReviewer API: ${data.api_version || 'outdated'}`;
    if (missingCapabilities.length) {
      healthStatus.textContent += `\nServer update required: restart ASCS Reviewer to enable ${missingCapabilities.join(', ')}.`;
    }
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
    const contextConfiguration = validateContextSelection();
    healthStatus.textContent = `Loading ${modelName} and checking readiness...`;
    const data = await fetchJson('/api/models/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: modelName, context_window: contextConfiguration.selectedContext, model_context_limit: contextConfiguration.contextLimit }) });
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
      const contextLabel = data.context_window ? ` at ${(data.context_window / 1024).toFixed(0)}K context` : '';
      healthStatus.textContent = data.latency_seconds ? `Ready: ${modelName} responded in ${data.latency_seconds}s${contextLabel}.` : `Started ${modelName}${contextLabel}`;
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
    const contextConfiguration = validateContextSelection();
    healthStatus.textContent = `Checking whether ${modelName} can respond...`;
    const data = await fetchJson('/api/models/ready', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: modelName, context_window: contextConfiguration.selectedContext, model_context_limit: contextConfiguration.contextLimit }) });
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
      const contextLabel = data.context_window ? ` at ${(data.context_window / 1024).toFixed(0)}K context` : '';
      healthStatus.textContent = data.latency_seconds ? `Ready: ${modelName} responded in ${data.latency_seconds}s${contextLabel}.` : `Ready: ${modelName} responded${contextLabel}.`;
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

function renderBenchmarkResults() {
  if (!benchmarkResults.size) {
    benchmarkResultsBody.innerHTML = '<tr><td colspan="6" class="muted">Run Test on an installed model to add a result.</td></tr>';
    return;
  }
  benchmarkResultsBody.innerHTML = Array.from(benchmarkResults.values())
    .sort((left, right) => right.score - left.score)
    .map((result) => `
      <tr>
        <td>${escapeHtml(result.model)}</td>
        <td><b>${escapeHtml(result.score.toFixed(1))}/100</b></td>
        <td>${escapeHtml(result.metrics.precision_percent)}%</td>
        <td>${escapeHtml(result.metrics.recall_percent)}%</td>
        <td>${escapeHtml(result.metrics.control_accuracy_percent)}%</td>
        <td>${escapeHtml(result.review_seconds)}s</td>
      </tr>
    `).join('');
}

async function runModelBenchmark(modelName, button, providerConfig = null) {
  if (!modelName) return;
  const localModel = currentModels.find((model) => model.name === modelName);
  const provider = providerConfig || { mode: 'ollama', model: modelName, context_limit: Number(localModel?.max_context_length) || null };
  const previousLabel = button?.textContent || 'Test';
  if (button) {
    button.disabled = true;
    button.textContent = 'Testing...';
  }
  benchmarkStatus.textContent = `Preparing ${modelName} and running benchmark v1.0...`;
  try {
    const contextConfiguration = validateContextSelection();
    const data = await fetchJson('/api/models/benchmark', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelName, model_provider: provider, context_window: contextConfiguration.selectedContext }),
    });
    if (data.error) throw new Error(data.error);
    const resultKey = `${data.provider_mode || provider.mode}:${provider.base_url || ''}:${modelName}`;
    benchmarkResults.set(resultKey, data);
    renderBenchmarkResults();
    const missed = data.metrics?.missed_findings || [];
    const unexpected = data.metrics?.unexpected_findings || [];
    const detail = [
      missed.length ? `Missed: ${missed.map((item) => `${item.requirement_id}/${item.rule_id}`).join(', ')}.` : 'All seeded defects found.',
      unexpected.length ? `Unexpected: ${unexpected.map((item) => `${item.requirement_id}/${item.rule_id}`).join(', ')}.` : 'No unexpected findings.',
      data.parse_error ? data.parse_error : '',
    ].filter(Boolean).join(' ');
    const contextLabel = data.context_window ? ` with a ${(data.context_window / 1024).toFixed(0)}K context window` : '';
    benchmarkStatus.textContent = `${modelName} scored ${data.score.toFixed(1)}/100${contextLabel} in ${data.review_seconds}s after ${data.warmup_seconds}s warm-up. ${detail}`;
    if ((data.provider_mode || provider.mode) === 'ollama') {
      await refreshModels();
    }
  } catch (error) {
    benchmarkStatus.textContent = `${featureErrorMessage(error, 'Model benchmark')} Model: ${modelName}.`;
  } finally {
    if (button?.isConnected) {
      button.disabled = false;
      button.textContent = previousLabel;
    }
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
      const isTextLike = file.type.startsWith('text/') || /\.(txt|md|rtf|json|csv|tsv|log|ya?ml|xml|html?|toml|ini|cfg|conf|rst|py|c|h|cc|hh|cpp|hpp|cxx|hxx|js|jsx|ts|tsx|java|cs|sql|sh|bat|ps1|m|mm|s|asm|scade|xscade|etp|sgfx|pgfx|ogfx|dgfx|sdfx|rgfx|sss|in|sns|out|obs)$/i.test(file.name);
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

function renderRagStatus(data) {
  indexedReferenceDocuments = Array.isArray(data?.documents) ? data.documents : [];
  syncRagReferenceEntries(data);
  if (!data?.loaded) {
    ragStatus.textContent = 'No retrieval knowledge is loaded.';
    return;
  }
  const vectorDetail = data.vector_chunk_count
    ? ` ${data.vector_chunk_count} chunk(s) have ${data.dimensions || 'unknown'}-dimension vectors${data.embedding_model ? ` from ${data.embedding_model}` : ''}.`
    : '';
  ragStatus.textContent = `${data.name || 'Reference index'}: ${data.chunk_count || 0} chunk(s), ~${Number(data.token_count || 0).toLocaleString()} tokens across ${data.source_count || 0} source(s). Retrieval: ${data.retrieval_mode}.${vectorDetail}`;
}

function syncRagReferenceEntries(data) {
  const indexedDocuments = Array.isArray(data?.documents) ? data.documents : [];
  const activeIds = new Set(indexedDocuments.map((document) => String(document.document_id || '')).filter(Boolean));

  for (let index = referenceEntries.length - 1; index >= 0; index -= 1) {
    const entry = referenceEntries[index];
    if (!entry.rag_document_id || activeIds.has(entry.rag_document_id)) continue;
    referenceEntries.splice(index, 1);
  }

  indexedDocuments.forEach((document) => {
    const documentId = String(document.document_id || '').trim();
    if (!documentId) return;
    let entry = referenceEntries.find((candidate) => candidate.rag_document_id === documentId);
    if (!entry) {
      entry = referenceEntries.find((candidate) => !candidate.rag_document_id && candidate.name === document.name);
    }
    if (!entry) {
      entry = { name: document.name || 'Knowledge document' };
      referenceEntries.push(entry);
    }
    entry.rag_document_id = documentId;
    entry.rag_chunk_count = Number(document.chunk_count) || 0;
    entry.rag_token_count = Number(document.token_count) || 0;
  });
  renderReferenceEntries();
}

function createRagDocumentId() {
  if (globalThis.crypto?.randomUUID) return `browser-${globalThis.crypto.randomUUID()}`;
  return `browser-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function refreshRagStatus() {
  try {
    renderRagStatus(await fetchJson('/api/rag/status'));
  } catch (error) {
    ragStatus.textContent = featureErrorMessage(error, 'Retrieval status');
  }
}

async function handleRagStoreSelection(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  ragStatus.textContent = `Loading vector store ${file.name}...`;
  try {
    const store = JSON.parse(await file.text());
    const data = await fetchJson('/api/rag/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: file.name, store, append: false }),
    });
    if (data.error) throw new Error(data.error);
    renderRagStatus(data);
  } catch (error) {
    ragStatus.textContent = featureErrorMessage(error, 'Vector store load');
  } finally {
    event.target.value = '';
  }
}

async function clearRagKnowledge() {
  ragStatus.textContent = 'Clearing indexed references...';
  try {
    const data = await fetchJson('/api/rag/clear', { method: 'POST' });
    referenceEntries.splice(0, referenceEntries.length);
    renderRagStatus(data);
    documentStatus.textContent = 'Cleared all reference documents and their associated chunks.';
  } catch (error) {
    ragStatus.textContent = featureErrorMessage(error, 'Clear references');
  }
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
    if (!addedEntries.length) {
      documentStatus.textContent = 'Those reference files are already indexed.';
      return;
    }
    addedEntries.forEach((document) => {
      document.document_id = createRagDocumentId();
    });
    documentStatus.textContent = `Chunking and indexing ${addedEntries.length} reference document(s)...`;
    ragStatus.textContent = `Vectorising ${addedEntries.length} reference document(s)...`;
    const data = await fetchJson('/api/rag/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Indexed reference documents', documents: addedEntries, append: true }),
    });
    if (data.error) throw new Error(data.error);
    addedEntries.forEach((document) => {
      document.rag_document_id = document.document_id;
      referenceEntries.push(document);
    });
    renderRagStatus(data);
    documentStatus.textContent = `Added and indexed ${addedEntries.length} reference document(s). Select one to inspect token counts.`;
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

async function removeSelectedReference() {
  const selectedIndex = getSelectedEntryIndex(referenceList, referenceEntries);
  if (selectedIndex < 0) {
    documentStatus.textContent = 'Select an entry to remove.';
    return;
  }
  const removedEntry = referenceEntries[selectedIndex];
  try {
    let ragData = null;
    if (removedEntry.rag_document_id) {
      documentStatus.textContent = `Removing ${removedEntry.name} and its retrieval chunks...`;
      ragData = await fetchJson('/api/rag/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ document_ids: [removedEntry.rag_document_id] }),
      });
      if (ragData.error) throw new Error(ragData.error);
    }
    const currentIndex = referenceEntries.indexOf(removedEntry);
    if (currentIndex >= 0) referenceEntries.splice(currentIndex, 1);
    if (ragData) renderRagStatus(ragData);
    else renderReferenceEntries();
    const chunkDetail = ragData ? ` and ${ragData.removed_chunk_count || 0} associated retrieval chunk(s)` : '';
    documentStatus.textContent = `Removed ${removedEntry?.name || 'reference entry'}${chunkDetail}.`;
  } catch (error) {
    documentStatus.textContent = featureErrorMessage(error, 'Reference removal');
  }
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
  const modelProvider = buildModelProviderPayload();
  const payload = {
    model: modelProvider.model,
    model_provider: modelProvider,
    context_window: Number(contextWindow.value),
    prompt_mode: promptMode,
    document_text: document.getElementById('documentText').value,
    rag: {
      enabled: ragEnabled.checked,
      max_chunks: Number(ragScope.value) || 24,
    },
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
  reviewStatus.textContent = modelAccessMode === 'hosted'
    ? 'Sending the review to the hosted model server...'
    : 'Reviewing with high effort. Large local models can take several minutes...';
  reviewOutput.textContent = 'Generating complete-document review...';
  try {
    validateContextSelection();
    const payload = buildReviewPayload();
    if (payload.model_provider.mode === 'hosted') {
      validateHostedProvider(payload.model_provider);
    }
    const data = await fetchJson('/api/reviewer/review', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (data.error) {
      reviewStatus.textContent = `Review failed: ${data.error}`;
      reviewOutput.textContent = `Review failed: ${data.error}`;
      return;
    }
    const reviewResult = normalizeReviewResultForDisplay(data.review_result || data.review || 'No review generated.');
    window.latestReviewResult = reviewResult;
    const reviewMethod = data.skill_name ? ` using ${data.skill_name}` : '';
    const retrievalMethod = data.retrieval
      ? `; selected ${data.retrieval.selected_chunks || 0} of ${data.retrieval.available_chunks || 0} available knowledge chunk(s)`
      : '';
    const relevanceMethod = data.retrieval?.relevance_stepthrough
      ? ` after scanning ${data.retrieval.relevance_stepthrough.target_chunks_scanned || 0} target chunk(s) and focusing ${data.retrieval.relevance_stepthrough.focus_chunks || 0}`
      : '';
    const atomicRepairMethod = data.atomic_comment_repair?.source
      ? `; recovered ${data.atomic_comment_repair.comment_count || 0} atomic comment(s) using ${data.atomic_comment_repair.source}`
      : '';
    const providerMethod = data.provider_mode === 'hosted' ? 'hosted model' : 'local Ollama';
    const contextLabel = data.context_window ? ` using ${(data.context_window / 1024).toFixed(0)}K context` : '';
    reviewStatus.textContent = `Review completed with ${data.model} via ${providerMethod}${contextLabel}${reviewMethod} across ${data.source_count || 0} source document(s)${retrievalMethod}${relevanceMethod}${atomicRepairMethod}`;
    renderReviewOutput(reviewResult);
    if (data.provider_mode !== 'hosted') {
      refreshModels();
    }
  } catch (error) {
    reviewStatus.textContent = error.message;
    reviewOutput.textContent = error.message;
  }
}

async function runTraceabilityAnalysis() {
  traceabilityPanel.style.display = 'block';
  traceabilityPanel.open = true;
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

function parseStructuredReviewJson(value) {
  if (typeof value !== 'string') return value;
  const text = value.trim().replace(/^\uFEFF/, '');
  const candidates = [text];
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fenced) candidates.push(fenced[1].trim());
  const firstBrace = text.indexOf('{');
  const lastBrace = text.lastIndexOf('}');
  if (firstBrace >= 0 && lastBrace > firstBrace) candidates.push(text.slice(firstBrace, lastBrace + 1));
  for (const candidate of candidates) {
    let parsed = candidate;
    for (let attempt = 0; attempt < 3 && typeof parsed === 'string'; attempt += 1) {
      try {
        parsed = JSON.parse(parsed);
      } catch (error) {
        parsed = null;
        break;
      }
    }
    if (parsed && typeof parsed === 'object') return parsed;
  }
  return value;
}

function formatReviewDisplayValue(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return String(value);
  if (Array.isArray(value)) {
    return value.map((item) => {
      const formatted = formatReviewDisplayValue(item);
      if (!formatted) return '';
      return formatted.includes('\n') ? formatted : `- ${formatted}`;
    }).filter(Boolean).join('\n\n');
  }
  if (typeof value === 'object') {
    const structuredFinding = formatStructuredFindingForDisplay(value);
    if (structuredFinding) return structuredFinding;
    return Object.entries(value).map(([key, item]) => {
      const label = key.replace(/_/g, ' ').replace(/^./, (letter) => letter.toUpperCase());
      const formatted = formatReviewDisplayValue(item);
      return formatted.includes('\n') ? `${label}:\n${formatted}` : `${label}: ${formatted}`;
    }).filter((line) => !line.endsWith(': ')).join('\n');
  }
  return String(value);
}

function formatStructuredFindingForDisplay(value) {
  const findingKeys = ['location', 'issue', 'problem', 'violated_rule', 'rule_violated', 'rule', 'evidence', 'comment', 'suggested_resolution', 'target_fix', 'resolution', 'fix'];
  if (!findingKeys.some((key) => Object.hasOwn(value, key))) return '';
  const fields = [
    ['Location', value.location],
    ['Rule violated', value.violated_rule || value.rule_violated || value.applicable_rule || value.rule],
    ['Rule evidence', value.rule_evidence || value.rule_reference],
    ['Issue', value.issue || value.problem || value.title],
    ['Evidence', value.evidence || value.comment || value.details],
    ['Target fix', value.suggested_resolution || value.target_fix || value.resolution || value.fix],
  ];
  return fields.filter(([, item]) => item !== null && item !== undefined && item !== '')
    .map(([label, item]) => `${label}: ${formatReviewDisplayValue(item)}`)
    .join('\n');
}

function normalizeReviewResultForDisplay(value) {
  let result = parseStructuredReviewJson(value);
  if (Array.isArray(result)) {
    const issueKeys = ['issue', 'problem', 'comment', 'location', 'suggested_resolution', 'target_fix'];
    const containsComments = result.some((item) => item && typeof item === 'object' && issueKeys.some((key) => Object.hasOwn(item, key)));
    result = containsComments
      ? { summary: 'Review completed.', atomic_comments: result }
      : { summary: 'Review completed.', sections: result };
  }
  if (!result || typeof result !== 'object') {
    const text = formatReviewDisplayValue(result || value || 'No review generated.');
    return { summary: text, sections: [{ title: 'Review', content: text }], atomic_comments: [] };
  }
  for (const key of ['review_result', 'review', 'result', 'output']) {
    if (result[key] && typeof result[key] === 'object' && !result.summary && !result.sections) {
      result = result[key];
      break;
    }
  }
  let sections = result.sections || result.review_sections || [];
  if (!Array.isArray(sections) && sections && typeof sections === 'object') {
    sections = Object.entries(sections).map(([title, content]) => ({ title, content }));
  }
  if (!Array.isArray(sections)) sections = sections ? [sections] : [];
  sections = sections.map((section, index) => {
    if (!section || typeof section !== 'object' || Array.isArray(section)) {
      return { title: `Review section ${index + 1}`, content: formatReviewDisplayValue(section) };
    }
    const content = section.content ?? section.findings ?? section.issues ?? section.assessment ?? section.text ?? '';
    return {
      title: formatReviewDisplayValue(section.title || section.name || `Review section ${index + 1}`),
      content: formatReviewDisplayValue(content),
    };
  });
  let comments = result.atomic_comments || result.atomicComments || result.comments || result.findings || [];
  if (!Array.isArray(comments) && comments && typeof comments === 'object') comments = Object.values(comments);
  if (!Array.isArray(comments)) comments = comments ? [comments] : [];
  comments = comments.filter((comment) => comment && typeof comment === 'object').map((comment, index) => ({
    id: formatReviewDisplayValue(comment.id || `A${index + 1}`),
    location: formatReviewDisplayValue(comment.location || ''),
    violated_rule: formatReviewDisplayValue(comment.violated_rule || comment.rule_violated || comment.rule || ''),
    rule_evidence: formatReviewDisplayValue(comment.rule_evidence || comment.rule_reference || ''),
    issue: formatReviewDisplayValue(comment.issue || comment.title || 'Issue'),
    comment: formatReviewDisplayValue(comment.comment || comment.evidence || comment.details || ''),
    suggested_resolution: formatReviewDisplayValue(comment.suggested_resolution || comment.target_fix || comment.resolution || ''),
  }));
  return {
    summary: formatReviewDisplayValue(result.summary || result.overall_assessment || result.executive_summary || 'Review completed.'),
    sections,
    atomic_comments: comments,
  };
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
    if (/^(?:(?:[-*]|\d+[\).])\s*)?(?:Location|Issue):/i.test(trimmed)) {
      insideIssue = true;
      const fieldLine = trimmed.replace(/^(?:[-*]|\d+[\).])\s*/, '');
      return `  ${/^Location:/i.test(fieldLine) ? stripPageFromLocation(fieldLine) : fieldLine}`;
    }
    if (insideIssue) {
      return `    ${trimmed}`;
    }
    return line;
  }).join('\n');
}

function splitSectionIssueBlocks(content) {
  const text = normalizeIndentedIssues(content || '');
  const fieldMatches = Array.from(text.matchAll(/(^|\n)\s*(?:(?:[-*]|\d+[\).])\s*)?(Location|Issue):/gi));
  const blockStarts = [];
  let currentHasIssue = false;
  fieldMatches.forEach((match) => {
    const start = match.index + match[1].length;
    if (match[2].toLowerCase() === 'location') {
      blockStarts.push(start);
      const lineEnd = text.indexOf('\n', start);
      const line = text.slice(start, lineEnd < 0 ? text.length : lineEnd);
      currentHasIssue = /\bIssue:\s*/i.test(line.replace(/^\s*Location:\s*/i, ''));
    } else if (!blockStarts.length || currentHasIssue) {
      blockStarts.push(start);
      currentHasIssue = true;
    } else {
      currentHasIssue = true;
    }
  });
  if (!blockStarts.length) {
    return { intro: text.trim(), issues: [] };
  }

  const intro = text.slice(0, blockStarts[0]).trim();
  const issues = blockStarts.map((start, index) => {
    const end = index + 1 < blockStarts.length ? blockStarts[index + 1] : text.length;
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
  parsed.issues.forEach((issue, index) => {
    parts.push(renderFindingBlock(issue, `Finding ${index + 1}`));
  });
  if (!parts.length) {
    parts.push('<div class="review-section-content">No content.</div>');
  }
  return parts.join('');
}

function parseIssueFields(block) {
  const fields = {};
  String(block || '').split(/\r?\n/).forEach((line) => {
    const match = line.trim().match(/^(Location|Rule violated|Rule evidence|Issue|Evidence|Comment|Details|Target fix|Suggested resolution):\s*(.*)$/i);
    if (match) {
      let key = match[1].toLowerCase().replace(/\s+/g, '_');
      if (key === 'comment' || key === 'details') key = 'evidence';
      if (key === 'suggested_resolution') key = 'target_fix';
      fields[key] = fields[key] ? `${fields[key]} ${match[2].trim()}` : match[2].trim();
    } else if (line.trim() && fields.evidence) {
      fields.evidence += ` ${line.trim()}`;
    }
  });
  return fields;
}

function renderFindingBlock(block, itemLabel = 'Finding') {
  const fields = parseIssueFields(block);
  if (!fields.issue && !fields.location) {
    fields.issue = itemLabel;
    fields.evidence = block;
  }
  return renderFindingCard(fields, itemLabel);
}

function buildFindingCopyText(fields) {
  return [
    fields.issue ? `Issue: ${fields.issue}` : '',
    fields.location ? `Location: ${stripPageFromLocation(fields.location)}` : '',
    fields.rule_violated ? `Rule violated: ${fields.rule_violated}` : '',
    fields.rule_evidence ? `Rule evidence: ${fields.rule_evidence}` : '',
    fields.evidence ? `Comment: ${fields.evidence.replace(/^Evidence:\s*/i, '')}` : '',
    fields.target_fix ? `Suggested resolution: ${fields.target_fix}` : '',
  ].filter(Boolean).join('\n');
}

function copyIcon(copied = false) {
  if (copied) {
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"></path></svg>';
  }
  return '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3"></path></svg>';
}

function renderFindingCard(fields, itemLabel = 'Comment') {
  const copyText = encodeURIComponent(buildFindingCopyText(fields));
  return `
    <article class="finding-card">
      <div class="finding-card-head">
        <div class="finding-card-heading">
          <span class="finding-item-label">${escapeHtml(itemLabel)}</span>
          <strong>${escapeHtml(fields.issue || 'Issue')}</strong>
          <span class="finding-location">${escapeHtml(stripPageFromLocation(fields.location || 'Not specified'))}</span>
        </div>
        <button class="finding-copy-button" type="button" data-copy-comment="${escapeHtml(copyText)}" title="Copy this comment" aria-label="Copy this comment">${copyIcon()}</button>
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

async function copyTextToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.setAttribute('readonly', '');
  textArea.style.position = 'fixed';
  textArea.style.opacity = '0';
  document.body.appendChild(textArea);
  textArea.select();
  const copied = document.execCommand('copy');
  textArea.remove();
  if (!copied) throw new Error('The browser did not permit clipboard access.');
}

async function handleReviewOutputClick(event) {
  const button = event.target.closest?.('.finding-copy-button');
  if (!button || !reviewOutput.contains(button)) return;
  try {
    await copyTextToClipboard(decodeURIComponent(button.dataset.copyComment || ''));
    button.classList.add('finding-copy-button-copied');
    button.innerHTML = copyIcon(true);
    button.title = 'Copied';
    button.setAttribute('aria-label', 'Comment copied');
    reviewStatus.textContent = 'Individual review comment copied to the clipboard.';
    window.setTimeout(() => {
      if (!button.isConnected) return;
      button.classList.remove('finding-copy-button-copied');
      button.innerHTML = copyIcon();
      button.title = 'Copy this comment';
      button.setAttribute('aria-label', 'Copy this comment');
    }, 1600);
  } catch (error) {
    reviewStatus.textContent = `Unable to copy comment: ${error.message}`;
  }
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
  const selectedModel = modelAccessMode === 'hosted' ? hostedModel.value : modelSelect.value;
  const modelName = (selectedModel || 'model').replace(/[^a-z0-9._-]+/gi, '-').replace(/^-+|-+$/g, '') || 'model';
  return `review-output-${modelName}-${timestamp}.txt`;
}

function renderReviewOutput(reviewResult) {
  reviewResult = normalizeReviewResultForDisplay(reviewResult);
  const sections = reviewResult?.sections || [];
  const comments = reviewResult?.atomic_comments || [];
  if (!sections.length && !comments.length) {
    reviewOutput.innerHTML = `<div class="small">${escapeHtml(reviewResult?.summary || 'No review output available.')}</div>`;
    return;
  }

  const html = [];
  html.push(`<div class="small" style="margin-bottom:0.6rem;"><strong>Summary:</strong> ${escapeHtml(reviewResult?.summary || 'No summary available.')}</div>`);
  sections.forEach((section) => {
    html.push(`<section class="review-section-box"><h3>${escapeHtml(section.title)}</h3>${renderSectionContent(section.content || 'No content.')}</section>`);
  });
  if (comments.length) {
    html.push(`<section class="review-section-box atomic-comments-box"><h3>Atomic comments</h3><div class="atomic-comment-list">${comments.map((comment, index) => {
      const rule = comment.violated_rule || 'Not found in provided reference material';
      return renderFindingCard({
        issue: `${comment.id}: ${comment.issue}`,
        location: comment.location || 'Not specified',
        rule_violated: rule,
        rule_evidence: comment.rule_evidence || '',
        evidence: comment.comment || 'N/A',
        target_fix: comment.suggested_resolution || 'N/A',
      }, `Comment ${index + 1}`);
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
providerModeBtn.addEventListener('click', () => {
  setModelAccessMode(modelAccessMode === 'ollama' ? 'hosted' : 'ollama');
});
hostedHealthBtn.addEventListener('click', checkHostedServer);
hostedBenchmarkBtn.addEventListener('click', () => {
  const provider = buildModelProviderPayload();
  try {
    validateHostedProvider(provider);
    runModelBenchmark(provider.model, hostedBenchmarkBtn, provider);
  } catch (error) {
    benchmarkStatus.textContent = error.message;
  }
});
hostedBaseUrl.addEventListener('input', () => {
  syncHostedModelSummary();
  if (hostedDetectedModelName) {
    hostedContextLimit.value = '';
    hostedDetectedModelName = '';
  }
  syncContextWindowOptions();
});
hostedModel.addEventListener('input', () => {
  syncHostedModelSummary();
  if (hostedDetectedModelName && hostedModel.value.trim() !== hostedDetectedModelName) {
    hostedContextLimit.value = '';
    hostedDetectedModelName = '';
  }
  syncContextWindowOptions();
});
hostedContextLimit.addEventListener('input', () => {
  hostedDetectedModelName = '';
  syncContextWindowOptions();
});
contextWindow.addEventListener('change', () => {
  preferredContextWindow = Number(contextWindow.value) || preferredContextWindow;
});
document.getElementById('reviewBtn').addEventListener('click', runReview);
document.getElementById('traceabilityBtn').addEventListener('click', runTraceabilityAnalysis);
document.getElementById('downloadReviewTextBtn').addEventListener('click', () => exportReview());
document.getElementById('downloadTraceabilityBtn').addEventListener('click', exportTraceabilityAnalysis);
reviewOutput.addEventListener('click', handleReviewOutputClick);
document.getElementById('loadRagStoreBtn').addEventListener('click', () => ragStoreInput.click());
document.getElementById('clearRagBtn').addEventListener('click', clearRagKnowledge);
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
  syncContextWindowOptions();
});
fileInput.addEventListener('change', handleFileSelection);
reviewFileInput.addEventListener('change', handleReviewDocumentSelection);
ragStoreInput.addEventListener('change', handleRagStoreSelection);
referenceList.addEventListener('change', renderChunkTokenDetails);

const savedConfig = readConfig();
applyConfig(savedConfig);
setModelAccessMode(modelAccessMode);
setReviewInputMode(reviewInputMode);
setPromptMode(promptMode);
checkHealth();
refreshModels();
loadSkills();
refreshRagStatus();
