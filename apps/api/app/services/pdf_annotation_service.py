from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.pdf_literature import PdfAnnotation, PdfDocument


def list_my_annotations(db: Session, *, doc: PdfDocument, user_id: int) -> list[PdfAnnotation]:
    return (
        db.query(PdfAnnotation)
        .filter(PdfAnnotation.doc_id == doc.id, PdfAnnotation.user_id == user_id)
        .order_by(PdfAnnotation.updated_at.desc())
        .all()
    )


def create_annotation(
    db: Session,
    *,
    doc: PdfDocument,
    user_id: int,
    annotation_json: dict,
    is_public: bool = False,
) -> PdfAnnotation:
    ann = PdfAnnotation(
        doc_id=doc.id,
        user_id=user_id,
        is_public=is_public,
        annotation_json=annotation_json,
        version=1,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return ann


def update_annotation(
    db: Session,
    *,
    annotation: PdfAnnotation,
    user_id: int,
    annotation_json: dict,
    is_public: bool,
) -> PdfAnnotation:
    if annotation.user_id != user_id:
        raise PermissionError("只允许编辑自己的批注")
    annotation.annotation_json = annotation_json
    annotation.is_public = is_public
    annotation.version = int(annotation.version or 1) + 1
    db.commit()
    db.refresh(annotation)
    return annotation


def delete_annotation(db: Session, *, annotation: PdfAnnotation, user_id: int) -> None:
    if annotation.user_id != user_id:
        raise PermissionError("只允许删除自己的批注")
    db.delete(annotation)
    db.commit()


def list_public_users(db: Session, *, doc: PdfDocument) -> list[int]:
    rows = (
        db.query(PdfAnnotation.user_id)
        .filter(PdfAnnotation.doc_id == doc.id, PdfAnnotation.is_public.is_(True))
        .distinct()
        .all()
    )
    return [int(r[0]) for r in rows]


def list_public_by_user(db: Session, *, doc: PdfDocument, user_id: int) -> list[PdfAnnotation]:
    return (
        db.query(PdfAnnotation)
        .filter(
            PdfAnnotation.doc_id == doc.id,
            PdfAnnotation.user_id == user_id,
            PdfAnnotation.is_public.is_(True),
        )
        .order_by(PdfAnnotation.updated_at.desc())
        .all()
    )
