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

/** The language of the system: German on a German system, else English. */
export function systemLanguage(): Language {
  const language = typeof navigator !== 'undefined' ? (navigator.language ?? '') : '';
  return language.toLowerCase().startsWith('de') ? 'de' : 'en';
}

/** A valid stored language, else the system language (a fresh install stores none). */
export function resolveLanguage(stored: string | null | undefined): Language {
  return stored && isLanguage(stored) ? stored : systemLanguage();
}

export const language = writable<Language>(systemLanguage());

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
  const normalized = resolveLanguage(next);
  language.set(normalized);
  if (typeof document !== 'undefined') {
    document.documentElement.lang = normalized;
  }
  return normalized;
}

/** BCP-47 locale for Intl formatting (dates, numbers), derived from the UI language. */
export function currentLocale(): string {
  return get(language) === 'de' ? 'de-DE' : 'en-GB';
}

export function tNow(key: string, vars?: Record<string, unknown>): string {
  return translate(get(language), key, vars);
}

export type { Language } from './dictionaries';
