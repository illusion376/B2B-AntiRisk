import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'B2B AntiRisk',
  description: 'Рабочее пространство для просмотра документов и разбора замечаний.',
  icons: { icon: '/favicon.svg?v=shield' },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ru"><body>{children}</body></html>;
}
