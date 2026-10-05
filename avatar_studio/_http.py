# -*- coding: utf-8 -*-
"""HTTP helper shared by the vendor clients: bounded retries, readable errors."""
import time

import httpx

RETRY_STATUSES = {429, 500, 502, 503, 504}


class ApiError(RuntimeError):
    def __init__(self, response):
        request = response.request
        super().__init__(
            "{} {} -> HTTP {}: {}".format(
                request.method, request.url, response.status_code, response.text[:2000]
            )
        )
        self.status_code = response.status_code


def request_with_retry(client, method, url, idempotent=True, max_attempts=4,
                       backoff_s=2.0, sleep=time.sleep, **kwargs):
    """Send a request, retrying throttling and transient server failures.

    Non-idempotent calls (anything that creates a billable object, e.g. a
    voice or a video) are retried only on 429, where the server has
    rejected the request without acting on it. A 5xx or dropped connection
    on a create may still have succeeded server-side, so it is surfaced
    instead of risking a duplicate.
    """
    for attempt in range(1, max_attempts + 1):
        delay = backoff_s * 2 ** (attempt - 1)
        try:
            response = client.request(method, url, **kwargs)
        except httpx.TransportError:
            if not idempotent or attempt == max_attempts:
                raise
            sleep(delay)
            continue
        retryable = response.status_code == 429 or (
            idempotent and response.status_code in RETRY_STATUSES
        )
        if retryable and attempt < max_attempts:
            retry_after = response.headers.get("retry-after", "")
            sleep(float(retry_after) if retry_after.isdigit() else delay)
            continue
        if response.is_error:
            raise ApiError(response)
        return response
    raise AssertionError("unreachable")
