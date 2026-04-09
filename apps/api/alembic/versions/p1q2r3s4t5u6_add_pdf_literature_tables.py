"""add pdf literature tables

Revision ID: p1q2r3s4t5u6
Revises: m9n8o7p6q5r4
Create Date: 2026-04-09

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "p1q2r3s4t5u6"
down_revision = "m9n8o7p6q5r4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pdf_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("authors_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("journal", sa.String(length=255), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("doi", sa.String(length=256), nullable=True),
        sa.Column("abstract_text", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("parse_status", sa.String(length=32), nullable=False),
        sa.Column("parse_progress", sa.Integer(), nullable=False),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("index_status", sa.String(length=32), nullable=False),
        sa.Column("index_progress", sa.Integer(), nullable=False),
        sa.Column("index_error", sa.Text(), nullable=True),
        sa.Column("translated_available", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id", name="uq_pdf_documents_file_id"),
    )
    op.create_index(op.f("ix_pdf_documents_file_id"), "pdf_documents", ["file_id"], unique=False)
    op.create_index(op.f("ix_pdf_documents_created_by"), "pdf_documents", ["created_by"], unique=False)

    op.create_table(
        "pdf_translation_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("doc_id", sa.Integer(), nullable=False),
        sa.Column("source_language", sa.String(length=32), nullable=True),
        sa.Column("target_language", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=True),
        sa.Column("provider_task_id", sa.String(length=128), nullable=True),
        sa.Column("translated_structured_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("translated_artifact_path", sa.String(length=500), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["doc_id"], ["pdf_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doc_id", "target_language", name="uq_pdf_translation_doc_lang"),
    )
    op.create_index(op.f("ix_pdf_translation_tasks_doc_id"), "pdf_translation_tasks", ["doc_id"], unique=False)
    op.create_index(
        op.f("ix_pdf_translation_tasks_requested_by"), "pdf_translation_tasks", ["requested_by"], unique=False
    )

    op.create_table(
        "pdf_annotations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("doc_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("annotation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["doc_id"], ["pdf_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pdf_annotations_doc_id"), "pdf_annotations", ["doc_id"], unique=False)
    op.create_index(op.f("ix_pdf_annotations_user_id"), "pdf_annotations", ["user_id"], unique=False)

    op.create_table(
        "document_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("doc_id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("attachment_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["doc_id"], ["pdf_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doc_id", "file_id", name="uq_document_attachment_doc_file"),
    )
    op.create_index(op.f("ix_document_attachments_doc_id"), "document_attachments", ["doc_id"], unique=False)
    op.create_index(op.f("ix_document_attachments_file_id"), "document_attachments", ["file_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_document_attachments_file_id"), table_name="document_attachments")
    op.drop_index(op.f("ix_document_attachments_doc_id"), table_name="document_attachments")
    op.drop_table("document_attachments")
    op.drop_index(op.f("ix_pdf_annotations_user_id"), table_name="pdf_annotations")
    op.drop_index(op.f("ix_pdf_annotations_doc_id"), table_name="pdf_annotations")
    op.drop_table("pdf_annotations")
    op.drop_index(op.f("ix_pdf_translation_tasks_requested_by"), table_name="pdf_translation_tasks")
    op.drop_index(op.f("ix_pdf_translation_tasks_doc_id"), table_name="pdf_translation_tasks")
    op.drop_table("pdf_translation_tasks")
    op.drop_index(op.f("ix_pdf_documents_created_by"), table_name="pdf_documents")
    op.drop_index(op.f("ix_pdf_documents_file_id"), table_name="pdf_documents")
    op.drop_table("pdf_documents")
