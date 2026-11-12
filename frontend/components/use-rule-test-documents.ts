'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '@/lib/api';
import {
  asRuleTestDocument, isRuleTestDocumentProcessing, mergeRuleTestDocuments, projectRuleTestDocuments,
  validateRuleTestUpload, type RuleTestTargetDocument,
} from '@/lib/rule-test-documents';

export function useRuleTestDocuments() {
  const [documents, setDocuments] = useState<RuleTestTargetDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  const projectId = useRef<string | null>(null);
  const uploadController = useRef<AbortController | null>(null);
  const refresh = useCallback(() => {
    generation.current += 1;
    setRevision(value => value + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const ticket = generation.current;
    let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const options = { signal: controller.signal };
        const project = projectId.current
          ? await api.getProject(projectId.current, options)
          : (await api.getProjects({ ...options, purpose: 'rule_test' })).find(item => item.isRuleTest);
        if (controller.signal.aborted || ticket !== generation.current) return;
        projectId.current = project?.id ?? null;
        const next = project ? projectRuleTestDocuments(project) : [];
        setDocuments(next);
        setLoadError(null);
        if (next.some(isRuleTestDocumentProcessing)) timer = setTimeout(read, 2500);
      } catch (cause) {
        if (!controller.signal.aborted && ticket === generation.current) setLoadError(errorMessage(cause));
      } finally {
        if (!controller.signal.aborted && ticket === generation.current) setLoading(false);
      }
    }
    void read();
    return () => { clearTimeout(timer); controller.abort(); };
  }, [revision]);

  useEffect(() => () => { uploadController.current?.abort(); }, []);

  async function upload(file: File): Promise<string | null> {
    if (uploadController.current) return null;
    const validation = validateRuleTestUpload(file);
    if (validation) { setUploadError(validation); return null; }
    const controller = new AbortController();
    uploadController.current = controller;
    generation.current += 1;
    setUploading(true);
    setUploadError(null);
    try {
      const result = await api.uploadRuleTestDocument(file, { signal: controller.signal });
      if (controller.signal.aborted) return null;
      projectId.current = result.projectId;
      const next = result.documents.map(asRuleTestDocument);
      setDocuments(previous => mergeRuleTestDocuments(next, previous));
      if (!next.length) throw new Error('Сервер не вернул загруженный документ. Обновите список и попробуйте ещё раз.');
      return next[0].id;
    } catch (cause) {
      if (!controller.signal.aborted) setUploadError(errorMessage(cause));
      return null;
    } finally {
      if (!controller.signal.aborted) {
        uploadController.current = null;
        setUploading(false);
        refresh();
      }
    }
  }

  return { documents, loading, uploading, loadError, uploadError, refresh, upload };
}
