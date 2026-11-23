create extension if not exists pgcrypto;
create table if not exists public.analysis_runs (
  id uuid primary key default gen_random_uuid(),
  filename text not null,
  storage_path text not null,
  status text not null check (status in ('resolved','unsupported','ambiguous')),
  result jsonb not null,
  created_at timestamptz not null default now()
);
create index if not exists analysis_runs_created_at_idx on public.analysis_runs(created_at desc);
-- Create a private Supabase Storage bucket named policy-pdfs (or set SUPABASE_BUCKET).
-- The backend uses the service-role key; never expose it to the browser.
