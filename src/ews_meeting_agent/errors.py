from __future__ import annotations


class EwsToolError(Exception):
    def __init__(self, error_code: str, message: str, **payload: object) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.payload = {"error_code": error_code, "message": message, **payload}
