import { http, setTokens, clearTokens } from './client';
import type { LoginResponse, User } from './types';

export async function login(username: string, password: string): Promise<User> {
  const tokens = await http.post<LoginResponse>('/api/auth/login', { username, password });
  setTokens(tokens.access_token, tokens.refresh_token);
  return me();
}

export function logout(): void {
  clearTokens();
}

export function me(): Promise<User> {
  return http.get<User>('/api/auth/me');
}
