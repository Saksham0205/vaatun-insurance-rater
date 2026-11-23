import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: 'Vaatun | Insurance operations', description: 'Evidence-backed motor insurance commission decisions' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body>{children}</body></html>; }
