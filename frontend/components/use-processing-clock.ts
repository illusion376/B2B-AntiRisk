'use client';

import { useEffect, useState } from 'react';
import { getProcessing } from '@/lib/projects';
import type { ProjectFile } from '@/lib/types';

export function useProcessingClock(files: ProjectFile[]) {
  const [now, setNow] = useState(0);
  useEffect(() => {
    const current = Date.now();
    setNow(current);
    if (files.every(file => getProcessing(file, current).phase === 'ready')) return;
    const timer = window.setInterval(() => {
      const time = Date.now();
      setNow(time);
      if (files.every(file => getProcessing(file, time).phase === 'ready')) window.clearInterval(timer);
    }, 300);
    return () => window.clearInterval(timer);
  }, [files]);
  return now;
}
