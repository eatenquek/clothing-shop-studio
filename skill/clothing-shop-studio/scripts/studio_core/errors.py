from __future__ import annotations


class StudioError(Exception):
    code = "internal_error"
    exit_code = 5

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        path: str | None = None,
        recovery: str = "Review the error and retry with corrected input.",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.field = field
        self.path = path
        self.recovery = recovery

    def as_dict(self) -> dict:
        result = {
            "code": self.code,
            "message": self.message,
            "recovery": self.recovery,
        }
        if self.field is not None:
            result["field"] = self.field
        if self.path is not None:
            result["path"] = self.path
        return result


class ValidationError(StudioError):
    code = "validation_error"
    exit_code = 2


class UnsafePathError(StudioError):
    code = "unsafe_path"
    exit_code = 3


class StorageError(StudioError):
    code = "storage_error"
    exit_code = 4
