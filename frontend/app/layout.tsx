import type { Metadata } from 'next';
import './globals.css';
import Nav from '@/components/Nav';

export const metadata: Metadata = {
  title: 'FreightSentinel',
  description: 'Shipping document verification workspace - from shared inbox to discrepancy report.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Nav />
        <main className="main">{children}</main>
      </body>
    </html>
  );
}
