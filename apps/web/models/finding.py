import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.web.models.base import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from apps.web.models.claim import Claim


class Severity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Finding(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "findings"

    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="finding_severity", native_enum=False, length=16),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(String(2048), nullable=False)
    refs_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)

    claim: Mapped["Claim"] = relationship(back_populates="findings")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "claim_id": str(self.claim_id),
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "refs": self.refs_json,
        }
