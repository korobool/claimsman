import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.web.models.base import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from apps.web.models.decision import Decision
    from apps.web.models.document import Document
    from apps.web.models.finding import Finding
    from apps.web.models.upload import Upload


class ClaimStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY_FOR_REVIEW = "ready_for_review"
    UNDER_REVIEW = "under_review"
    DECIDED = "decided"
    ESCALATED = "escalated"
    ERROR = "error"


class Claim(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "claims"

    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    claimant_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    policy_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    domain: Mapped[str] = mapped_column(String(64), default="health_insurance", nullable=False)
    status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus, name="claim_status", native_enum=False, length=32),
        default=ClaimStatus.UPLOADED,
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    uploads: Mapped[list["Upload"]] = relationship(
        back_populates="claim",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="claim",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="claim",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="claim",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @staticmethod
    def new_code() -> str:
        return "CLM-" + uuid.uuid4().hex[:8].upper()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "code": self.code,
            "title": self.title,
            "claimant_name": self.claimant_name,
            "policy_number": self.policy_number,
            "domain": self.domain,
            "status": self.status.value,
            "notes": self.notes,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "upload_count": len(self.uploads) if self.uploads is not None else 0,
        }


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
