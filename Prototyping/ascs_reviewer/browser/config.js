export const CONFIG_STORAGE_KEY = 'ascs-reviewer-config';

export function readConfig() {
  try {
    const stored = localStorage.getItem(CONFIG_STORAGE_KEY);
    return stored ? JSON.parse(stored) : null;
  } catch (error) {
    console.warn('Unable to read saved configuration', error);
    return null;
  }
}

export function writeConfig(config) {
  localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(config));
}
