import type { QualitySettingsDto } from './api-types';
import type { QualitySettings } from './types';

export const MAX_PROCESSING_SLA_SECONDS = 2_147_483;

export interface QualitySettingsInput {
  ocrMinConfidence: string;
  processingSlaSeconds: string;
}

function validate(settings: QualitySettings): QualitySettings {
  const { ocrMinConfidence, processingSlaSeconds } = settings;
  if (typeof ocrMinConfidence !== 'number' || !Number.isFinite(ocrMinConfidence) || ocrMinConfidence < 0 || ocrMinConfidence > 100) {
    throw new Error('Укажите требуемый уровень распознавания от 0 до 100 %.');
  }
  if (processingSlaSeconds !== null && (typeof processingSlaSeconds !== 'number' || !Number.isInteger(processingSlaSeconds) || processingSlaSeconds < 1 || processingSlaSeconds > MAX_PROCESSING_SLA_SECONDS)) {
    throw new Error('Нормативное время должно быть целым числом от 1 до 2 147 483 секунд. Оставьте поле пустым, если норматив не установлен.');
  }
  return settings;
}

export function parseQualitySettings(input: QualitySettingsInput): QualitySettings {
  if (!input.ocrMinConfidence.trim()) throw new Error('Укажите требуемый уровень распознавания от 0 до 100 %.');
  return validate({
    ocrMinConfidence: Number(input.ocrMinConfidence.trim()),
    processingSlaSeconds: input.processingSlaSeconds.trim() ? Number(input.processingSlaSeconds.trim()) : null,
  });
}

export function mapQualitySettings(value: QualitySettingsDto | null | undefined): QualitySettings | null {
  if (value == null) return null;
  return validate({ ocrMinConfidence: value.ocr_min_confidence, processingSlaSeconds: value.processing_sla_seconds });
}

export function qualitySettingsPayload(settings: QualitySettings): { quality_settings: QualitySettingsDto } {
  const valid = validate(settings);
  return { quality_settings: { ocr_min_confidence: valid.ocrMinConfidence, processing_sla_seconds: valid.processingSlaSeconds } };
}
