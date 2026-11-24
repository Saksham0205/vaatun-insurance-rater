'use client';

import { ChangeEvent, DragEvent, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  Check,
  Clock3,
  FileCheck2,
  FileText,
  LoaderCircle,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  UploadCloud,
} from 'lucide-react';
import { WorkspaceShell } from '../components/workspace-shell';
import { apiError, apiFetch } from '../lib/api';
import { insurerName } from '../lib/insurers';

type DocumentRow = {
  id: string;
  original_name: string;
  sha256: string;
  status: 'uploaded' | 'processing' | 'processed' | 'failed';
  uploaded_at: string;
  latest_analysis_id?: string | null;
  assessment_complete?: boolean | null;
  insurer?: string | null;
};
type Stats = { total: number; processed: number; pending: number; incomplete: number };
const emptyStats: Stats = { total: 0, processed: 0, pending: 0, incomplete: 0 };

function Status({ status, incomplete }: { status: string; incomplete?: boolean }) {
  const styles: Record<string, string> = {
    processed: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
    uploaded: 'bg-slate-50 text-slate-600 ring-slate-200',
    processing: 'bg-accent-soft text-accent ring-accent/30',
    failed: 'bg-rose-50 text-rose-700 ring-rose-200',
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span
        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[13px] font-semibold capitalize ring-1 ring-inset ${styles[status] || styles.uploaded}`}
      >
        {status === 'processing' && <LoaderCircle size={13} className="animate-spin" />}
        {status === 'processed' && <Check size={13} />}
        {status}
      </span>
      {incomplete && (
        <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[13px] font-semibold text-amber-800 ring-1 ring-inset ring-amber-200">
          Needs review
        </span>
      )}
    </span>
  );
}

export default function Home() {
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [stats, setStats] = useState<Stats>(emptyStats);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [insurer, setInsurer] = useState('all');
  const [sort, setSort] = useState<'newest' | 'oldest'>('newest');
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [analyzing, setAnalyzing] = useState('');
  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await apiFetch('/api/v1/documents?limit=100');
      if (!response.ok) throw new Error(await apiError(response));
      const body = await response.json();
      setDocs(body.documents || []);
      setStats(body.stats || emptyStats);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load your policies.');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    if (!docs.some(d => d.status === 'processing')) return;
    const timer = setInterval(() => void refresh(), 2500);
    return () => clearInterval(timer);
  }, [docs, refresh]);
  const insurers = useMemo(
    () => Array.from(new Set(docs.map(d => d.insurer).filter((v): v is string => Boolean(v)))),
    [docs],
  );
  const rows = useMemo(
    () =>
      docs
        .filter(
          d =>
            (!query ||
              `${d.original_name} ${d.insurer || ''} ${insurerName(d.insurer)}`
                .toLowerCase()
                .includes(query.toLowerCase())) &&
            (status === 'all' || d.status === status) &&
            (insurer === 'all' || d.insurer === insurer),
        )
        .sort((a, b) =>
          sort === 'newest'
            ? Date.parse(b.uploaded_at) - Date.parse(a.uploaded_at)
            : Date.parse(a.uploaded_at) - Date.parse(b.uploaded_at),
        ),
    [docs, query, status, insurer, sort],
  );
  function acceptFile(next: File | null) {
    setNotice('');
    if (!next) return;
    if (next.type !== 'application/pdf' && !next.name.toLowerCase().endsWith('.pdf')) {
      setFile(null);
      setNotice('Choose a PDF document.');
      return;
    }
    if (next.size > 25 * 1024 * 1024) {
      setFile(null);
      setNotice('The PDF must be 25 MB or smaller.');
      return;
    }
    setFile(next);
  }
  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    acceptFile(e.dataTransfer.files.item(0));
  }
  function uploadFile() {
    if (!file || busy) return;
    setBusy(true);
    setUploadProgress(0);
    setNotice('');
    const data = new FormData();
    data.append('file', file);
    const xhr = new XMLHttpRequest();
    xhr.open(
      'POST',
      `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/documents/upload`,
    );
    void import('../lib/supabase/client').then(async ({ createClient }) => {
      const { data: auth } = await createClient().auth.getSession();
      if (!auth.session) {
        window.location.assign('/login?reason=expired');
        return;
      }
      xhr.setRequestHeader('Authorization', `Bearer ${auth.session.access_token}`);
      xhr.upload.onprogress = e => {
        if (e.lengthComputable) setUploadProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => {
        void (async () => {
          try {
            const body = JSON.parse(xhr.responseText || '{}');
            if (xhr.status < 200 || xhr.status >= 300)
              throw new Error(body.detail || 'Upload failed.');
            setNotice(`Uploaded ${body.original_name}. Select Analyze in the list to rate it.`);
            setFile(null);
            await refresh();
          } catch (e) {
            setNotice(e instanceof Error ? e.message : 'Upload failed.');
          } finally {
            setBusy(false);
            setTimeout(() => setUploadProgress(0), 500);
          }
        })();
      };
      xhr.onerror = () => {
        setNotice('Upload connection failed. Check your connection and retry.');
        setBusy(false);
      };
      xhr.send(data);
    });
  }
  async function analyze(id: string) {
    if (analyzing) return;
    setAnalyzing(id);
    setError('');
    try {
      const start = await apiFetch(`/api/v1/documents/${id}/analyze`, { method: 'POST' });
      if (!start.ok) throw new Error(await apiError(start));
      const first = await start.json();
      let analysis = first.analysis;
      for (let i = 0; i < 45 && first.status === 'processing'; i++) {
        await new Promise(r => setTimeout(r, 2000));
        const next = await apiFetch(`/api/v1/analyses/${first.analysis_id}`);
        if (!next.ok) throw new Error(await apiError(next));
        analysis = await next.json();
        if (analysis.status !== 'processing' && analysis.status !== 'pending') break;
      }
      if (analysis?.status === 'completed') {
        window.location.assign(`/documents/${id}`);
        return;
      }
      if (analysis?.status === 'failed')
        throw new Error(analysis.error_message || 'Analysis failed. Retry is available.');
      setNotice('Analysis is still processing. Its status will refresh automatically.');
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis could not be started.');
      await refresh();
    } finally {
      setAnalyzing('');
    }
  }

  return (
    <WorkspaceShell>
      <div className="mx-auto max-w-[1260px]">
        <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="m-0 font-display text-[32px] font-semibold tracking-[-.02em]">
              Policies
            </h1>
            <p className="mb-0 mt-1 max-w-[560px] text-[15px] text-muted">
              Upload a policy PDF to see the commission it earns, with the source behind every
              number.
            </p>
          </div>
          <button
            onClick={() => void refresh()}
            className="inline-flex items-center gap-2 rounded-lg border border-line bg-white px-3.5 py-2 text-[14px] font-medium text-[#3F4B50] transition-colors hover:bg-canvas"
          >
            <RefreshCw size={15} className={loading ? 'animate-spin' : undefined} />
            Refresh
          </button>
        </div>

        <section
          aria-label="Policy statistics"
          className="mb-6 grid grid-cols-2 gap-3 xl:grid-cols-4"
        >
          {[
            {
              label: 'Policies',
              value: stats.total,
              note: 'Uploaded to your workspace',
              icon: FileText,
              color: 'text-muted',
              id: 'total',
            },
            {
              label: 'Analyzed',
              value: stats.processed,
              note: 'Commission worked out',
              icon: FileCheck2,
              color: 'text-emerald-600',
              id: 'processed',
            },
            {
              label: 'Waiting',
              value: stats.pending,
              note: 'Not analyzed yet',
              icon: Clock3,
              color: 'text-accent',
              id: 'pending',
            },
            {
              label: 'Needs review',
              value: stats.incomplete,
              note: 'Missing a rate-card input',
              icon: ShieldAlert,
              color: 'text-amber-600',
              id: 'incomplete',
            },
          ].map(card => {
            const Icon = card.icon;
            return (
              <div
                key={card.id}
                className="rounded-xl border border-line bg-white p-4 shadow-panel md:p-5"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[14px] font-medium text-[#3F4B50]">{card.label}</span>
                  <Icon size={18} className={card.color} />
                </div>
                <div className="mt-2 font-display text-[34px] font-semibold leading-tight tracking-[-.02em]">
                  {loading ? (
                    <span className="inline-block h-8 w-12 animate-pulse rounded bg-gray-100" />
                  ) : (
                    card.value
                  )}
                </div>
                <p className="mb-0 mt-1 text-[13px] text-muted">{card.note}</p>
              </div>
            );
          })}
        </section>

        <div className="grid items-start gap-5 2xl:grid-cols-[minmax(0,1fr)_340px]">
          <section
            id="history"
            className="overflow-hidden rounded-xl border border-line bg-white shadow-panel"
          >
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-4 md:px-5">
              <div>
                <h2 className="m-0 font-display text-[18px] font-semibold">Recent policies</h2>
                <p className="mb-0 mt-0.5 text-[13px] text-muted">
                  {loading ? 'Loading…' : `Showing ${rows.length} of ${docs.length}`}
                </p>
              </div>
            </div>
            <div className="flex flex-col gap-2 border-b border-line px-4 py-3 md:flex-row md:px-5">
              <label className="relative min-w-0 flex-1">
                <Search
                  size={16}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8A969A]"
                />
                <input
                  aria-label="Search documents"
                  placeholder="Search by document or insurer"
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                  className="h-10 w-full rounded-lg border border-line pl-9 pr-3 text-[14px] outline-none transition-shadow focus:border-accent focus:ring-4 focus:ring-accent/10"
                />
              </label>
              <select
                aria-label="Filter by analysis status"
                value={status}
                onChange={e => setStatus(e.target.value)}
                className="h-10 rounded-lg border border-line bg-white px-3 text-[14px] text-[#3F4B50]"
              >
                <option value="all">All statuses</option>
                <option value="uploaded">Uploaded</option>
                <option value="processing">Processing</option>
                <option value="processed">Processed</option>
                <option value="failed">Failed</option>
              </select>
              <select
                aria-label="Filter by insurer"
                value={insurer}
                onChange={e => setInsurer(e.target.value)}
                className="h-10 rounded-lg border border-line bg-white px-3 text-[14px] text-[#3F4B50]"
              >
                <option value="all">All insurers</option>
                {insurers.map(x => (
                  <option key={x} value={x}>
                    {insurerName(x)}
                  </option>
                ))}
              </select>
              <button
                onClick={() => setSort(sort === 'newest' ? 'oldest' : 'newest')}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-line px-3 text-[14px] text-[#3F4B50] transition-colors hover:bg-canvas"
              >
                {sort === 'newest' ? <ArrowDown size={15} /> : <ArrowUp size={15} />}
                {sort === 'newest' ? 'Newest' : 'Oldest'}
              </button>
            </div>
            {error && (
              <div
                role="alert"
                className="mx-4 mt-3 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-[14px] text-rose-700 md:mx-5"
              >
                <AlertCircle size={15} className="mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="border-b border-line bg-[#F8FAF9] text-[13px] font-medium text-muted">
                    <th className="px-5 py-3">Document</th>
                    <th className="hidden px-4 py-3 md:table-cell">Insurer</th>
                    <th className="hidden px-4 py-3 lg:table-cell">Uploaded</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-5 py-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    Array.from({ length: 4 }, (_, i) => (
                      <tr key={i} className="border-b border-line">
                        <td colSpan={5} className="px-5 py-4">
                          <div className="h-5 animate-pulse rounded bg-gray-100" />
                        </td>
                      </tr>
                    ))
                  ) : rows.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-5 py-16 text-center">
                        <div className="mx-auto mb-3 grid h-10 w-10 place-items-center rounded-xl bg-canvas text-[#8A969A]">
                          <FilesIcon />
                        </div>
                        <p className="m-0 text-[15px] font-semibold">
                          {docs.length ? 'No matching documents' : 'No policies yet'}
                        </p>
                        <p className="mb-0 mt-1 text-[13px] text-muted">
                          {docs.length
                            ? 'Try a different search or filter.'
                            : 'Upload a policy PDF to get started.'}
                        </p>
                      </td>
                    </tr>
                  ) : (
                    rows.map(d => (
                      <tr
                        key={d.id}
                        className="group border-b border-line last:border-0 hover:bg-[#F8FAF9]"
                      >
                        <td className="px-5 py-3.5">
                          <Link
                            href={`/documents/${d.id}`}
                            className="flex items-center gap-3 text-inherit no-underline"
                          >
                            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-canvas text-muted transition-colors group-hover:bg-accent-soft group-hover:text-accent">
                              <FileText size={17} />
                            </span>
                            <span className="min-w-0">
                              <span className="block max-w-[36vw] truncate text-[14px] font-semibold transition-colors group-hover:text-accent sm:max-w-[48vw] md:max-w-[380px] 2xl:max-w-[520px]">
                                {d.original_name}
                              </span>
                              <span className="block text-[13px] text-muted md:hidden">
                                {insurerName(d.insurer) || 'Insurer not identified'}
                              </span>
                            </span>
                          </Link>
                        </td>
                        <td className="hidden whitespace-nowrap px-4 py-3.5 text-[14px] text-[#3F4B50] md:table-cell">
                          {insurerName(d.insurer) || (
                            <span className="text-muted">Not identified</span>
                          )}
                        </td>
                        <td className="hidden whitespace-nowrap px-4 py-3.5 text-[14px] text-muted lg:table-cell">
                          {new Date(d.uploaded_at).toLocaleDateString(undefined, {
                            day: 'numeric',
                            month: 'short',
                            year: 'numeric',
                          })}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3.5">
                          <Status status={d.status} incomplete={d.assessment_complete === false} />
                        </td>
                        <td className="px-5 py-3.5 text-right">
                          {d.status === 'uploaded' || d.status === 'failed' ? (
                            <button
                              disabled={Boolean(analyzing)}
                              onClick={() => void analyze(d.id)}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-accent/30 bg-white px-3 py-1.5 text-[14px] font-semibold text-accent transition-colors hover:bg-accent-soft disabled:opacity-50"
                            >
                              {analyzing === d.id ? (
                                <LoaderCircle size={14} className="animate-spin" />
                              ) : null}
                              {analyzing === d.id
                                ? 'Analyzing'
                                : d.status === 'failed'
                                  ? 'Retry'
                                  : 'Analyze'}
                            </button>
                          ) : (
                            <Link
                              href={`/documents/${d.id}`}
                              className="inline-flex items-center gap-1 text-[14px] font-semibold text-accent no-underline hover:underline"
                            >
                              {d.status === 'processed' ? 'Open' : 'View status'}
                              <ArrowUpRight size={14} />
                            </Link>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section
            id="upload"
            className="order-first scroll-mt-24 rounded-xl border border-line bg-white p-4 shadow-panel md:p-5 2xl:order-none"
          >
            <div className="mb-4 flex items-start justify-between">
              <div>
                <h2 className="m-0 font-display text-[18px] font-semibold">Upload a policy</h2>
                <p className="mb-0 mt-0.5 text-[13px] text-muted">PDF, up to 25 MB</p>
              </div>
            </div>
            <label
              onDragOver={e => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={`dropzone group/drop flex min-h-[150px] 2xl:min-h-[190px] cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-5 text-center transition-colors duration-200 ${dragging ? 'border-accent bg-accent-soft' : file ? 'border-accent/40 bg-accent-soft/50' : 'border-line bg-[#F8FAF9] hover:border-accent/40'}`}
            >
              <input
                type="file"
                accept="application/pdf,.pdf"
                className="sr-only"
                onChange={(e: ChangeEvent<HTMLInputElement>) =>
                  acceptFile(e.target.files?.[0] || null)
                }
              />
              <span
                className={`mb-3 grid h-12 w-12 place-items-center rounded-full bg-white text-accent shadow-sm transition-transform duration-200 ${dragging ? '-translate-y-1 scale-110' : 'group-hover/drop:-translate-y-0.5'}`}
              >
                {file ? <FileCheck2 size={22} /> : <UploadCloud size={22} />}
              </span>
              <span className="max-w-full break-all text-[14px] font-semibold">
                {file?.name || (dragging ? 'Drop to add it' : 'Drag a PDF here')}
              </span>
              <span className="mt-1 text-[13px] text-muted">
                {file ? (
                  <>
                    Ready to upload. <span className="font-medium text-accent">Choose another</span>
                  </>
                ) : (
                  <>
                    or <span className="font-medium text-accent">browse your files</span>
                  </>
                )}
              </span>
            </label>
            {busy && (
              <div className="mt-3">
                <div className="mb-1 flex justify-between text-[13px] text-muted">
                  <span>Uploading</span>
                  <span>{uploadProgress}%</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-gray-100">
                  <div
                    className="h-full rounded-full bg-accent transition-all"
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
              </div>
            )}
            {notice && (
              <p
                role="status"
                className="mt-3 animate-settle rounded-lg bg-emerald-50 px-3 py-2.5 text-[14px] text-emerald-800"
              >
                {notice}
              </p>
            )}
            {error && (
              <p
                role="alert"
                className="mt-3 animate-settle rounded-lg bg-rose-50 px-3 py-2.5 text-[14px] text-rose-700"
              >
                {error}
              </p>
            )}
            <button
              disabled={!file || busy}
              onClick={uploadFile}
              className="mt-3 flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-accent text-[14px] font-semibold text-white transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-45"
            >
              {busy ? (
                <LoaderCircle size={16} className="animate-spin" />
              ) : (
                <UploadCloud size={16} />
              )}
              Upload PDF
            </button>
            <p className="mb-0 mt-3 flex items-center justify-center gap-1.5 text-[13px] text-muted">
              <ShieldCheck size={14} />
              Only you can see your uploads
            </p>
          </section>
        </div>
      </div>
    </WorkspaceShell>
  );
}

function FilesIcon() {
  return <FileText size={18} />;
}
