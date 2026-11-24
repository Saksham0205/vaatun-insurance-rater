'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useState } from 'react';
import { LoaderCircle } from 'lucide-react';
import { createClient } from '../../lib/supabase/client';
import { AuthLayout, inputClass, primaryButtonClass } from '../../components/auth-layout';

export default function LoginPage() {
  const supabase = createClient();
  const [expired, setExpired] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setExpired(new URLSearchParams(window.location.search).get('reason') === 'expired');
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
    setBusy(false);
    if (error) {
      setError(error.message);
      return;
    }
    window.location.assign('/');
  }

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Sign in to rate policies and review their commissions."
      footer={
        <>
          New to Vaatun?{' '}
          <Link href="/signup" className="font-semibold text-accent no-underline hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      {expired && (
        <div
          role="status"
          className="mb-5 rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-3 text-[14px] text-amber-900"
        >
          Your session expired. Sign in again to continue.
        </div>
      )}
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
            autoComplete="current-password"
            required
            value={password}
            onChange={e => setPassword(e.target.value)}
            className={inputClass}
          />
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
          {busy ? 'Signing in' : 'Sign in'}
        </button>
      </form>
    </AuthLayout>
  );
}
