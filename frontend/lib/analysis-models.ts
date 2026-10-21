import type { AnalysisModel } from './types';

export const analysisModelPreferenceKey = 'b2b-antirisk.analysis-model';

export function savedAnalysisModel(value: string | null): string | null {
  return value && /^[a-zA-Z0-9][a-zA-Z0-9._:/@+\-]{0,199}$/.test(value) ? value : null;
}

export function filterAnalysisModels(models: AnalysisModel[], query: string, provider: string): AnalysisModel[] {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return models.filter(model => (provider === 'all' || model.providerId === provider)
    && terms.every(term => `${model.label} ${model.provider} ${model.id}`.toLocaleLowerCase().includes(term)));
}

export const modelProviderIcons: Record<string, string> = {
  openai: '/model-providers/openai.svg', deepseek: '/model-providers/deepseek.svg',
  qwen: '/model-providers/qwen.svg', anthropic: '/model-providers/anthropic.svg', google: '/model-providers/google.svg',
};
