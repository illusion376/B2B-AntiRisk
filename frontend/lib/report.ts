/** Decode a server-supplied attachment name without trusting path components. */
export function reportFilename(disposition: string | null, fallback = 'report.docx'): string {
  let name: string | undefined;
  const encoded = disposition?.match(/(?:^|;)\s*filename\*\s*=\s*(?:"?UTF-8'[^']*')([^;\"]+)/i);
  if (encoded) {
    try { name = decodeURIComponent(encoded[1].trim()); } catch { /* Try the ordinary filename. */ }
  }
  if (!name) {
    const quoted = disposition?.match(/(?:^|;)\s*filename\s*=\s*"((?:\\.|[^"\\])*)"/i);
    const plain = disposition?.match(/(?:^|;)\s*filename\s*=\s*([^;]+)/i);
    name = quoted ? quoted[1].replace(/\\(.)/g, '$1') : plain?.[1].trim();
  }
  const safe = (name ?? fallback).split(/[\\/]/).at(-1)?.replace(/[\u0000-\u001f\u007f]/g, '').trim();
  return safe && safe !== '.' && safe !== '..' ? safe : fallback;
}

export function saveDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  try { link.click(); } finally {
    link.remove();
    // Keep the URL alive while the browser starts consuming the download.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
