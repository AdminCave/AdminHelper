// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// i18n engine: reactive language store + t() function with {placeholder} replacement.

import { writable, derived, get, type Readable } from 'svelte/store';
import { translations, type Language } from './dictionaries';

export type TranslateFn = (key: string, vars?: Record<string, unknown>) => string;

function isLanguage(candidate: string): candidate is Language {
  return candidate in translations;
}

export function detectBrowserLanguage(): Language {
  if (typeof navigator === 'undefined') return 'de';
  const prefix = navigator.language.toLowerCase().split('-')[0];
  return isLanguage(prefix) ? prefix : 'de';
}

export const language = writable<Language>(detectBrowserLanguage());

function translate(lang: Language, key: string, vars: Record<string, unknown> = {}): string {
  const dict = translations[lang] ?? translations.en;
  const fallback = translations.en ?? {};
  const template = dict[key] ?? fallback[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (_, token) => {
    const value = vars[token as keyof typeof vars];
    return value === undefined || value === null ? '' : String(value);
  });
}

export const t: Readable<TranslateFn> = derived(language, ($lang) => {
  return (key: string, vars?: Record<string, unknown>) => translate($lang, key, vars);
});

export function setLanguage(next: string | null | undefined): Language {
  const normalized: Language = next && isLanguage(next) ? next : 'en';
  language.set(normalized);
  if (typeof document !== 'undefined') {
    document.documentElement.lang = normalized;
  }
  return normalized;
}

export function currentLanguage(): Language {
  return get(language);
}

export function tNow(key: string, vars?: Record<string, unknown>): string {
  return translate(get(language), key, vars);
}

export type { Language } from './dictionaries';
