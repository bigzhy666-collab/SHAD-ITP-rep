class ServiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 422,
                 retryable: bool = False, details: list | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable
        self.details = details or []

    def payload(self) -> dict:
        return {"code": self.code, "message": self.message,
                "retryable": self.retryable, "details": self.details}
