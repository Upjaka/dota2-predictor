class BatruError(Exception):
    """Base class for Batru integration failures."""


class BatruTemporaryError(BatruError):
    """A failure that may succeed if retried."""


class BatruRateLimitedError(BatruTemporaryError):
    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("Batru rate limit reached.")
        self.retry_after = retry_after


class BatruHTTPError(BatruError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"Batru returned HTTP {status_code}.")
        self.status_code = status_code


class BatruInvalidResponseError(BatruError):
    """The Batru response did not match its documented win-rate format."""
