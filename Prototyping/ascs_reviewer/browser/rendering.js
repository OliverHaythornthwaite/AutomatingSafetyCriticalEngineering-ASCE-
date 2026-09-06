export function featureErrorMessage(error, featureName) {
  const message = String(error?.message || error || 'Unknown error');
  if (/\b404\b|not found/i.test(message)) {
    return `${featureName} is unavailable because the running ASCS Reviewer server is outdated. Restart the server, then reload this page.`;
  }
  return `${featureName} failed: ${message}`;
}

export function formatByteSize(value) {
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

export function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function stripPageFromLocation(value) {
  return String(value || '')
    .replace(/\bpage\s+(?:not available in source|\d+(?:\s*\([^)]*\))?)\s*,?\s*/gi, '')
    .replace(/\|\s*page\s+(?:not available in source|\d+(?:\s*\([^)]*\))?)\s*\|?/gi, '|')
    .replace(/\s*\|\s*/g, ' | ')
    .replace(/^\|\s*|\s*\|$/g, '')
    .replace(/\s+,/g, ',')
    .replace(/^[\s,-]+|[\s,-]+$/g, '');
}
