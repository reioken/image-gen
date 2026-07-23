"""Normalized provider error hierarchy.

Adapters translate raw HTTP/SDK failures into these classes so the scheduler
can make uniform decisions (retry vs. abort vs. disable-provider).
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for all normalized provider errors.

    Attributes
    ----------
    provider, model:
        Identify where the error came from.
    http_status:
        The HTTP status code if the failure was an HTTP response.
    retryable:
        Whether the scheduler should retry this task.
    disables_provider:
        Whether this error should disable the provider for the rest of the run
        (used for auth errors — retrying a bad key is pointless and wasteful).
    """

    retryable: bool = False
    disables_provider: bool = False

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.model = model
        self.http_status = http_status

    @property
    def error_type(self) -> str:
        return type(self).__name__


class ProviderAuthError(ProviderError):
    """Invalid / missing credentials. Not retryable; disables the provider."""

    retryable = False
    disables_provider = True


class ProviderRateLimitError(ProviderError):
    """429 / rate-limit. Retryable after a wait (honor Retry-After when present)."""

    retryable = True

    def __init__(self, *args, retry_after: float | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


class ProviderContentPolicyError(ProviderError):
    """Content-policy refusal. Never retryable — retrying yields the same refusal."""

    retryable = False


class ProviderInvalidInputError(ProviderError):
    """400/422-style bad request (bad params, unsupported input). Not retryable."""

    retryable = False


class ProviderTimeoutError(ProviderError):
    """Request or job timed out. Retryable."""

    retryable = True


class ProviderTransientError(ProviderError):
    """5xx / connection error / temporary failure. Retryable."""

    retryable = True


def classify_http_status(
    status: int,
    *,
    provider: str | None = None,
    model: str | None = None,
    message: str = "",
    retry_after: float | None = None,
) -> ProviderError:
    """Map an HTTP status code onto the appropriate normalized error class."""
    msg = message or f"HTTP {status} from {provider or 'provider'}"
    if status in (401, 403):
        return ProviderAuthError(msg, provider=provider, model=model, http_status=status)
    if status == 429:
        return ProviderRateLimitError(
            msg, provider=provider, model=model, http_status=status, retry_after=retry_after
        )
    if status in (400, 422):
        # Some providers signal content-policy refusals via 400 with a marker in
        # the body; the caller can override by raising ProviderContentPolicyError
        # directly. Default 400/422 => invalid input.
        return ProviderInvalidInputError(msg, provider=provider, model=model, http_status=status)
    if status == 408:
        return ProviderTimeoutError(msg, provider=provider, model=model, http_status=status)
    if status in (409, 425, 500, 502, 503, 504):
        return ProviderTransientError(msg, provider=provider, model=model, http_status=status)
    # Unknown status: treat non-2xx as transient so we at least retry once.
    if status >= 500:
        return ProviderTransientError(msg, provider=provider, model=model, http_status=status)
    return ProviderInvalidInputError(msg, provider=provider, model=model, http_status=status)
