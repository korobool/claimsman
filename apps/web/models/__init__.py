from apps.web.models.base import Base
from apps.web.models.claim import Claim, ClaimStatus
from apps.web.models.document import Document
from apps.web.models.extracted_field import ExtractedField
from apps.web.models.finding import Finding, Severity
from apps.web.models.page import Page
from apps.web.models.upload import Upload

__all__ = [
    "Base",
    "Claim",
    "ClaimStatus",
    "Document",
    "ExtractedField",
    "Finding",
    "Page",
    "Severity",
    "Upload",
]
