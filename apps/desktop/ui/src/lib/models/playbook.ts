// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Form model for Ansible playbook authoring (create/edit). The list/run wizard
// reads playbooks; this layer turns one into an editable form and back into the
// PlaybookInput the server API expects. Pure logic so it stays unit-testable.

import type { Playbook, PlaybookInput } from '$lib/api/types';
import { tNow } from '$lib/i18n';
import { parseTags, type ValidationResult } from './shared';
export { parseTags };

export interface PlaybookForm {
  id: string | null;
  name: string;
  filename: string;
  description: string;
  tags: string[];
  content: string;
}

export function emptyPlaybookForm(): PlaybookForm {
  return {
    id: null,
    name: '',
    filename: '',
    description: '',
    tags: [],
    content: '',
  };
}

export function playbookToForm(p: Playbook, content: string): PlaybookForm {
  return {
    id: p.id,
    name: p.name,
    filename: p.filename,
    description: p.description ?? '',
    tags: [...(p.tags ?? [])],
    content,
  };
}

/** Builds the PlaybookInput the server API expects. Trims text fields and
 * dedups tags; never sends the id (it routes the request). */
export function formToInput(form: PlaybookForm): PlaybookInput {
  return {
    name: form.name.trim(),
    filename: form.filename.trim(),
    description: form.description.trim(),
    tags: [...new Set(form.tags.map((t) => t.trim()).filter((t) => t.length > 0))],
    content: form.content,
  };
}

export function validatePlaybookForm(form: PlaybookForm): ValidationResult {
  if (!form.name.trim()) return { ok: false, message: tNow('ansible.edit.nameRequired') };
  if (!form.filename.trim()) return { ok: false, message: tNow('ansible.edit.filenameRequired') };
  return { ok: true };
}
