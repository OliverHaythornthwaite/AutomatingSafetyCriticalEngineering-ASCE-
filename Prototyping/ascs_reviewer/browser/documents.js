export function getSelectedEntryIndex(selectElement, entries) {
  const selectedOption = selectElement.selectedOptions[0];
  const selectedValue = selectedOption?.value ?? '';
  const valueIndex = Number(selectedValue);
  if (Number.isInteger(valueIndex) && valueIndex >= 0 && entries[valueIndex]) {
    return valueIndex;
  }

  const selectedIndex = selectElement.selectedIndex;
  return selectedIndex >= 0 && entries[selectedIndex] ? selectedIndex : -1;
}

export function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = '';
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return btoa(binary);
}

export function readFileAsDocument(file) {
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

export function createRagDocumentId() {
  if (globalThis.crypto?.randomUUID) return `browser-${globalThis.crypto.randomUUID()}`;
  return `browser-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
