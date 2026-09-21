import type { Metadata } from 'next';
import './globals.css';
import Nav from '@/components/Nav';
import { LanguageProvider } from '@/components/LanguageProvider';

export const metadata: Metadata = {
  title: 'FreightSentinel',
  description: 'Shipping document verification workspace - from shared inbox to discrepancy report.',
  // The app ships its own language switcher. Browser auto-translation would run on top of it
  // and produce a second, machine-translated layer over the curated wording.
  other: { google: 'notranslate' },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" translate="no" className="notranslate" suppressHydrationWarning>
      <body>
        <LanguageProvider>
          <Nav />
          <main className="main">{children}</main>
        </LanguageProvider>
      </body>
    </html>
  );
}
