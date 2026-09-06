// Pure normalization functions shared by review rendering and export.

export function parseStructuredReviewJson(value) {
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

export function formatReviewDisplayValue(value) {
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

export function normalizeReviewResultForDisplay(value) {
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

