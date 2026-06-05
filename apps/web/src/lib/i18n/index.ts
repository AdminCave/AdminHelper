// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable, derived, get } from 'svelte/store';
import { translations, type Language } from './dictionaries';

export type { Language } from './dictionaries';
export type TVars = Record<string, string | number | null | undefined>;

function detect(): Language {
  const stored = localStorage.getItem('adminhelper_language');
  if (stored === 'de' || stored === 'en') return stored;
  const nav = (navigator.language || '').substring(0, 2);
  return nav === 'en' ? 'en' : 'de';
}

const _language = writable<Language>(detect());

_language.subscribe((lang) => {
  localStorage.setItem('adminhelper_language', lang);
  if (typeof document !== 'undefined') {
    document.documentElement.lang = lang;
  }
});

export const language = {
  subscribe: _language.subscribe,
  set: _language.set,
};

export function setLanguage(lang: Language): void {
  _language.set(lang);
}

export function toggleLanguage(): void {
  _language.update((l) => (l === 'de' ? 'en' : 'de'));
}

function translate(lang: Language, key: string, vars?: TVars): string {
  const dict = translations[lang] ?? translations.en;
  const fallback = translations.de;
  let text = dict[key] ?? fallback[key] ?? key;
  if (vars) {
    text = text.replace(/\{(\w+)\}/g, (_, token) => {
      const v = vars[token];
      return v === undefined || v === null ? '' : String(v);
    });
  }
  return text;
}

export const t = derived(
  _language,
  ($lang) => (key: string, vars?: TVars) => translate($lang, key, vars),
);

export function tNow(key: string, vars?: TVars): string {
  return translate(get(_language), key, vars);
}
