"""Catalogue queries with mirrors and a short memory of which services are down.

ESA's Gaia archive and IRSA's TAP service go down for hours at a time. Asking only one of them,
with long timeouts and retries, made a layer take up to a minute to say "unavailable", and every
switch-on asked again. Here each query names the services that can answer it, in order (the
original first, then a mirror of the same catalogue); one that fails is skipped for
``DOWN_FOR_S``, so a second request either reaches the mirror at once or fails at once.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypeVar

import requests

log = logging.getLogger(__name__)

# (connect, read) seconds. A healthy service connects in well under a second; a cone of up to
# 5000 rows is read in a few. Waiting longer only delays the switch to the mirror.
TIMEOUT_S = (5, 30)
# How long a service that failed is skipped before it is tried again.
DOWN_FOR_S = 300.0

T = TypeVar("T")


@dataclass(frozen=True)
class Service:
    """One TAP endpoint able to answer a query: its name (for the down list and the logs), its
    sync URL and the form fields of the request."""

    name: str
    url: str
    data: dict[str, str]


class TapUnavailable(RuntimeError):
    """No service answered (each failed now, or failed less than ``DOWN_FOR_S`` ago)."""


_down_until: dict[str, float] = {}
_lock = threading.Lock()


def is_down(name: str) -> bool:
    with _lock:
        return time.monotonic() < _down_until.get(name, 0.0)


def mark_down(name: str) -> None:
    with _lock:
        _down_until[name] = time.monotonic() + DOWN_FOR_S


def reset() -> None:
    """Forget which services were down (tests, or after a deploy)."""
    with _lock:
        _down_until.clear()


def query(
    services: Sequence[Service],
    parse: Callable[[str], T],
    header: str,
) -> T:
    """The parsed answer of the first service that answers with a CSV table.

    ``header`` is the first column name: some services answer 200 with an HTML or VOTable error
    page, which read as CSV would look like "no sources" and be cached for good.
    """
    errors = []
    for service in services:
        if is_down(service.name):
            errors.append(f"{service.name}: down (skipped)")
            continue
        try:
            response = requests.post(service.url, data=service.data, timeout=TIMEOUT_S)
            response.raise_for_status()
            if not response.text.lstrip().startswith(header):
                raise requests.RequestException("answer is not a CSV table")
            return parse(response.text)
        except requests.RequestException as error:
            mark_down(service.name)
            log.info("%s did not answer (%s); skipped for %.0f s", service.name, error, DOWN_FOR_S)
            errors.append(f"{service.name}: {error}")
    raise TapUnavailable("; ".join(errors))
