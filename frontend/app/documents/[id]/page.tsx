'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  FileText,
  LoaderCircle,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  XCircle,
} from 'lucide-react';
import { WorkspaceShell } from '../../../components/workspace-shell';
import { apiError, apiFetch } from '../../../lib/api';
import { RatingReview } from '../../../components/rating-review';
import { insurerName } from '../../../lib/insurers';

type Fact = {
  value: any;
  page?: number | null;
  confidence?: number | null;
  text?: string;
  source?: Record<string, any>;
};
type Decision = {
  status: string;
  applicable?: boolean;
  rate_percent?: string | null;
  commission_amount?: string | null;
  premium_basis?: string | null;
  rate_basis?: string | null;
  selected_conditions?: Record<string, any>;
  calculation?: string | null;
  evidence?: Record<string, any>[];
  issues?: string[];
};
const MAX_POLL_MS = 11 * 60 * 1000; // just past the backend's 10-minute stale window
const fields: [string, string][] = [
  ['insurer', 'Insurer'],
  ['previous_insurer', 'Previous insurer'],
  ['policy_type', 'Policy type'],
  ['make_model', 'Vehicle'],
  ['registration_number', 'Registration'],
  ['fuel', 'Fuel'],
  ['engine_cc', 'Engine capacity'],
  ['manufacture_year', 'Manufacture year'],
  ['registration_year', 'Registration year'],
  ['rto', 'RTO'],
  ['state', 'State'],
  ['policy_start_date', 'Policy start'],
  ['od_premium', 'OD premium'],
  ['tp_premium', 'TP premium'],
  ['net_premium', 'Net premium'],
  ['ncb_percent', 'NCB discount'],
  ['business_type', 'Business type'],
  ['add_ons', 'Add-ons'],
];
const fieldLabels = Object.fromEntries(fields);
/** Human label for a fact key, e.g. `engine_cc` → `Engine capacity`. */
function labelFor(key: string) {
  const label = fieldLabels[key] ?? key.replaceAll('_', ' ');
  return label.charAt(0).toUpperCase() + label.slice(1);
}
function display(value: any, field: string) {
  if (value === null || value === undefined || value === '') return 'Not extracted';
  if (field === 'insurer') return insurerName(String(value));
  if (field === 'engine_cc') return `${value} cc`;
  if (field === 'ncb_percent') return `${value}%`;
  if (['od_premium', 'tp_premium', 'net_premium'].includes(field))
    return `₹${Number(value).toLocaleString('en-IN')}`;
  return String(value);
}
function confidence(value: number | undefined | null) {
  return value == null ? 'Confidence unavailable' : `${Math.round(value * 100)}% confidence`;
}

export default function AnalysisDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [document, setDocument] = useState<any>(null);
  const [analysis, setAnalysis] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retrying, setRetrying] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await apiFetch(`/api/v1/documents/${id}`);
      if (!response.ok) throw new Error(await apiError(response));
      const doc = await response.json();
      setDocument(doc);
      const latestId = doc.latest_analysis_id || doc.analyses?.[0]?.id;
      if (latestId) {
        const saved = await apiFetch(`/api/v1/analyses/${latestId}`);
        if (saved.ok) setAnalysis(await saved.json());
        else throw new Error(await apiError(saved));
      } else setAnalysis(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to load this policy.');
    } finally {
      setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);
  // Poll while the analysis runs, but never forever: the backend marks a dead run failed after its stale window.
  const processing = analysis
    ? analysis.status === 'processing'
    : document?.status === 'processing';
  const [pollTimedOut, setPollTimedOut] = useState(false);
  useEffect(() => {
    if (!processing) {
      setPollTimedOut(false);
      return;
    }
    const started = Date.now();
    const timer = setInterval(() => {
      if (Date.now() - started > MAX_POLL_MS) {
        clearInterval(timer);
        setPollTimedOut(true);
        return;
      }
      void load();
    }, 2500);
    return () => clearInterval(timer);
  }, [processing, load]);
  async function retry(force = false) {
    setRetrying(true);
    setError('');
    try {
      const response = await apiFetch(
        `/api/v1/documents/${id}/analyze${force ? '?force=true' : ''}`,
        { method: 'POST' },
      );
      if (!response.ok) throw new Error(await apiError(response));
      const body = await response.json();
      if (body.analysis) setAnalysis(body.analysis);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Retry failed.');
    } finally {
      setRetrying(false);
    }
  }
  async function deletePolicy() {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setDeleting(true);
    setError('');
    try {
      const response = await apiFetch(`/api/v1/documents/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(await apiError(response));
      router.replace('/');
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Deletion failed.');
      setConfirmDelete(false);
    } finally {
      setDeleting(false);
    }
  }
  if (loading && !document)
    return (
      <WorkspaceShell>
        <div className="h-40 animate-pulse rounded-xl border border-line bg-white" />
      </WorkspaceShell>
    );
  if (error && !document)
    return (
      <WorkspaceShell>
        <div className="rounded-xl border border-rose-200 bg-white p-8">
          <h1 className="m-0 font-display text-[22px] font-semibold">Could not open policy</h1>
          <p role="alert" className="mt-2 text-[14px] text-rose-700">
            {error}
          </p>
          <Link href="/" className="text-[13px] font-semibold text-accent">
            Back to policies
          </Link>
        </div>
      </WorkspaceShell>
    );
  const result = analysis?.result || document?.analyses?.[0]?.result_json;
  const facts: Record<string, Fact> = result?.facts || {};
  const decisions: Record<string, Decision> = result?.decisions || {};
  const conflicts: Record<string, Fact[]> = result?.conflicts || {};
  const low: Record<string, Fact[]> = result?.low_confidence || {};
  const missing: string[] = result?.missing_or_uncertain || [];
  const isIncomplete =
    result?.assessment_status !== 'complete' || analysis?.assessment_complete === false;
  return (
    <WorkspaceShell>
      <div className="mx-auto max-w-[1190px]">
        <Link
          href="/"
          className="group mb-5 inline-flex items-center gap-2 text-[14px] text-muted no-underline hover:text-accent"
        >
          <ArrowLeft size={16} className="transition-transform group-hover:-translate-x-0.5" />
          All policies
        </Link>
        <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-white text-accent shadow-panel ring-1 ring-line">
              <FileText size={20} />
            </div>
            <div className="min-w-0">
              <h1 className="m-0 max-w-[760px] break-all font-display text-[28px] font-semibold leading-tight tracking-[-.02em]">
                {document?.original_name}
              </h1>
              <p className="mb-0 mt-1 break-all text-[12px] text-[#8A969A]">
                SHA-256 {document?.sha256}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            {analysis?.status === 'completed' && (
              <button
                disabled={retrying || deleting}
                onClick={() => void retry(true)}
                title="Read the PDF again"
                className="inline-flex items-center gap-2 rounded-lg border border-line bg-white px-3.5 py-2 text-[14px] font-semibold text-[#3F4B50] transition-colors hover:bg-canvas disabled:opacity-50"
              >
                {retrying ? (
                  <LoaderCircle size={15} className="animate-spin" />
                ) : (
                  <RefreshCw size={15} />
                )}
                Re-run extraction
              </button>
            )}
            {analysis?.status === 'failed' && (
              <button
                disabled={retrying || deleting}
                onClick={() => void retry()}
                className="inline-flex items-center gap-2 rounded-lg bg-accent px-3.5 py-2 text-[14px] font-semibold text-white transition-colors hover:bg-accent-strong disabled:opacity-50"
              >
                {retrying ? (
                  <LoaderCircle size={15} className="animate-spin" />
                ) : (
                  <RefreshCw size={15} />
                )}
                Retry analysis
              </button>
            )}
            <button
              disabled={deleting || analysis?.status === 'processing'}
              onClick={() => void deletePolicy()}
              className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-[14px] font-semibold transition-colors disabled:opacity-50 ${confirmDelete ? 'bg-rose-600 text-white hover:bg-rose-700' : 'border border-rose-200 bg-white text-rose-700 hover:bg-rose-50'}`}
            >
              {deleting ? (
                <LoaderCircle size={15} className="animate-spin" />
              ) : (
                <Trash2 size={15} />
              )}{' '}
              {confirmDelete ? 'Delete permanently' : 'Delete policy'}
            </button>
            {confirmDelete && (
              <button
                disabled={deleting}
                onClick={() => setConfirmDelete(false)}
                className="rounded-lg border border-line bg-white px-3.5 py-2 text-[14px] font-semibold text-muted transition-colors hover:bg-canvas"
              >
                Cancel
              </button>
            )}
            <button
              aria-label="Refresh analysis"
              title="Refresh"
              onClick={() => void load()}
              className="rounded-lg border border-line bg-white p-2.5 text-muted transition-colors hover:bg-canvas hover:text-ink"
            >
              <RefreshCw size={16} className={loading ? 'animate-spin' : undefined} />
            </button>
          </div>
        </div>
        {error && (
          <div
            role="alert"
            className="mb-4 animate-settle rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-[14px] text-rose-700"
          >
            {error}
          </div>
        )}
        {analysis?.status === 'processing' && (
          <div
            role="status"
            className="mb-4 flex items-center gap-3 rounded-xl border border-accent/30 bg-accent-soft px-4 py-3 text-[14px] text-accent-strong"
          >
            <LoaderCircle size={18} className="shrink-0 animate-spin" />
            <span>
              <b>Reading the policy</b>
              <span className="ml-2 text-accent">
                {pollTimedOut
                  ? 'This is taking longer than usual. Refresh to check again. A run that stalls is marked failed, so you can retry it.'
                  : 'This page updates on its own when the analysis finishes.'}
              </span>
            </span>
          </div>
        )}
        {analysis?.status === 'failed' && (
          <div className="mb-4 flex items-start gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-[14px] text-rose-800">
            <XCircle size={18} className="mt-0.5 shrink-0" />
            <div>
              <b>Analysis failed</b>
              <p className="mb-0 mt-1">
                {analysis.error_message ||
                  'The analysis stopped before finishing. Select Retry analysis to run it again.'}
              </p>
            </div>
          </div>
        )}
        {isIncomplete && analysis?.status === 'completed' && (
          <div className="mb-4 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-[14px] text-amber-900">
            <AlertTriangle size={18} className="mt-0.5 shrink-0" />
            <div>
              <b>Assessment incomplete</b>
              <p className="mb-0 mt-1 leading-6">
                The rate card needs a value this PDF doesn&rsquo;t print, or a premium is missing.
                Add it under{' '}
                <a
                  href="#review"
                  className="font-semibold text-amber-900 underline-offset-2 hover:underline"
                >
                  Review rating inputs
                </a>{' '}
                and the commission is calculated. Nothing is estimated.
              </p>
            </div>
          </div>
        )}
        <section
          aria-label="Summary"
          className="mb-6 grid overflow-hidden rounded-xl border border-line bg-white shadow-panel md:grid-cols-[repeat(3,minmax(0,1fr))_minmax(0,1.4fr)]"
        >
          <Meta
            label="Insurer"
            value={insurerName(facts.insurer?.value || document?.insurer) || 'Not identified'}
          />
          <Meta label="Policy type" value={facts.policy_type?.value || 'Not identified'} />
          <Meta
            label="Assessment"
            value={
              analysis?.status === 'completed'
                ? isIncomplete
                  ? 'Needs review'
                  : 'Complete'
                : analysis?.status === 'failed'
                  ? 'Failed'
                  : analysis?.status === 'processing'
                    ? 'Processing'
                    : 'Not analyzed'
            }
            tone={
              analysis?.status === 'completed'
                ? isIncomplete
                  ? 'text-amber-700'
                  : 'text-emerald-700'
                : undefined
            }
          />
          <div className="flex flex-col justify-center border-t border-line bg-accent-soft/60 px-5 py-4 md:border-l md:border-t-0">
            <p className="m-0 text-[13px] font-medium text-accent-strong">Total commission</p>
            <p
              key={String(result?.totals?.commission_total)}
              data-testid="commission-total"
              className="m-0 mt-0.5 animate-settle font-display text-[34px] font-semibold leading-tight tracking-[-.02em] text-accent"
            >
              {result?.totals?.commission_total != null
                ? `₹${Number(result.totals.commission_total).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                : '—'}
            </p>
          </div>
        </section>
        <h2 className="mb-3 mt-0 font-display text-[20px] font-semibold">
          Commission by component
        </h2>
        <div className="mb-5 grid gap-4 xl:grid-cols-2">
          <DecisionCard name="Own Damage" code="OD" decision={decisions.OD} />
          <DecisionCard name="Third Party" code="TP" decision={decisions.TP} />
        </div>
        {analysis?.status === 'completed' && (
          <section
            id="review"
            className="mb-5 scroll-mt-20 rounded-xl border border-line bg-white shadow-panel"
          >
            <SectionTitle
              title="Review rating inputs"
              note="Supply or correct what the rate card selects on, then recalculate. The PDF isn't read again."
            />
            <div className="pt-4">
              <RatingReview analysisId={analysis.id} result={result} onUpdated={setAnalysis} />
            </div>
          </section>
        )}
        <section className="mb-5 rounded-xl border border-line bg-white shadow-panel">
          <SectionTitle
            title="Extracted policy information"
            note="Each value shows the page it was read from and how confident the read was."
          />
          <div className="grid grid-cols-1 divide-y divide-line sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-3">
            {fields.map(([key, label]) => {
              const fact = facts[key];
              const candidates = conflicts[key] || [];
              const uncertain = low[key] || [];
              const value = fact?.value;
              return (
                <div
                  key={key}
                  className="border-b border-line px-5 py-3.5 sm:[&:nth-child(2n)]:border-l lg:[&:nth-child(2n)]:border-l-0 lg:[&:nth-child(3n+2)]:border-l lg:[&:nth-child(3n)]:border-l"
                >
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <span className="text-[13px] font-medium text-muted">{label}</span>
                    {candidates.length > 0 ? (
                      <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[12px] font-semibold text-rose-700">
                        Conflict
                      </span>
                    ) : uncertain.length > 0 ? (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[12px] font-semibold text-amber-800">
                        Low confidence
                      </span>
                    ) : null}
                  </div>
                  {candidates.length > 0 ? (
                    <div className="space-y-1">
                      {candidates.map((c, i) => (
                        <p key={i} className="m-0 text-[13px] font-semibold text-rose-800">
                          {display(c.value, key)}{' '}
                          <span className="font-normal text-rose-700/70">· p.{c.page ?? '?'}</span>
                        </p>
                      ))}
                    </div>
                  ) : (
                    <p
                      className={`m-0 break-words text-[15px] font-semibold ${value == null ? 'font-normal text-[#8A969A]' : 'text-ink'}`}
                    >
                      {display(value, key)}
                    </p>
                  )}
                  <div className="mt-1 text-[12px] text-[#8A969A]">
                    {fact
                      ? `Page ${fact.page ?? '—'} · ${confidence(fact.confidence)}`
                      : uncertain[0]
                        ? `Page ${uncertain[0].page ?? '—'} · ${confidence(uncertain[0].confidence)}`
                        : 'No verified source found'}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
        <section className="mb-5 rounded-xl border border-line bg-white shadow-panel">
          <SectionTitle
            title="Extraction quality"
            note="Values that conflict or can't be read are listed here, never guessed."
          />
          <div className="grid gap-5 px-5 pb-5 lg:grid-cols-2">
            <div>
              <h3 className="mb-2 flex items-center gap-2 text-[13px] font-semibold">
                <AlertTriangle size={14} className="text-amber-600" />
                Missing fields
              </h3>
              {missing.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {missing.map(x => (
                    <span key={x} className="rounded-lg bg-canvas px-2 py-1 text-[12px] text-muted">
                      {x.replaceAll('_', ' ')}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-[13px] text-muted">No missing-field warnings.</p>
              )}
              <h3 className="mb-2 mt-5 flex items-center gap-2 text-[13px] font-semibold">
                <ShieldAlert size={14} className="text-rose-600" />
                Conflicting candidates
              </h3>
              {Object.keys(conflicts).length ? (
                Object.entries(conflicts).map(([key, list]) => (
                  <div
                    key={key}
                    className="mb-2 rounded-lg border border-rose-100 bg-rose-50/50 p-2.5"
                  >
                    <p className="m-0 mb-1 text-[13px] font-semibold text-rose-800">
                      {labelFor(key)}
                    </p>
                    {list.map((item, i) => (
                      <p key={i} className="m-0 mt-1 text-[13px] text-rose-800">
                        {String(item.value)} · page {item.page ?? '—'} ·{' '}
                        {confidence(item.confidence)}
                      </p>
                    ))}
                  </div>
                ))
              ) : (
                <p className="text-[13px] text-muted">No conflicting candidates found.</p>
              )}
              {Object.keys(low).length > 0 && (
                <>
                  <h3 className="mb-2 mt-5 text-[13px] font-semibold text-amber-800">
                    Low-confidence extractions
                  </h3>
                  {Object.entries(low).map(([key, list]) => (
                    <p key={key} className="text-[13px] text-amber-800">
                      {labelFor(key)}:{' '}
                      {list
                        .map(
                          x =>
                            `${String(x.value)} (p.${x.page ?? '?'}, ${confidence(x.confidence)})`,
                        )
                        .join('; ')}
                    </p>
                  ))}
                </>
              )}
            </div>
            <div>
              <h3 className="mb-2 flex items-center gap-2 text-[13px] font-semibold">
                <CheckCircle2 size={14} className="text-accent" />
                OCR coverage
              </h3>
              <div className="rounded-lg border border-line bg-[#F8FAF9] p-3">
                <p className="m-0 text-[13px] text-[#3F4B50]">
                  {result?.document?.page_count ?? '—'} pages in source document
                </p>
                <p className="mb-0 mt-1 text-[13px] text-muted">
                  {extractionNote(result?.ai_extraction)}
                </p>
                <p className="mb-0 mt-1 text-[13px] text-muted">
                  OCR processed {result?.document?.ocr_pages?.length ?? 0} page(s).
                </p>
              </div>
              <h3 className="mb-2 mt-5 text-[13px] font-semibold">Source excerpts</h3>
              {Object.entries(facts)
                .filter(([, v]) => v?.text)
                .slice(0, 5)
                .map(([key, fact]) => (
                  <div key={key} className="mb-2 rounded-lg border border-line p-2.5">
                    <div className="mb-1 flex justify-between gap-3 text-[12px]">
                      <span className="font-semibold text-[#3F4B50]">{labelFor(key)}</span>
                      <span className="text-muted">
                        Page {fact.page ?? '—'} · {confidence(fact.confidence)}
                      </span>
                    </div>
                    <p className="m-0 text-[13px] leading-5 text-muted">“{fact.text}”</p>
                  </div>
                ))}
            </div>
          </div>
        </section>
      </div>
    </WorkspaceShell>
  );
}

function Meta({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="border-t border-line px-5 py-4 first:border-t-0 md:border-l md:border-t-0 md:first:border-l-0">
      <p className="m-0 text-[13px] font-medium text-muted">{label}</p>
      <p className={`mb-0 mt-1 truncate text-[16px] font-semibold capitalize ${tone || ''}`}>
        {value.replaceAll('_', ' ')}
      </p>
    </div>
  );
}
function SectionTitle({ title, note }: { title: string; note: string }) {
  return (
    <div className="border-b border-line px-5 py-4">
      <h2 className="m-0 font-display text-[18px] font-semibold">{title}</h2>
      <p className="mb-0 mt-0.5 text-[14px] text-muted">{note}</p>
    </div>
  );
}
function DecisionCard({
  name,
  code,
  decision,
}: {
  name: string;
  code: string;
  decision?: Decision;
}) {
  const d = decision;
  const resolved = d?.status === 'resolved';
  const statusStyles: Record<string, string> = {
    resolved: 'bg-emerald-50 text-emerald-700',
    not_applicable: 'bg-slate-100 text-slate-700',
    unsupported: 'bg-amber-50 text-amber-800',
    ambiguous: 'bg-rose-50 text-rose-700',
  };
  return (
    <article className="overflow-hidden rounded-xl border border-line bg-white shadow-panel">
      <div className="flex items-start justify-between border-b border-line px-5 py-4">
        <div>
          <h3 className="m-0 font-display text-[18px] font-semibold">
            {code} · {name}
          </h3>
          <p className="mb-0 mt-0.5 text-[13px] text-muted">
            {d?.applicable === false
              ? 'Does not apply to this policy'
              : d
                ? 'Rated from the rate card'
                : 'Waiting for analysis'}
          </p>
        </div>
        <span
          className={`shrink-0 rounded-full px-2.5 py-1 text-[13px] font-semibold capitalize ${statusStyles[d?.status || ''] || 'bg-slate-100 text-slate-600'}`}
        >
          {(d?.status || 'pending').replaceAll('_', ' ')}
        </span>
      </div>
      <div className="px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="m-0 text-[13px] text-muted">Rate</p>
            <p
              key={String(d?.rate_percent)}
              className="mb-0 mt-0.5 animate-settle font-display text-[34px] font-semibold leading-tight tracking-[-.02em]"
            >
              {resolved && d?.rate_percent != null ? `${d.rate_percent}%` : '—'}
            </p>
            <p className="mb-0 mt-1 text-[13px] text-muted">
              {resolved
                ? d?.issues?.some(i => i.startsWith('Assumption:'))
                  ? 'From the rate card, with an assumption noted below'
                  : 'From the rate card'
                : 'No confirmed rate yet'}
            </p>
          </div>
          <div className="text-right">
            <p className="m-0 text-[13px] text-muted">Commission</p>
            <p
              key={String(d?.commission_amount)}
              className="mb-0 mt-0.5 animate-settle font-display text-[26px] font-semibold leading-tight text-accent"
            >
              {resolved && d?.commission_amount != null
                ? `₹${Number(d.commission_amount).toLocaleString('en-IN')}`
                : '—'}
            </p>
            <p className="mb-0 mt-1 text-[13px] text-muted">
              {d?.premium_basis
                ? `On a premium of ₹${Number(d.premium_basis).toLocaleString('en-IN')}`
                : 'Premium basis not found'}
            </p>
          </div>
        </div>
        {d?.rate_basis && (
          <p className="mb-0 mt-4 rounded-lg bg-[#F8FAF9] p-2.5 text-[13px] leading-5 text-[#3F4B50]">
            {d.rate_basis}
          </p>
        )}
        {d?.selected_conditions && Object.keys(d.selected_conditions).length > 0 && (
          <div className="mt-4">
            <p className="mb-1.5 text-[13px] font-semibold text-[#3F4B50]">Selected conditions</p>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(d.selected_conditions).map(([k, v]) => (
                <span
                  key={k}
                  className="rounded border border-line px-2 py-1 text-[12px] text-muted"
                >
                  {k.replaceAll('_', ' ')}: {String(v)}
                </span>
              ))}
            </div>
          </div>
        )}
        {d?.calculation && (
          <div className="mt-4">
            <p className="mb-1 text-[13px] font-semibold text-[#3F4B50]">Calculation</p>
            <p className="m-0 text-[13px] leading-5 text-muted">{d.calculation}</p>
          </div>
        )}
        <div className="mt-4">
          <p className="mb-1.5 text-[13px] font-semibold text-[#3F4B50]">Decision notes</p>
          {d?.issues?.length ? (
            <ul className="m-0 list-disc space-y-1 pl-4 text-[13px] leading-5 text-muted">
              {d.issues.map((item, i) => (
                <li
                  key={i}
                  className={
                    item.startsWith('Assumption:') ? 'font-medium text-amber-800' : undefined
                  }
                >
                  {item}
                </li>
              ))}
            </ul>
          ) : d?.status === 'not_applicable' ? (
            <p className="m-0 text-[13px] text-muted">
              This component doesn&rsquo;t apply to this policy type.
            </p>
          ) : (
            <p className="m-0 text-[13px] text-muted">No notes for this decision.</p>
          )}
        </div>
        <div className="mt-5 border-t border-line pt-4">
          <p className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-[#3F4B50]">
            <ShieldCheck size={15} className="text-accent" />
            Source evidence ({d?.evidence?.length || 0})
          </p>
          {d?.evidence?.length ? (
            <div className="space-y-2">
              {d.evidence.map((ref, i) => (
                <Evidence key={i} reference={ref} />
              ))}
            </div>
          ) : (
            <p className="m-0 rounded-lg bg-[#F8FAF9] p-3 text-[13px] text-muted">
              No source evidence was recorded for this decision.
            </p>
          )}
        </div>
      </div>
    </article>
  );
}
function Evidence({ reference: r }: { reference: Record<string, any> }) {
  const coords = [
    r.sheet && `Sheet ${r.sheet}`,
    r.cell && `Cell ${r.cell}`,
    r.page && `Page ${r.page}`,
    r.table && `Table ${r.table}`,
    r.row && `Row ${r.row}`,
    r.column && `Column ${r.column}`,
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <div className="rounded-lg border border-line bg-[#F8FAF9] p-3">
      <p className="m-0 break-all text-[13px] font-semibold text-[#3F4B50]">
        {r.source_file || 'Source document'}
        {r.source_kind && (
          <span className="ml-2 rounded bg-canvas px-1.5 py-0.5 font-medium text-muted">
            {r.source_kind.replace('_', ' ')}
          </span>
        )}
      </p>
      <p className="mb-0 mt-1 text-[13px] text-muted">
        {coords || 'Source location not recorded'}
        {r.role ? ` · ${String(r.role).replaceAll('_', ' ')}` : ''}
      </p>
      {r.source_sha256 && (
        <p className="mb-0 mt-1 break-all font-mono text-[11px] text-[#8A969A]">
          SHA-256 {r.source_sha256}
        </p>
      )}
      {r.value !== undefined && (
        <p className="mb-0 mt-1 text-[13px] text-[#3F4B50]">Extracted value: {String(r.value)}</p>
      )}
    </div>
  );
}

function extractionNote(meta: any) {
  const pages = meta?.ocr_pages?.length;
  return `Read without AI: ${pages ? `local OCR on ${pages} scanned page(s)` : 'PDF text layer'} + layout-aware rules. Values not printed in the PDF are left for review.`;
}
