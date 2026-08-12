"""One error shape for the whole API.

Every failure the browser can see is an ApiError, so the front-end has exactly
one branch to write: `field` set means "show it next to that input", `field`
empty means "show the banner".

    code                 http  raised when
    invalid_param        400   a value failed catalog validation
    unknown_report       404   report_id is not in the catalog
    unsupported_format   400   format not offered by that report
    kdb_timeout          504   the report exceeded its timeout_s
    kdb_unavailable      502   no handle could be opened
    report_error         500   kdb returned status=`err, or signalled
    artifact_missing     404   a PDF download link expired or never existed
"""
from __future__ import annotations

from typing import Optional


class ApiError(Exception):
    status = 500
    code = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        status: Optional[int] = None,
        field: Optional[str] = None,
        detail: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status
        self.field = field
        self.detail = detail

    def payload(self) -> dict:
        body = {"status": "err", "code": self.code, "message": self.message}
        if self.field:
            body["field"] = self.field
        if self.detail:
            body["detail"] = self.detail
        return body


class ValidationError(ApiError):
    status = 400
    code = "invalid_param"

    def __init__(self, field: str, message: str):
        super().__init__(message, field=field)


class UnknownReport(ApiError):
    status = 404
    code = "unknown_report"


class UnsupportedFormat(ApiError):
    status = 400
    code = "unsupported_format"


class KdbTimeout(ApiError):
    status = 504
    code = "kdb_timeout"


class KdbUnavailable(ApiError):
    status = 502
    code = "kdb_unavailable"


class ReportError(ApiError):
    status = 500
    code = "report_error"


class ArtifactMissing(ApiError):
    status = 404
    code = "artifact_missing"
