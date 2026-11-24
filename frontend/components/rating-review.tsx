'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Calculator,
  ChevronDown,
  ChevronUp,
  LoaderCircle,
  RotateCcw,
  UserCheck,
} from 'lucide-react';
import { apiError, apiFetch } from '../lib/api';
import { insurerName } from '../lib/insurers';

type FieldSpec = {
  name: string;
  kind: 'choice' | 'int' | 'decimal' | 'text';
  label: string;
  choices: string[] | null;
};
type Options = { fields: FieldSpec[]; required_by_insurer: Record<string, string[]> };
type Input = { value: any; source: 'document' | 'operator' | null };

let cachedOptions: Promise<Options> | null = null;
function loadOptions(): Promise<Options> {
  cachedOptions ??= apiFetch('/api/v1/review/options').then(async r => {
    if (!r.ok) {
      cachedOptions = null;
      throw new Error(await apiError(r));
    }
    return r.json();
  });
  return cachedOptions;
}

export function RatingReview({
  analysisId,
  result,
  onUpdated,
}: {
  analysisId: string;
  result: any;
  onUpdated: (analysis: any) => void;
}) {
  const [options, setOptions] = useState<Options | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [showAll, setShowAll] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const inputs: Record<string, Input> = result?.rating_inputs || {};
  const saved: Record<string, any> = result?.overrides || {};
  const insurer: string = result?.facts?.insurer?.value || '';

  useEffect(() => {
    loadOptions()
      .then(setOptions)
      .catch(e => setError(e instanceof Error ? e.message : 'Could not load review options.'));
  }, []);
  useEffect(() => {
    setDraft(Object.fromEntries(Object.entries(saved).map(([k, v]) => [k, String(v)])));
  }, [result]); // eslint-disable-line react-hooks/exhaustive-deps

  const required = useMemo(() => options?.required_by_insurer[insurer] || [], [options, insurer]);
  const fields = useMemo(() => {
    if (!options) return [];
    const ordered = [...options.fields].sort((a, b) => {
      const ra = required.indexOf(a.name),
        rb = required.indexOf(b.name);
      return (ra < 0 ? 99 : ra) - (rb < 0 ? 99 : rb);
    });
    return showAll || !required.length ? ordered : ordered.filter(f => required.includes(f.name));
  }, [options, required, showAll]);

  if (!result?.policy_input) {
    return (
      <p className="m-0 px-5 pb-5 text-[13px] text-muted">
        This analysis predates input review. Select Re-run extraction to review its rating inputs.
      </p>
    );
  }

  const dirty =
    JSON.stringify(Object.fromEntries(Object.entries(draft).filter(([, v]) => v !== ''))) !==
    JSON.stringify(Object.fromEntries(Object.entries(saved).map(([k, v]) => [k, String(v)])));

  async function submit(overrides: Record<string, string>) {
    setSaving(true);
    setError('');
    try {
      const response = await apiFetch(`/api/v1/analyses/${analysisId}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ overrides }),
      });
      if (!response.ok) throw new Error(await apiError(response));
      onUpdated(await response.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Recalculation failed.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="px-5 pb-5">
      {error && (
        <p
          role="alert"
          className="mb-3 mt-0 animate-settle rounded-lg border border-rose-200 bg-rose-50 px-3 py-2.5 text-[14px] text-rose-700"
        >
          {error}
        </p>
      )}
      {!options ? (
        <div className="h-24 animate-pulse rounded-lg bg-canvas" />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {fields.map(f => {
              const current = inputs[f.name] || { value: null, source: null };
              const isRequired = required.includes(f.name);
              const missing = current.value == null || current.value === '';
              const value = draft[f.name] ?? '';
              const set = (v: string) => setDraft(d => ({ ...d, [f.name]: v }));
              const base =
                'h-10 w-full rounded-lg border px-3 text-[14px] outline-none transition-shadow focus:border-accent focus:ring-4 focus:ring-accent/10';
              const tone = value
                ? 'border-accent/30 bg-accent-soft/60'
                : isRequired && missing
                  ? 'border-amber-300 bg-amber-50/40'
                  : 'border-line bg-white';
              return (
                <label key={f.name} className="block">
                  <span className="mb-1.5 flex items-center justify-between gap-2 text-[13px] font-medium text-[#3F4B50]">
                    <span>
                      {f.label}
                      {isRequired && <span className="text-amber-600"> *</span>}
                    </span>
                    <span
                      className={`max-w-[55%] truncate rounded-full px-2 py-0.5 text-[12px] font-semibold ${current.source === 'operator' ? 'bg-accent-soft text-accent' : missing ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'}`}
                    >
                      {current.source === 'operator'
                        ? 'Reviewer'
                        : missing
                          ? 'Missing'
                          : `PDF: ${String(current.value)}`}
                    </span>
                  </span>
                  {f.kind === 'choice' ? (
                    <select
                      value={value}
                      onChange={e => set(e.target.value)}
                      className={`${base} ${tone}`}
                    >
                      <option value="">
                        {missing ? 'Choose a value' : `Keep: ${String(current.value)}`}
                      </option>
                      {(f.choices || []).map(c => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      value={value}
                      onChange={e => set(e.target.value)}
                      inputMode={f.kind === 'text' ? 'text' : 'decimal'}
                      placeholder={missing ? 'Enter value' : `Keep: ${String(current.value)}`}
                      className={`${base} ${tone}`}
                    />
                  )}
                </label>
              );
            })}
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              type="button"
              data-testid="recalculate"
              disabled={saving || !dirty}
              onClick={() =>
                void submit(Object.fromEntries(Object.entries(draft).filter(([, v]) => v !== '')))
              }
              className="inline-flex h-10 items-center gap-2 rounded-lg bg-accent px-4 text-[14px] font-semibold text-white transition-colors hover:bg-accent-strong disabled:opacity-50"
            >
              {saving ? (
                <LoaderCircle size={16} className="animate-spin" />
              ) : (
                <Calculator size={16} />
              )}
              Recalculate commission
            </button>
            {Object.keys(saved).length > 0 && (
              <button
                type="button"
                disabled={saving}
                onClick={() => void submit({})}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-line px-3.5 text-[14px] text-[#3F4B50] transition-colors hover:bg-canvas disabled:opacity-50"
              >
                <RotateCcw size={15} />
                Reset to PDF values
              </button>
            )}
            {required.length > 0 && (
              <button
                type="button"
                onClick={() => setShowAll(v => !v)}
                className="inline-flex items-center gap-1 px-1 text-[14px] font-medium text-accent hover:underline"
              >
                {showAll ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
                {showAll ? 'Show rate-card inputs only' : 'Show all inputs'}
              </button>
            )}
            {Object.keys(saved).length > 0 && (
              <span className="ml-auto inline-flex items-center gap-1 text-[13px] font-medium text-accent">
                <UserCheck size={15} />
                {Object.keys(saved).length === 1
                  ? '1 input from the reviewer'
                  : `${Object.keys(saved).length} inputs from the reviewer`}
              </span>
            )}
          </div>
          <p className="mb-0 mt-4 max-w-[760px] text-[13px] leading-5 text-muted">
            Fields marked * are what the {insurerName(insurer) || 'selected'} rate card selects on.
            Values you enter are recorded as &ldquo;Operator review&rdquo; evidence and the
            commission is recomputed from the rate card; the PDF is not re-read.
          </p>
        </>
      )}
    </div>
  );
}
