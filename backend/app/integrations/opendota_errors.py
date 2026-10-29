class OpenDotaError(Exception):
    """Base class for OpenDota integration failures."""


class OpenDotaTemporaryError(OpenDotaError):
    """A request failure that may succeed if retried."""


class OpenDotaRateLimitedError(OpenDotaTemporaryError):
    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("OpenDota rate limit reached.")
        self.retry_after = retry_after


class OpenDotaHTTPError(OpenDotaError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"OpenDota returned HTTP {status_code}.")
        self.status_code = status_code


class OpenDotaInvalidResponseError(OpenDotaError):
    """The response did not match the documented OpenDota response shape."""
