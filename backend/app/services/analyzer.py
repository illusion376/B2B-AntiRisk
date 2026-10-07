"""Применение правил риска к документу: retrieval -> LLM -> проверка цитат -> черновики замечаний."""
import asyncio
import logging
import re
from dataclasses import dataclass, field

from app.config import settings
from app.models import RiskRule
from app.services.llm import LLMClient
from app.services.quotes import QuoteMatch, locate_quote
from app.services.retrieval import RetrievedChunk
from app.vocab import weaker

log = logging.getLogger(__name__)

LAW_NAMES = {"44-FZ": "44-ФЗ", "223-FZ": "223-ФЗ"}

SYSTEM_PROMPT = """Ты — опытный юрист по государственным и корпоративным закупкам (44-ФЗ, 223-ФЗ, ГК РФ).
Ты проверяешь документацию закупки на стороне ПОСТАВЩИКА: ищешь условия, которые грозят штрафами,
убытками, односторонним расторжением контракта и включением в реестр недобросовестных поставщиков (РНП).

Правила ответа:
- Анализируй ТОЛЬКО предоставленные фрагменты документа, ничего не придумывай.
- Цитату ("quote") копируй из фрагмента ДОСЛОВНО, символ в символ, 1–3 предложения, без сокращений и многоточий.
- Если в фрагментах нет условий по проверяемому вопросу — verdict "NOT_FOUND".
- Если условия есть и рисков нет — verdict "OK".
- Пиши по-русски, кратко и по делу, понятно юристу и менеджеру.
- Ответ — строго один JSON-объект без пояснений вокруг."""

USER_TEMPLATE = """Документ: {document_name}
Применимое законодательство: {law}

ПРАВИЛО ПРОВЕРКИ: {title}
Описание риска: {description}
Норма права: {legal_reference}
Что проверить: {prompt}

ФРАГМЕНТЫ ДОКУМЕНТА:
{fragments}

Верни JSON строго такого вида:
{{
  "verdict": "RISK" | "OK" | "NOT_FOUND",
  "issues": [
    {{
      "fragment": "F1",
      "quote": "дословная цитата из фрагмента",
      "severity": "RED" | "YELLOW" | "LOW",
      "summary": "суть проблемы, до 90 символов",
      "comment": "почему это риск для поставщика и что нарушено (со ссылкой на норму)",
      "recommendation": "предлагаемая редакция пункта или действие: запрос разъяснений, протокол разногласий",
      "confidence": 0.0
    }}
  ],
  "explanation": "для OK / NOT_FOUND — одно предложение, почему риска нет"
}}
Не более 3 элементов в "issues". Для "OK" и "NOT_FOUND" массив "issues" пустой.
Если риск — именно в ОТСУТСТВИИ нужного условия, верни "RISK", в "quote" оставь пустую строку,
а в "fragment" укажи фрагмент раздела, где это условие должно было быть."""


@dataclass
class FindingDraft:
    rule: RiskRule
    severity: str  # RED / YELLOW / LOW / GREEN
    title: str
    short_description: str | None
    comment: str
    counter_proposal: str | None = None
    page_number: int | None = None
    clause: str | None = None
    exact_quote: str | None = None
    highlights: list[dict] = field(default_factory=list)
    quote_verified: bool = False
    confidence: float | None = None
    source: str = "LLM"


@dataclass
class RuleContext:
    rule: RiskRule
    chunks: list[RetrievedChunk]


def _format_fragments(chunks: list[RetrievedChunk]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        pages = f"стр. {chunk.page_number}" if not chunk.page_end or chunk.page_end == chunk.page_number \
            else f"стр. {chunk.page_number}–{chunk.page_end}"
        header = f"[F{i}] ({pages}" + (f", {chunk.clause_title}" if chunk.clause_title else "") + ")"
        parts.append(f"{header}\n{chunk.content}")
    return "\n\n".join(parts)


def _clause_label(match_clause: str | None, chunk: RetrievedChunk | None) -> str | None:
    """Номер пункта без «п.» («6.2»), как его показывает фронтенд; иначе — пункты/раздел чанка."""
    if match_clause:
        return match_clause
    if chunk and chunk.clause_title:
        label = chunk.clause_title.split(" › ")[-1]
        if label.startswith("п"):
            return re.sub(r"^пп?\. ", "", label)[:255]
        section = re.match(r"^(\d{1,2})\.", label)  # только раздел: «6. Ответственность сторон» -> «6»
        return section.group(1) if section else None
    return None


def _page_hint(chunk: RetrievedChunk | None) -> tuple[int, int] | None:
    if not chunk:
        return None
    return chunk.page_number, chunk.page_end or chunk.page_number


def _green(rule: RiskRule, explanation: str | None, source: str = "LLM") -> FindingDraft:
    return FindingDraft(
        rule=rule,
        severity="GREEN",
        title=rule.title,
        short_description="Нарушений не выявлено",
        comment=explanation or "Условий, создающих риск по этому правилу, не обнаружено.",
        source=source,
    )


def _resolve_quote(pages: list[dict], quote: str, chunk: RetrievedChunk | None) -> QuoteMatch:
    if quote.strip():
        return locate_quote(pages, quote, _page_hint(chunk))
    return QuoteMatch(False, chunk.page_number if chunk else None, None, None)


def _build_drafts(rule: RiskRule, ctx: RuleContext, answer: dict, pages: list[dict]) -> list[FindingDraft]:
    verdict = str(answer.get("verdict", "")).upper()
    issues = answer.get("issues") or []
    if verdict != "RISK" or not isinstance(issues, list) or not issues:
        return [_green(rule, answer.get("explanation"))]

    drafts: list[FindingDraft] = []
    seen_quotes: set[str] = set()
    for issue in issues[:3]:
        if not isinstance(issue, dict):
            continue
        chunk = _chunk_by_ref(ctx.chunks, issue.get("fragment"))
        quote = str(issue.get("quote") or "")
        match = _resolve_quote(pages, quote, chunk)
        if match.verified and match.text in seen_quotes:
            continue
        if match.verified:
            seen_quotes.add(match.text)

        # Уровень задаёт правило; модель может только понизить критичность
        suggested = str(issue.get("severity", "")).upper()
        severity = weaker(rule.severity, suggested) if suggested in ("RED", "YELLOW", "LOW") else rule.severity
        if severity not in ("RED", "YELLOW", "LOW"):
            severity = "YELLOW"

        drafts.append(FindingDraft(
            rule=rule,
            severity=severity,
            title=rule.title,
            short_description=_short(issue.get("summary")) or rule.description,
            comment=str(issue.get("comment") or rule.description).strip(),
            counter_proposal=(str(issue.get("recommendation")).strip() or None) if issue.get("recommendation") else None,
            page_number=match.page_number or (chunk.page_number if chunk else None),
            clause=_clause_label(match.clause, chunk),
            exact_quote=match.text if match.verified else (quote.strip() or None),
            highlights=match.highlights,
            quote_verified=match.verified,
            confidence=_confidence(issue.get("confidence"), match),
        ))
    return drafts or [_green(rule, answer.get("explanation"))]


def _chunk_by_ref(chunks: list[RetrievedChunk], ref) -> RetrievedChunk | None:
    m = re.search(r"\d+", str(ref or ""))
    if m and 1 <= int(m.group()) <= len(chunks):
        return chunks[int(m.group()) - 1]
    return chunks[0] if chunks else None


def _short(value) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    return text if len(text) <= 120 else text[:117].rstrip() + "…"


def _confidence(value, match: QuoteMatch) -> float | None:
    try:
        conf = max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        conf = 0.7
    # Цитату не нашли в документе — снижаем доверие к замечанию
    return round(conf if match.verified else conf * 0.6, 2)


async def _evaluate_rule(client: LLMClient, semaphore: asyncio.Semaphore, ctx: RuleContext,
                         pages: list[dict], document_name: str, law_type: str | None) -> list[FindingDraft]:
    rule = ctx.rule
    if not ctx.chunks:
        return [_green(rule, "В документе нет фрагментов, относящихся к правилу.")]
    prompt = USER_TEMPLATE.format(
        document_name=document_name,
        law=LAW_NAMES.get(law_type or "", "не определено (44-ФЗ / 223-ФЗ / коммерческий договор)"),
        title=rule.title,
        description=rule.description,
        legal_reference=rule.legal_reference or "—",
        prompt=rule.llm_prompt,
        fragments=_format_fragments(ctx.chunks),
    )
    async with semaphore:
        answer = await client.complete_json(SYSTEM_PROMPT, prompt)
    return _build_drafts(rule, ctx, answer, pages)


async def evaluate_with_llm(contexts: list[RuleContext], pages: list[dict], document_name: str,
                            law_type: str | None) -> list[FindingDraft]:
    semaphore = asyncio.Semaphore(settings.llm_concurrency)
    async with LLMClient() as client:
        results = await asyncio.gather(
            *(_evaluate_rule(client, semaphore, ctx, pages, document_name, law_type) for ctx in contexts),
            return_exceptions=True,
        )
    drafts: list[FindingDraft] = []
    for ctx, result in zip(contexts, results):
        if isinstance(result, BaseException):
            log.error("Rule %s failed: %r", ctx.rule.id, result)
            drafts.append(FindingDraft(
                rule=ctx.rule, severity=weaker(ctx.rule.severity, "YELLOW"), title=ctx.rule.title,
                short_description="Не удалось проверить автоматически — нужна ручная проверка",
                comment=f"Ошибка ИИ-модуля при проверке правила: {type(result).__name__}. "
                        "Проверьте условие вручную.",
                page_number=ctx.chunks[0].page_number if ctx.chunks else None,
                clause=_clause_label(None, ctx.chunks[0] if ctx.chunks else None),
                confidence=0.0, source="ERROR",
            ))
        else:
            drafts.extend(result)
    return drafts


# ---------- Эвристический режим (LLM не настроена) ----------

_WORD = re.compile(r"\w{4,}", re.UNICODE)
_SENTENCE = re.compile(r"(?<=[.;!?])\s+")


def _stems(text: str) -> set[str]:
    return {w[:6] for w in _WORD.findall(text.lower().replace("ё", "е"))}


def evaluate_heuristic(contexts: list[RuleContext], pages: list[dict]) -> list[FindingDraft]:
    """Без LLM: показываем самый релевантный фрагмент как «требует внимания».

    Режим нужен, чтобы система работала «из коробки» без ключей API; замечания помечаются
    source=HEURISTIC и низкой уверенностью.
    """
    drafts: list[FindingDraft] = []
    for ctx in contexts:
        rule = ctx.rule
        relevant = [c for c in ctx.chunks if c.fts_hit]
        if not relevant:
            drafts.append(_green(rule, "Релевантных условий в документе не найдено.", source="HEURISTIC"))
            continue
        best = max(relevant, key=lambda c: c.score)
        query_stems = _stems(rule.semantic_query)
        sentences = [s for s in _SENTENCE.split(best.content.replace("\n", " ")) if len(s) > 20] or [best.content]
        sentence = max(sentences, key=lambda s: len(_stems(s) & query_stems))
        match = locate_quote(pages, sentence[:400], _page_hint(best))
        drafts.append(FindingDraft(
            rule=rule,
            severity=weaker(rule.severity, "YELLOW"),
            title=rule.title,
            short_description="Найдено релевантное условие — проверьте вручную",
            comment=f"{rule.description}. Автоматическая оценка без LLM: проверьте фрагмент на соответствие правилу. "
                    f"{rule.llm_prompt}",
            page_number=match.page_number or best.page_number,
            clause=_clause_label(match.clause, best),
            exact_quote=match.text if match.verified else sentence[:400],
            highlights=match.highlights,
            quote_verified=match.verified,
            confidence=0.3,
            source="HEURISTIC",
        ))
    return drafts
