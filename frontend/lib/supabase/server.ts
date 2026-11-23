import { createServerClient } from '@supabase/ssr';
import { cookies } from 'next/headers';

export async function createClient() {
  const jar = await cookies();
  return createServerClient(process.env.NEXT_PUBLIC_SUPABASE_URL || 'http://127.0.0.1:54321', process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || 'local-unconfigured-publishable-key', {
    cookies: { getAll: () => jar.getAll(), setAll: (items) => { try { items.forEach(({ name, value, options }) => jar.set(name, value, options)); } catch { /* refreshed by middleware */ } } },
  });
}
