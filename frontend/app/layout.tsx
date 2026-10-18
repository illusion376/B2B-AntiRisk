import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'AntiRisk',
  description: 'Рабочее пространство для просмотра документов и разбора замечаний.',
  icons: { icon: { url: '/antirisk-logo.png?v=antirisk', type: 'image/png' } },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ru"><body>{children}</body></html>;
}
