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
    rdpScalingMode: "auto",
    rdpWindowMode: "fit",
    rdpCustomSize: "1920x1080",
    rdpPerformanceProfile: "auto",
    allowSelfSignedCerts: false,
    serverUrl: ""
  };
}

export const RDP_WINDOW_MODES = ["fit", "fullscreen", "multimon", "custom"];
export const RDP_PERFORMANCE_PROFILES = ["auto", "lan", "broadband", "low"];
export const RDP_CUSTOM_SIZE_PATTERN = /^\d{3,5}x\d{3,5}$/;

export function getIntervalMinutes(settings) {
  const raw = Number(settings?.intervalMinutes);
  if (!Number.isFinite(raw)) {
    return 1;
  }
  return Math.max(1, Math.min(1440, Math.round(raw)));
}
