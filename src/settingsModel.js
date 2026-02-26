export function detectSystemLanguage() {
  const language = navigator.language || "";
  return language.toLowerCase().startsWith("de") ? "de" : "en";
}

export function getSettingsDefaults() {
  return {
    mode: "local",
    url: "",
    intervalMinutes: 1,
    language: detectSystemLanguage(),
    storePasswords: false,
    rdpScalingMode: "auto"
  };
}

export function getIntervalMinutes(settings) {
  const raw = Number(settings?.intervalMinutes);
  if (!Number.isFinite(raw)) {
    return 1;
  }
  return Math.max(1, Math.min(1440, Math.round(raw)));
}
