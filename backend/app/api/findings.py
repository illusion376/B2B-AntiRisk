import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import current_user, finding_out, get_document_or_404
from app.db import get_db
from app.models import Analysis, Document, RiskFinding, User
from app.schemas import FindingOut, FindingUpdate
from app.services.audit import log_action
from app.services.scoring import risk_score
from app.vocab import REVIEW_FROM_API, REVIEW_LABELS

router = APIRouter(prefix="/api/findings", tags=["Замечания"])


def _get(db: Session, finding_id: uuid.UUID, user: User) -> RiskFinding:
    finding = db.get(RiskFinding, finding_id)
    if finding is None:
        raise HTTPException(404, "Замечание не найдено")
    get_document_or_404(db, finding.document_id, user)
    return finding


@router.get("/{finding_id}", response_model=FindingOut)
def get_finding(finding_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return finding_out(_get(db, finding_id, user))


@router.patch("/{finding_id}", response_model=FindingOut,
              summary="Статус проверки замечания: unseen (не просмотрено) / accepted (принято) / dismissed (отклонено)")
def update_finding(finding_id: uuid.UUID, body: FindingUpdate, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    finding = _get(db, finding_id, user)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("status") is not None:
        finding.review_status = REVIEW_FROM_API[changes["status"]]
        finding.reviewed_by = user.id
        finding.reviewed_at = func.now()
    if "reviewer_comment" in changes:
        finding.reviewer_comment = changes["reviewer_comment"]
    log_action(db, user.id, "FINDING_REVIEWED", "finding", finding.id, {
        "title": finding.title, "status": REVIEW_LABELS[finding.review_status],
        "document_id": str(finding.document_id),
    })
    db.flush()

    # Отклонённые замечания не учитываются в индексе риска документа и файла
    severities = db.scalars(select(RiskFinding.severity).where(
        RiskFinding.document_id == finding.document_id, RiskFinding.review_status != "DISMISSED")).all()
    db.execute(update(Document).where(Document.id == finding.document_id)
               .values(risk_score=risk_score(severities)))
    db.execute(update(Analysis).where(Analysis.id == finding.analysis_id).values(
        risk_score=select(func.max(Document.risk_score))
        .where(Document.analysis_id == finding.analysis_id, Document.status == "COMPLETED")
        .scalar_subquery()
    ))
    db.commit()
    db.refresh(finding)
    return finding_out(finding)
