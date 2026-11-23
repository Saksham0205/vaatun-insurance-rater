import { createClient } from './supabase/client';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function apiFetch(path: string, init: RequestInit = {}) {
  const supabase = createClient();
  const { data } = await supabase.auth.getSession();
  if (!data.session) {
    if (typeof window !== 'undefined') window.location.assign('/login?reason=expired');
    throw new Error('Your session has ended. Sign in again to continue.');
  }
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${data.session.access_token}`);
  const response = await fetch(`${API}${path}`, { ...init, headers, cache: 'no-store' });
  if (response.status === 401) {
    await supabase.auth.signOut();
    if (typeof window !== 'undefined') window.location.assign('/login?reason=expired');
    throw new Error('Your session expired. Sign in again to continue.');
  }
  return response;
}

export async function apiError(response: Response) {
  try { const body = await response.json(); return body.detail || body.message || `Request failed (${response.status})`; }
  catch { return `Request failed (${response.status})`; }
}
