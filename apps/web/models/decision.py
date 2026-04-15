import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.web.models.base import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from apps.web.models.claim import Claim


class DecisionOutcome(str, enum.Enum):
    APPROVE = "approve"
    PARTIAL_APPROVE = "partial_approve"
    DENY = "deny"
    NEEDS_INFO = "needs_info"


class Decision(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "decisions"

    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), default="proposed", nullable=False)
    outcome: Mapped[DecisionOutcome] = mapped_column(
        Enum(DecisionOutcome, name="decision_outcome", native_enum=False, length=32),
        nullable=False,
    )
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    rationale_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_proposed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    claim: Mapped["Claim"] = relationship(back_populates="decisions")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "claim_id": str(self.claim_id),
            "kind": self.kind,
            "outcome": self.outcome.value,
            "amount": self.amount,
            "currency": self.currency,
            "rationale_md": self.rationale_md,
            "is_proposed": self.is_proposed,
            "llm_model": self.llm_model,
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
