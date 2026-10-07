"""Сбор данных для отчёта — общий для всех режимов и форматов."""
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Analysis, Document, RiskFinding, RiskRule, User, visible_findings
from app.services.scoring import risk_score, traffic_light


@dataclass
class ReportFinding:
    number: int | None
    severity: str
    category: str | None
    title: str
    short_description: str | None
    page_number: int | None
    clause: str | None
    exact_quote: str | None
    comment: str
    counter_proposal: str | None
    legal_reference: str | None
    review_status: str
    reviewer_comment: str | None
    quote_verified: bool
    source: str
    highlights: list


@dataclass
class ReportDocument:
    id: uuid.UUID
    file_name: str
    relative_path: str | None
    status: str
    total_pages: int
    is_scanned: bool
    law_type: str | None
    risk_score: int | None
    light: str
    preview_path: str | None
    error_message: str | None
    findings: list[ReportFinding] = field(default_factory=list)
    rules_checked: int = 0

    @property
    def assessed(self) -> bool:
        return self.status == "COMPLETED" and self.light != "UNKNOWN" and (
            self.rules_checked > 0 or bool(self.findings)
        )

    @property
    def issues(self) -> list[ReportFinding]:
        """Все замечания (критические, внимание, низкий риск) в порядке списка."""
        return [f for f in self.findings if f.severity != "GREEN"]

    @property
    def red(self) -> list[ReportFinding]:
        return [f for f in self.findings if f.severity == "RED"]

    @property
    def yellow(self) -> list[ReportFinding]:
        return [f for f in self.findings if f.severity == "YELLOW"]

    @property
    def green(self) -> list[ReportFinding]:
        return [f for f in self.findings if f.severity == "GREEN"]


@dataclass
class ReportData:
    analysis_id: uuid.UUID
    title: str
    original_filename: str
    created_at: datetime
    generated_at: datetime
    author: str | None
    company: str | None
    rules_checked: int
    documents: list[ReportDocument]
    rules: list[RiskRule]

    @property
    def all_findings(self) -> list[ReportFinding]:
        return [f for d in self.documents for f in d.findings]

    @property
    def risk_score(self) -> int | None:
        if not self.documents or not all(d.assessed for d in self.documents):
            return None
        return max((d.risk_score or 0 for d in self.documents), default=0)

    @property
    def light(self) -> str:
        if not self.documents or not all(d.assessed for d in self.documents):
            return "UNKNOWN"
        return traffic_light(f.severity for f in self.all_findings if f.review_status != "DISMISSED")


def collect(db: Session, analysis: Analysis, user: User, document_id: uuid.UUID | None = None,
            include_dismissed: bool = False) -> ReportData:
    doc_query = select(Document).where(Document.analysis_id == analysis.id, Document.status != "UNSUPPORTED")
    if document_id:
        doc_query = doc_query.where(Document.id == document_id)
    documents = list(db.scalars(doc_query.order_by(Document.relative_path)))

    result_docs: list[ReportDocument] = []
    used_rules: set[str] = set()
    for doc in documents:
        query = (select(RiskFinding).where(RiskFinding.document_id == doc.id, visible_findings())
                 .order_by(RiskFinding.sort_index))
        checked_findings = list(db.scalars(query))
        checked_rules = {f.rule_id for f in checked_findings if f.rule_id}
        used_rules.update(checked_rules)
        findings = [f for f in checked_findings if include_dismissed or f.review_status != "DISMISSED"]
        items = [
            ReportFinding(
                number=f.sort_index + 1 if f.severity != "GREEN" else None,
                severity=f.severity, category=f.category, title=f.title, short_description=f.short_description,
                page_number=f.page_number, clause=f.clause, exact_quote=f.exact_quote, comment=f.comment,
                counter_proposal=f.counter_proposal, legal_reference=f.legal_reference,
                review_status=f.review_status, reviewer_comment=f.reviewer_comment,
                quote_verified=f.quote_verified, source=f.source, highlights=f.highlights or [],
            )
            for f in findings
        ]
        # Отклонённые замечания можно включить в отчёт для истории, но они не
        # повышают риск и не отменяют сам факт выполненной проверки.
        severities = [f.severity for f in checked_findings if f.review_status != "DISMISSED"]
        assessed = doc.status == "COMPLETED" and bool(checked_findings)
        result_docs.append(ReportDocument(
            id=doc.id, file_name=doc.file_name, relative_path=doc.relative_path, status=doc.status,
            total_pages=doc.total_pages, is_scanned=doc.is_scanned, law_type=doc.law_type,
            risk_score=risk_score(severities) if assessed else None,
            light=traffic_light(severities) if assessed else "UNKNOWN",
            preview_path=doc.preview_path, error_message=doc.error_message,
            findings=items, rules_checked=len(checked_rules),
        ))

    rules = list(db.scalars(select(RiskRule).where(RiskRule.id.in_(used_rules)).order_by(RiskRule.sort_order))) \
        if used_rules else []
    return ReportData(
        analysis_id=analysis.id,
        title=analysis.title,
        original_filename=analysis.original_filename,
        created_at=analysis.created_at,
        generated_at=datetime.now().astimezone(),
        author=user.full_name,
        company=user.company_name,
        rules_checked=len(rules),
        documents=result_docs,
        rules=rules,
    )
