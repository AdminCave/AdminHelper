import { http } from './client';
import type { Connection } from './types';

export function list(): Promise<Connection[]> {
  return http.get<Connection[]>('/api/connections');
}

export function create(data: Partial<Connection>): Promise<Connection> {
  return http.post<Connection>('/api/connections', data);
}

export function update(id: string, data: Partial<Connection>): Promise<Connection> {
  return http.put<Connection>(`/api/connections/${id}`, data);
}

export function remove(id: string): Promise<void> {
  return http.del<void>(`/api/connections/${id}`);
}
