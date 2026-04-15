import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.web.models.base import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from apps.web.models.document import Document


class ExtractedField(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "extracted_fields"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schema_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value_json: Mapped[dict | list | str | int | float | None] = mapped_column(
        JSONB, nullable=True
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_bbox_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    llm_rationale: Mapped[str | None] = mapped_column(String(4096), nullable=True)

    document: Mapped["Document"] = relationship(back_populates="extracted_fields")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "document_id": str(self.document_id),
            "schema_key": self.schema_key,
            "value": self.value_json,
            "confidence": self.confidence,
            "llm_model": self.llm_model,
        }
