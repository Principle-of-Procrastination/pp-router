class GatewayError(Exception):
    def __init__(self, status: int, code: str, message: str, *, retry_after: int | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.request_id = None
        super().__init__(code)

    def payload(self, request_id: str | None = None):
        return {
            "error": {
                "message": self.message,
                "type": self.code,
                "code": self.code,
                "param": None,
                "request_id": request_id or self.request_id,
            }
        }
