import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.web.models.base import Base, TimestampMixin, UUIDPKMixin


class AuditLog(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "audit_log"

    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    before_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    after_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "actor": self.actor,
            "entity": self.entity,
            "entity_id": str(self.entity_id) if self.entity_id else None,
            "action": self.action,
            "before": self.before_json,
            "after": self.after_json,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
