"""phase2 trace and index governance

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a7
Create Date: 2026-04-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("files", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("files", sa.Column("last_error_code", sa.String(length=64), nullable=True))
    op.add_column("files", sa.Column("pipeline_version", sa.String(length=50), nullable=True))

    op.add_column("qa_retrieval_traces", sa.Column("trace_id", sa.String(length=64), nullable=True))
    op.add_column("qa_retrieval_traces", sa.Column("request_id", sa.String(length=64), nullable=True))
    op.add_column("qa_retrieval_traces", sa.Column("is_abstained", sa.Boolean(), nullable=True))
    op.add_column("qa_retrieval_traces", sa.Column("abstain_reason", sa.String(length=64), nullable=True))
    op.add_column("qa_retrieval_traces", sa.Column("failure_reason", sa.String(length=64), nullable=True))
    op.add_column("qa_retrieval_traces", sa.Column("model_name", sa.String(length=200), nullable=True))
    op.add_column("qa_retrieval_traces", sa.Column("latency_ms", sa.Float(), nullable=True))
    op.add_column("qa_retrieval_traces", sa.Column("filters_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("qa_retrieval_traces", sa.Column("evidence_bundles_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("qa_retrieval_traces", sa.Column("token_usage_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("qa_retrieval_traces", sa.Column("task_type", sa.String(length=50), nullable=True))
    op.add_column("qa_retrieval_traces", sa.Column("tool_traces_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("qa_retrieval_traces", sa.Column("workflow_steps_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("qa_retrieval_traces", sa.Column("session_context_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.create_index(op.f("ix_qa_retrieval_traces_trace_id"), "qa_retrieval_traces", ["trace_id"], unique=False)
    op.create_index(op.f("ix_qa_retrieval_traces_request_id"), "qa_retrieval_traces", ["request_id"], unique=False)

    op.alter_column("files", "retry_count", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_qa_retrieval_traces_request_id"), table_name="qa_retrieval_traces")
    op.drop_index(op.f("ix_qa_retrieval_traces_trace_id"), table_name="qa_retrieval_traces")
    for col in [
        "session_context_json",
        "workflow_steps_json",
        "tool_traces_json",
        "task_type",
        "token_usage_json",
        "evidence_bundles_json",
        "filters_json",
        "latency_ms",
        "model_name",
        "failure_reason",
        "abstain_reason",
        "is_abstained",
        "request_id",
        "trace_id",
    ]:
        op.drop_column("qa_retrieval_traces", col)
    op.drop_column("files", "pipeline_version")
    op.drop_column("files", "last_error_code")
    op.drop_column("files", "retry_count")

