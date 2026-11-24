'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { FilePlus2, LayoutList, LogOut, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { createClient } from '../lib/supabase/client';
import { BrandMark, BrandName } from './brand';

const COLLAPSE_KEY = 'vaatun.sidebar.collapsed';

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const supabase = createClient();
  const pathname = usePathname();
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === '1');
  }, []);
  useEffect(() => {
    void supabase.auth.getSession().then(({ data }) => {
      if (!data.session) router.replace('/login');
      else setEmail(data.session.user.email || '');
    });
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!session) router.replace('/login?reason=expired');
      else setEmail(session.user.email || '');
    });
    return () => subscription.unsubscribe();
  }, [router, supabase]);

  async function logout() {
    await supabase.auth.signOut();
    router.replace('/login');
  }
  function toggleSidebar() {
    setCollapsed(value => {
      const next = !value;
      window.localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0');
      return next;
    });
  }

  const nav = [{ href: '/', label: 'Overview', icon: LayoutList }];
  const initial = email.slice(0, 1).toUpperCase() || 'U';
  const width = collapsed ? 'w-[76px]' : 'w-[248px]';
  const offset = collapsed ? 'lg:pl-[76px]' : 'lg:pl-[248px]';
  const onDetail = pathname.startsWith('/documents');

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <aside
        data-testid="sidebar"
        data-collapsed={collapsed}
        className={`fixed inset-y-0 left-0 z-30 hidden ${width} border-r border-line bg-white transition-[width] duration-200 lg:flex lg:flex-col`}
      >
        <Link
          href="/"
          title="Vaatun Rater"
          className={`flex h-[68px] items-center gap-2.5 border-b border-line no-underline ${collapsed ? 'justify-center px-0' : 'px-5'}`}
        >
          <BrandMark size={32} />
          {!collapsed && <BrandName />}
        </Link>

        <nav className="space-y-1 px-3 pt-5">
          {nav.map(item => {
            const Icon = item.icon;
            const active = pathname === '/' || onDetail;
            return (
              <Link
                key={item.href}
                href={item.href}
                title={collapsed ? item.label : undefined}
                className={`relative flex h-10 items-center gap-3 rounded-lg text-[14px] no-underline transition-colors ${collapsed ? 'justify-center px-0' : 'px-3'} ${active ? 'bg-accent-soft font-semibold text-accent' : 'text-muted hover:bg-canvas hover:text-ink'}`}
              >
                {active && (
                  <span className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-accent" />
                )}
                <Icon size={17} />
                {!collapsed && item.label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto p-3">
          <div
            className={`flex items-center gap-2.5 border-t border-line pt-3 ${collapsed ? 'flex-col px-0' : 'px-2'}`}
          >
            <div
              title={collapsed ? email : undefined}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-accent-soft text-[13px] font-semibold text-accent"
            >
              {initial}
            </div>
            <div className={collapsed ? 'sr-only' : 'min-w-0 flex-1'}>
              <p data-testid="account-email" className="m-0 truncate text-[13px] font-medium">
                {email || 'Signed-in user'}
              </p>
              <p className="m-0 text-[12px] text-muted">Personal workspace</p>
            </div>
            <button
              aria-label="Sign out"
              title="Sign out"
              onClick={logout}
              className="rounded-lg p-2 text-muted transition-colors hover:bg-canvas hover:text-ink"
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      <div className={`${offset} transition-[padding] duration-200`}>
        <header className="sticky top-0 z-20 flex h-[64px] items-center justify-between border-b border-line bg-white/90 px-5 backdrop-blur md:px-8">
          <div className="flex items-center gap-3 text-[14px] text-muted">
            <button
              type="button"
              data-testid="sidebar-toggle"
              onClick={toggleSidebar}
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              aria-expanded={!collapsed}
              className="hidden rounded-lg border border-line p-1.5 text-muted transition-colors hover:bg-canvas hover:text-ink lg:block"
            >
              {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
            <Link href="/" className="flex items-center gap-2 no-underline lg:hidden">
              <BrandMark size={28} />
            </Link>
            {onDetail ? (
              <>
                <Link href="/" className="text-muted no-underline hover:text-ink">
                  Policies
                </Link>
                <span className="text-line">/</span>
                <span className="font-medium text-ink">Policy detail</span>
              </>
            ) : (
              <span className="font-medium text-ink">Policies</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/#upload"
              className="flex items-center gap-2 rounded-lg bg-accent px-3.5 py-2 text-[14px] font-semibold text-white no-underline transition-colors hover:bg-accent-strong"
            >
              <FilePlus2 size={16} />
              Upload policy
            </Link>
            <div className="grid h-8 w-8 place-items-center rounded-full bg-accent-soft text-[13px] font-semibold text-accent lg:hidden">
              {initial}
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-[1440px] px-4 py-6 md:px-8 md:py-8">{children}</main>
      </div>
    </div>
  );
}
