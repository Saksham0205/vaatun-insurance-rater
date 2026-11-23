'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Activity, FilePlus2, LogOut, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { createClient } from '../lib/supabase/client';

const COLLAPSE_KEY = 'vaatun.sidebar.collapsed';

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const supabase = createClient(); const pathname = usePathname(); const router = useRouter();
  const [email, setEmail] = useState('');
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => { setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === '1'); }, []);
  useEffect(() => { void supabase.auth.getSession().then(({ data }) => { if (!data.session) router.replace('/login'); else setEmail(data.session.user.email || ''); }); const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => { if (!session) router.replace('/login?reason=expired'); else setEmail(session.user.email || ''); }); return () => subscription.unsubscribe(); }, [router, supabase]);

  async function logout() { await supabase.auth.signOut(); router.replace('/login'); }
  function toggleSidebar() {
    setCollapsed(value => { const next = !value; window.localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0'); return next; });
  }

  const nav = [{ href: '/', label: 'Overview', icon: Activity }];
  const initial = email.slice(0, 1).toUpperCase() || 'U';
  const width = collapsed ? 'w-[72px]' : 'w-[238px]';
  const offset = collapsed ? 'lg:pl-[72px]' : 'lg:pl-[238px]';

  return <div className="min-h-screen bg-canvas text-ink">
    <aside data-testid="sidebar" data-collapsed={collapsed} className={`fixed inset-y-0 left-0 z-30 hidden ${width} border-r border-line bg-white transition-[width] duration-200 lg:flex lg:flex-col`}>
      <Link href="/" title="vaatun rater" className={`flex h-[68px] items-center gap-3 border-b border-line no-underline ${collapsed ? 'justify-center px-0' : 'px-5'}`}>
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-[10px] bg-[#4d61d8] text-sm font-bold text-white">V</span>
        {!collapsed && <span className="text-[15px] font-semibold tracking-[-.35px] text-ink">vaatun<span className="ml-1 font-normal text-muted">rater</span></span>}
      </Link>

      <div className="px-3 pt-6">
        {!collapsed && <p className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-[.11em] text-[#9a9faa]">Workspace</p>}
        <nav className="space-y-1">
          {nav.map(item => {
            const Icon = item.icon;
            const active = pathname === '/' || pathname.startsWith('/documents');
            return <Link key={item.href} href={item.href} title={collapsed ? item.label : undefined}
              className={`flex h-9 items-center gap-3 rounded-md text-[12px] no-underline ${collapsed ? 'justify-center px-0' : 'px-3'} ${active ? 'bg-[#f0f2ff] font-semibold text-accent' : 'text-[#626875] hover:bg-[#f5f6f8]'}`}>
              <Icon size={15} />{!collapsed && item.label}
            </Link>;
          })}
        </nav>
      </div>

      <div className="mt-auto p-3">
        <div className={`flex items-center gap-2 border-t border-line pt-3 ${collapsed ? 'flex-col px-0' : 'px-2'}`}>
          <div title={collapsed ? email : undefined} className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#e9ecff] text-[11px] font-semibold text-accent">{initial}</div>
          <div className={collapsed ? 'sr-only' : 'min-w-0 flex-1'}>
            <p data-testid="account-email" className="m-0 truncate text-[10px] font-medium">{email || 'Signed-in user'}</p>
            <p className="m-0 mt-0.5 text-[9px] text-muted">Personal workspace</p>
          </div>
          <button aria-label="Sign out" title="Sign out" onClick={logout} className="rounded p-1.5 text-muted hover:bg-gray-100"><LogOut size={15} /></button>
        </div>
      </div>
    </aside>

    <div className={`${offset} transition-[padding] duration-200`}>
      <header className="sticky top-0 z-20 flex h-[62px] items-center justify-between border-b border-line bg-white/95 px-5 backdrop-blur md:px-8">
        <div className="flex items-center gap-3 text-[11px] text-muted">
          <button type="button" data-testid="sidebar-toggle" onClick={toggleSidebar}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
            className="hidden rounded-md border border-line p-1.5 text-muted hover:bg-[#f5f6f8] hover:text-ink lg:block">
            {collapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
          </button>
          <span className="font-medium text-ink">Workspace</span><span>/</span><span>{pathname.startsWith('/documents') ? 'Policy detail' : 'Policies'}</span>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/#upload" className="flex items-center gap-2 rounded-md bg-accent px-3 py-2 text-[11px] font-semibold text-white no-underline hover:bg-[#3e51c5]"><FilePlus2 size={14} />Upload policy</Link>
          <div className="grid h-7 w-7 place-items-center rounded-full bg-[#e9ecff] text-[10px] font-semibold text-accent lg:hidden">{initial}</div>
        </div>
      </header>
      <main className="mx-auto max-w-[1440px] px-4 py-6 md:px-8 md:py-8">{children}</main>
    </div>
  </div>;
}
