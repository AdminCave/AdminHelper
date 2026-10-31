// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import {
  endsOwnSession,
  userCreatePayload,
  userUpdatePayload,
  validateUserForm,
  type UserForm,
} from './userForm';
import type { User } from '$lib/api/types';

const SELF: User = { id: 1, username: 'admin', is_admin: true, server_ids: [] };
const OTHER: User = { id: 2, username: 'alice', is_admin: false, server_ids: ['s1'] };

function form(over: Partial<UserForm>): UserForm {
  return { username: '', password: '', isAdmin: false, serverIds: [], ...over };
}

describe('validateUserForm', () => {
  it('a new user needs a password', () => {
    expect(validateUserForm(form({ username: 'bob' }), null)).toBe('modal.user.passwordRequired');
    expect(validateUserForm(form({ username: 'bob', password: 'pw' }), null)).toBeNull();
  });

  it('an edit without a password keeps the current one', () => {
    expect(validateUserForm(form({}), OTHER)).toBeNull();
  });
});

describe('userCreatePayload', () => {
  it('trims the name and sends the servers ticked', () => {
    expect(
      userCreatePayload(form({ username: '  alice  ', password: 'pw', serverIds: ['s2'] })),
    ).toStrictEqual({ username: 'alice', password: 'pw', is_admin: false, server_ids: ['s2'] });
  });
});

describe('userUpdatePayload', () => {
  it('without a password: no password key', () => {
    expect(userUpdatePayload(form({ serverIds: ['s2'] }))).toStrictEqual({
      is_admin: false,
      server_ids: ['s2'],
    });
  });

  it('with a password: the password goes along', () => {
    expect(userUpdatePayload(form({ isAdmin: true, password: 'new-pw' }))).toStrictEqual({
      is_admin: true,
      server_ids: [],
      password: 'new-pw',
    });
  });
});

describe('endsOwnSession (R-0652)', () => {
  it('a new password for the signed-in account ends its session', () => {
    expect(endsOwnSession(form({ password: 'new-pw' }), SELF, SELF.id)).toBe(true);
  });

  it('the own account without a password, another account with one, or a new user: no', () => {
    expect(endsOwnSession(form({}), SELF, SELF.id)).toBe(false);
    expect(endsOwnSession(form({ password: 'new-pw' }), OTHER, SELF.id)).toBe(false);
    expect(endsOwnSession(form({ password: 'pw' }), null, SELF.id)).toBe(false);
  });
});
