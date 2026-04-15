import hashlib
import uuid
from pathlib import Path

import aiofiles

from apps.web.config import settings


class StorageService:
    """Filesystem storage for uploaded claim files.

    Files are stored under ``{storage_root}/{claim_id}/{sha256}{ext}``.
    The same content hashes to the same filename, so duplicates within a claim
    collapse naturally.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or settings.storage_root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _claim_dir(self, claim_id: uuid.UUID) -> Path:
        d = self.root / str(claim_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def save(
        self,
        *,
        claim_id: uuid.UUID,
        filename: str,
        content: bytes,
    ) -> tuple[Path, str]:
        sha256 = hashlib.sha256(content).hexdigest()
        ext = Path(filename).suffix.lower() or ""
        target = self._claim_dir(claim_id) / f"{sha256}{ext}"
        if not target.exists():
            async with aiofiles.open(target, "wb") as f:
                await f.write(content)
        return target, sha256


storage = StorageService()
