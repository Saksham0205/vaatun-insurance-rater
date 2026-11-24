import Link from 'next/link';
import { ShieldCheck } from 'lucide-react';
import { BrandMark, BrandName } from './brand';

export const inputClass =
  'mt-1.5 h-11 w-full rounded-lg border border-line bg-white px-3.5 text-[14px] text-ink outline-none transition-colors placeholder:text-[#9AA4A8] focus:border-accent focus:ring-4 focus:ring-accent/10';
export const primaryButtonClass =
  'flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-accent text-[14px] font-semibold text-white transition-colors hover:bg-accent-strong disabled:opacity-60';

/** Split sign-in layout shared by /login and /signup. */
export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <main className="grid min-h-screen bg-white md:grid-cols-[minmax(420px,.85fr)_1.15fr]">
      <section className="flex flex-col px-6 py-8 sm:px-10">
        <Link href="/login" className="flex items-center gap-2.5 self-start no-underline">
          <BrandMark size={34} />
          <BrandName />
        </Link>
        <div className="flex flex-1 items-center justify-center py-12">
          <div className="w-full max-w-[380px] animate-settle">
            <h1 className="m-0 font-display text-[30px] font-semibold leading-tight tracking-[-.02em]">
              {title}
            </h1>
            <p className="mb-8 mt-2 text-[15px] leading-6 text-muted">{subtitle}</p>
            {children}
            <p className="mt-6 text-center text-[14px] text-muted">{footer}</p>
          </div>
        </div>
        <p className="m-0 flex items-center justify-center gap-1.5 text-[12px] text-muted">
          <ShieldCheck size={14} />
          Sessions are secured by Supabase Auth
        </p>
      </section>
      <RateCardPanel />
    </main>
  );
}

const policyRows: [string, string][] = [
  ['Insurer', 'Go Digit'],
  ['RTO', 'UP-78 Kanpur'],
  ['Fuel', 'Petrol'],
  ['Engine', '1,197 cc'],
  ['TP premium', '₹3,416'],
];
const gridCols = ['Up to 1000 cc', '1000–1500 cc', 'Above 1500 cc'];
const gridRows: [string, string[]][] = [
  ['Cluster A', ['25%', '27.5%', '30%']],
  ['Cluster B', ['30%', '32.5%', '35%']],
  ['Cluster C', ['20%', '22.5%', '25%']],
];

/** Illustration of what the app does: read the policy, find its rate-card cell, compute the commission. */
function RateCardPanel() {
  return (
    <aside
      aria-hidden="true"
      className="relative hidden overflow-hidden bg-[#0E3F48] px-10 py-12 text-white md:flex md:flex-col md:justify-center lg:px-16"
    >
      <div
        className="pointer-events-none absolute inset-0 opacity-[.07]"
        style={{
          backgroundImage:
            'linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px)',
          backgroundSize: '44px 44px',
        }}
      />
      <div className="relative mx-auto w-full max-w-[620px]">
        <h2 className="m-0 max-w-[520px] font-display text-[40px] font-semibold leading-[1.08] tracking-[-.03em]">
          From policy PDF to commission, with the source for every number.
        </h2>
        <p className="mb-10 mt-4 max-w-[460px] text-[15px] leading-6 text-white/65">
          Upload a policy, and Vaatun reads it, finds the matching cell in the insurer&rsquo;s rate
          card, and shows you how the commission was worked out.
        </p>

        <div className="grid gap-4 xl:grid-cols-[.9fr_1.1fr]">
          <div className="rounded-xl bg-white/[.06] p-4 ring-1 ring-white/10">
            <p className="m-0 mb-2 text-[13px] font-medium text-white/60">Policy schedule</p>
            <div className="relative">
              <div
                className="vg-scan absolute inset-x-[-6px] top-0 h-8 rounded-md bg-white/10 ring-1 ring-marigold/60"
                style={{ ['--scan-to' as string]: '96px' }}
              />
              {policyRows.map(([k, v]) => (
                <div key={k} className="relative flex h-8 items-center justify-between text-[13px]">
                  <span className="text-white/55">{k}</span>
                  <span className="font-medium">{v}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-xl bg-white/[.06] p-4 ring-1 ring-white/10">
            <p className="m-0 mb-2 text-[13px] font-medium text-white/60">Go Digit SATP grid</p>
            <div className="grid grid-cols-[auto_repeat(3,minmax(0,1fr))] gap-1 text-center text-[12px]">
              <span />
              {gridCols.map(c => (
                <span key={c} className="px-1 pb-1 leading-4 text-white/45">
                  {c}
                </span>
              ))}
              {gridRows.map(([row, cells]) => [
                <span key={row} className="flex items-center pr-2 text-left text-white/55">
                  {row}
                </span>,
                ...cells.map((cell, i) => {
                  const hit = row === 'Cluster B' && i === 1;
                  return (
                    <span
                      key={`${row}-${i}`}
                      className={`rounded-md py-2 font-medium ${hit ? 'vg-cell' : 'bg-white/[.07] text-white/55'}`}
                    >
                      {cell}
                    </span>
                  );
                }),
              ])}
            </div>
          </div>
        </div>

        <div className="mt-4 flex items-baseline justify-between rounded-xl bg-white px-5 py-4 text-ink">
          <span className="vg-guide text-[13px] text-muted">₹3,416 × 32.5%</span>
          <span className="vg-result font-display text-[26px] font-semibold tracking-[-.02em] text-accent">
            ₹1,110.20
          </span>
        </div>
      </div>
    </aside>
  );
}
