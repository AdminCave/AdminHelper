/* AdminHelper – i18n Helper Functions */
'use strict';

let currentLanguage = 'de';

function detectLanguage() {
  const stored = localStorage.getItem('srm_language');
  if (stored && translations[stored]) return stored;
  const nav = (navigator.language || '').substring(0, 2);
  return translations[nav] ? nav : 'de';
}

function t(key, vars) {
  const dict = translations[currentLanguage] || translations.en;
  const fallback = translations.de || {};
  let text = dict[key] || fallback[key] || key;
  if (vars) {
    text = text.replace(/\{(\w+)\}/g, (_, token) => {
      const value = vars[token];
      return value === undefined || value === null ? '' : String(value);
    });
  }
  return text;
}

function applyTranslations() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    if (key) el.textContent = t(key);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.dataset.i18nPlaceholder;
    if (key) el.setAttribute('placeholder', t(key));
  });
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    const key = el.dataset.i18nHtml;
    if (key) el.innerHTML = t(key);
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.dataset.i18nTitle;
    if (key) el.setAttribute('title', t(key));
  });
}

function setLanguage(lang) {
  const normalized = translations[lang] ? lang : 'de';
  currentLanguage = normalized;
  localStorage.setItem('srm_language', normalized);
  document.documentElement.lang = normalized;
  applyTranslations();
}

// Initialize on load
currentLanguage = detectLanguage();
document.documentElement.lang = currentLanguage;
