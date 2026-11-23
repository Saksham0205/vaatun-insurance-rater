create extension if not exists pgcrypto;

create table if not exists public.users (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.users (id, email)
  values (new.id, new.email)
  on conflict (id) do update set email = excluded.email;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created_vaatun on auth.users;
create trigger on_auth_user_created_vaatun
  after insert or update of email on auth.users
  for each row execute procedure public.handle_new_user();

create table if not exists public.documents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  original_name text not null,
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  storage_path text not null unique,
  byte_count bigint not null check (byte_count > 0),
  mime_type text not null default 'application/pdf' check (mime_type = 'application/pdf'),
  status text not null default 'uploaded' check (status in ('uploaded','processing','processed','failed')),
  uploaded_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  error_message text,
  unique (user_id, sha256)
);

create table if not exists public.analyses (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.documents(id) on delete cascade,
  user_id uuid not null references public.users(id) on delete cascade,
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  pipeline_version text not null,
  status text not null default 'pending' check (status in ('pending','processing','completed','failed')),
  overall_status text check (overall_status in ('resolved','not_applicable','unsupported','ambiguous')),
  assessment_complete boolean not null default false,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  error_message text,
  result_json jsonb,
  unique (document_id, document_sha256, pipeline_version)
);

create table if not exists public.extracted_facts (
  id uuid primary key default gen_random_uuid(),
  analysis_id uuid not null references public.analyses(id) on delete cascade,
  field_name text not null,
  value jsonb,
  page integer check (page is null or page > 0),
  confidence double precision check (confidence is null or (confidence >= 0 and confidence <= 1)),
  extracted_text text,
  source_ref jsonb,
  is_missing boolean not null default false,
  is_conflict boolean not null default false,
  is_low_confidence boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists public.component_decisions (
  id uuid primary key default gen_random_uuid(),
  analysis_id uuid not null references public.analyses(id) on delete cascade,
  component text not null check (component in ('OD','TP')),
  status text not null check (status in ('resolved','not_applicable','unsupported','ambiguous')),
  applicable boolean not null,
  rate_percent numeric,
  commission_amount numeric,
  premium_basis numeric,
  rate_basis text,
  selected_conditions jsonb not null default '{}'::jsonb,
  calculation text,
  issues jsonb not null default '[]'::jsonb,
  unique (analysis_id, component)
);

create table if not exists public.evidence_references (
  id uuid primary key default gen_random_uuid(),
  analysis_id uuid not null references public.analyses(id) on delete cascade,
  component_decision_id uuid references public.component_decisions(id) on delete cascade,
  extracted_fact_id uuid references public.extracted_facts(id) on delete cascade,
  source_kind text not null check (source_kind in ('policy','rate_card','other')),
  source_file text not null,
  source_sha256 text,
  sheet text,
  cell text,
  page integer check (page is null or page > 0),
  table_number integer,
  row_number integer,
  column_number integer,
  role text not null default 'support',
  created_at timestamptz not null default now(),
  check (component_decision_id is not null or extracted_fact_id is not null)
);

create index if not exists documents_user_uploaded_idx on public.documents(user_id, uploaded_at desc);
create index if not exists documents_user_status_idx on public.documents(user_id, status);
create index if not exists analyses_user_created_idx on public.analyses(user_id, created_at desc);
create index if not exists analyses_document_status_idx on public.analyses(document_id, status, updated_at desc);
create index if not exists facts_analysis_field_idx on public.extracted_facts(analysis_id, field_name);
create index if not exists decisions_analysis_idx on public.component_decisions(analysis_id);
create index if not exists evidence_analysis_idx on public.evidence_references(analysis_id);

alter table public.users enable row level security;
alter table public.documents enable row level security;
alter table public.analyses enable row level security;
alter table public.extracted_facts enable row level security;
alter table public.component_decisions enable row level security;
alter table public.evidence_references enable row level security;

drop policy if exists users_read_self on public.users;
create policy users_read_self on public.users for select to authenticated
  using (id = (select auth.uid()));
drop policy if exists users_update_self on public.users;
create policy users_update_self on public.users for update to authenticated
  using (id = (select auth.uid())) with check (id = (select auth.uid()));

drop policy if exists documents_owner_all on public.documents;
create policy documents_owner_all on public.documents for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
drop policy if exists analyses_owner_read on public.analyses;
create policy analyses_owner_read on public.analyses for select to authenticated
  using (user_id = (select auth.uid()));
drop policy if exists facts_owner_read on public.extracted_facts;
create policy facts_owner_read on public.extracted_facts for select to authenticated
  using (exists (select 1 from public.analyses a where a.id = analysis_id and a.user_id = (select auth.uid())));
drop policy if exists decisions_owner_read on public.component_decisions;
create policy decisions_owner_read on public.component_decisions for select to authenticated
  using (exists (select 1 from public.analyses a where a.id = analysis_id and a.user_id = (select auth.uid())));
drop policy if exists evidence_owner_read on public.evidence_references;
create policy evidence_owner_read on public.evidence_references for select to authenticated
  using (exists (select 1 from public.analyses a where a.id = analysis_id and a.user_id = (select auth.uid())));

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('policy-pdfs', 'policy-pdfs', false, 26214400, array['application/pdf'])
on conflict (id) do update set public = false, file_size_limit = 26214400,
  allowed_mime_types = array['application/pdf'];

drop policy if exists policy_pdfs_owner_read on storage.objects;
create policy policy_pdfs_owner_read on storage.objects for select to authenticated
  using (bucket_id = 'policy-pdfs' and (storage.foldername(name))[1] = (select auth.uid())::text);
drop policy if exists policy_pdfs_owner_insert on storage.objects;
create policy policy_pdfs_owner_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'policy-pdfs' and (storage.foldername(name))[1] = (select auth.uid())::text);
drop policy if exists policy_pdfs_owner_update on storage.objects;
create policy policy_pdfs_owner_update on storage.objects for update to authenticated
  using (bucket_id = 'policy-pdfs' and (storage.foldername(name))[1] = (select auth.uid())::text)
  with check (bucket_id = 'policy-pdfs' and (storage.foldername(name))[1] = (select auth.uid())::text);
drop policy if exists policy_pdfs_owner_delete on storage.objects;
create policy policy_pdfs_owner_delete on storage.objects for delete to authenticated
  using (bucket_id = 'policy-pdfs' and (storage.foldername(name))[1] = (select auth.uid())::text);
