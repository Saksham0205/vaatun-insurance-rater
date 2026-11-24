'use client';

import Link from 'next/link';
import { FormEvent, useState } from 'react';
import { LoaderCircle, MailCheck } from 'lucide-react';
import { createClient } from '../../lib/supabase/client';
import { AuthLayout, inputClass, primaryButtonClass } from '../../components/auth-layout';

export default function SignupPage() {
  const supabase = createClient();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const { data, error } = await supabase.auth.signUp({
      email: email.trim(),
      password,
      options: { emailRedirectTo: `${location.origin}/auth/callback` },
    });
    setBusy(false);
    if (error) {
      setError(error.message);
      return;
    }
    if (data.session) {
      window.location.assign('/');
      return;
    }
    setSent(true);
  }

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Rate policies against insurer rate cards and keep every decision traceable."
      footer={
        <>
          Already have an account?{' '}
          <Link href="/login" className="font-semibold text-accent no-underline hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      {sent ? (
        <div
          role="status"
          className="flex animate-settle gap-3 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-[14px] leading-6 text-emerald-900"
        >
          <MailCheck size={20} className="mt-0.5 shrink-0" />
          <span>
            We sent a confirmation link to <b>{email.trim()}</b>. Open it, then come back here to
            sign in.
          </span>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <label className="block text-[13px] font-medium">
            Work email
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@company.com"
              className={inputClass}
            />
          </label>
          <label className="block text-[13px] font-medium">
            Password
            <input
              type="password"
              autoComplete="new-password"
              minLength={8}
              required
              value={password}
              onChange={e => setPassword(e.target.value)}
              className={inputClass}
            />
            <span className="mt-1.5 block text-[12px] font-normal text-muted">
              At least 8 characters.
            </span>
          </label>
          {error && (
            <p
              role="alert"
              className="m-0 rounded-lg bg-rose-50 px-3.5 py-3 text-[14px] text-rose-700"
            >
              {error}
            </p>
          )}
          <button disabled={busy} className={`${primaryButtonClass} !mt-6`}>
            {busy && <LoaderCircle size={16} className="animate-spin" />}
            {busy ? 'Creating account' : 'Create account'}
          </button>
        </form>
      )}
    </AuthLayout>
  );
}
