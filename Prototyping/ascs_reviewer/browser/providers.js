export function buildModelProvider({ mode, baseUrl, model, apiKey, contextLimit }) {
  if (mode === 'hosted') {
    return {
      mode: 'hosted',
      base_url: baseUrl.trim(),
      model: model.trim(),
      api_key: apiKey.trim(),
      context_limit: Number(contextLimit) || null,
    };
  }
  return {
    mode: 'ollama',
    model,
    context_limit: Number(contextLimit) || null,
  };
}

export function validateHostedProvider(provider) {
  if (!provider.base_url) throw new Error('Enter the hosted model server URL.');
  if (!provider.model) throw new Error('Enter the hosted model identifier.');
}

export function formatModelDate(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString();
}

export function formatModelDateTime(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString();
}
