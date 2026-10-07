"""NLI (Natural Language Inference) анализ фрагментов договора.

Использует модель cointegrated/rubert-base-cased-nli-threeway (или совместимую)
для классификации отношений между посылкой (текст договора) и гипотезой (условие риска):
- entailment: условие договора влечёт (подтверждает) риск;
- contradiction: условие договора противоречит риску (риск отсутствует);
- neutral: нейтральное отношение (фрагмент не относится к делу).

Поддерживает динамическое INT8-квантование для экономии памяти в пределах ~2 ГБ ОЗУ.
"""
import logging
from typing import Any

from app.config import settings

log = logging.getLogger(__name__)

_CLASSIFIER_INSTANCE = None


class NLIError(RuntimeError):
    pass


class NLIClassifier:
    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        quantize: bool | None = None,
    ) -> None:
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise NLIError(
                "Пакеты torch и transformers не установлены. "
                "Установите их для поддержки NLI: pip install torch transformers"
            ) from exc

        self.model_name = model_name or settings.nli_model_name
        self.device = device or settings.nli_device
        self.quantize = settings.nli_quantize if quantize is None else quantize

        log.info("Загрузка NLI модели %s (device=%s, quantize=%s)...", self.model_name, self.device, self.quantize)
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        model = AutoModelForSequenceClassification.from_pretrained(self.model_name)

        if self.device == "cpu" and self.quantize:
            log.info("Применение dynamic INT8 квантования для снижения потребления ОЗУ...")
            try:
                model = torch.quantization.quantize_dynamic(
                    model, {torch.nn.Linear}, dtype=torch.qint8
                )
            except Exception as e:
                log.warning("Не удалось применить dynamic quantize, загружаем в float32: %s", e)

        model.to(self.device)
        model.eval()
        self.model = model

        # Определение индексов классов из конфига модели
        id2label = getattr(model.config, "id2label", {}) or {}

        # Нормализация имён меток
        self.idx_entailment = 0
        self.idx_neutral = 1
        self.idx_contradiction = 2

        for idx, lbl in id2label.items():
            l_lower = str(lbl).lower()
            if "entail" in l_lower:
                self.idx_entailment = int(idx)
            elif "contra" in l_lower:
                self.idx_contradiction = int(idx)
            elif "neutr" in l_lower:
                self.idx_neutral = int(idx)

        log.info(
            "NLI метки: entailment=%d, neutral=%d, contradiction=%d",
            self.idx_entailment, self.idx_neutral, self.idx_contradiction
        )

    def predict(self, pairs: list[tuple[str, str]], batch_size: int | None = None) -> list[dict[str, float]]:
        """Классифицирует пары (premise, hypothesis).

        Возвращает список словарей:
        [{"entailment": 0.85, "neutral": 0.10, "contradiction": 0.05}, ...]
        """
        if not pairs:
            return []

        import torch

        batch_size = batch_size or settings.nli_batch_size
        results: list[dict[str, float]] = []

        for i in range(0, len(pairs), batch_size):
            batch_pairs = pairs[i : i + batch_size]
            premises = [p[0] for p in batch_pairs]
            hypotheses = [p[1] for p in batch_pairs]

            encoded = self.tokenizer(
                premises,
                hypotheses,
                padding=True,
                truncation="only_first",  # обрезаем длинную посылку, гипотезу сохраняем
                max_length=512,
                return_tensors="pt",
            ).to(self.device)

            with torch.no_grad():
                outputs = self.model(**encoded)
                probs = torch.softmax(outputs.logits, dim=1).cpu().numpy()

            for row in probs:
                results.append({
                    "entailment": float(row[self.idx_entailment]),
                    "neutral": float(row[self.idx_neutral]),
                    "contradiction": float(row[self.idx_contradiction]),
                })

        return results


def get_nli_classifier() -> NLIClassifier:
    """Ленивая инициализация синглтона классификатора."""
    global _CLASSIFIER_INSTANCE
    if _CLASSIFIER_INSTANCE is None:
        _CLASSIFIER_INSTANCE = NLIClassifier()
    return _CLASSIFIER_INSTANCE
