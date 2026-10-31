import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';

const inter = Inter({
  subsets: ['latin', 'cyrillic'],
  display: 'swap',
  variable: '--font-inter',
});

export const metadata: Metadata = {
  title: 'AntiRisk',
  description: 'Рабочее пространство для просмотра документов и разбора замечаний.',
  icons: { icon: { url: '/favicon.svg?v=antirisk-transparent', type: 'image/svg+xml', sizes: 'any' } },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru" className={inter.variable}>
      <body className={inter.className}>{children}</body>
    </html>
  );
}

