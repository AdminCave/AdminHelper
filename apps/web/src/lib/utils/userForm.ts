// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import type { User, UserCreate, UserUpdate } from '$lib/api/types';

// The user dialog's fields; an empty password when editing keeps the current one.
export interface UserForm {
  username: string;
  password: string;
  isAdmin: boolean;
  serverIds: string[];
}

// The i18n key of what is missing, or null if the form can be sent.
export function validateUserForm(
  form: UserForm,
  editing: User | null,
): 'modal.user.passwordRequired' | null {
  return !editing && !form.password ? 'modal.user.passwordRequired' : null;
}

export function userCreatePayload(form: UserForm): UserCreate {
  return {
    username: form.username.trim(),
    password: form.password,
    is_admin: form.isAdmin,
    server_ids: [...form.serverIds],
  };
}

export function userUpdatePayload(form: UserForm): UserUpdate {
  const payload: UserUpdate = { is_admin: form.isAdmin, server_ids: [...form.serverIds] };
  if (form.password) payload.password = form.password;
  return payload;
}

// A new password for the signed-in account: the server then ends every session of it
// (tokens_valid_after), so the dialog logs out at once instead of failing at the next click.
export function endsOwnSession(
  form: UserForm,
  editing: User | null,
  currentUserId: number | undefined,
): boolean {
  return !!form.password && !!editing && editing.id === currentUserId;
}
