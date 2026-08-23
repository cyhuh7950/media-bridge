"""Tenant-scoped, bounded state for sanitized OpenAI Responses follow-ups."""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from media_bridge.assets import AssetAccessError, validate_tenant_id

MediaModality = Literal["image", "pdf"]

_RESPONSE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ResponsesStateError(LookupError):
    def __init__(self, code: str = "state_unavailable") -> None:
        super().__init__("Responses state is unavailable.")
        self.code = code
        self.safe_message = "Responses state is unavailable."


@dataclass(frozen=True, slots=True)
class ResponsesStateRecord:
    response_id: str
    tenant_id: str
    sanitized_text: str
    media_tainted: bool
    media_modalities: frozenset[MediaModality]
    expires_at: float


class ResponsesStateStore:
    """Keep only bounded sanitized text metadata; never media or provider payloads."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 30 * 60,
        max_entries: int = 1_000,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if ttl_seconds < 1 or ttl_seconds > 86_400:
            raise ValueError("state TTL must be between 1 and 86400 seconds")
        if max_entries < 1 or max_entries > 100_000:
            raise ValueError("state capacity must be between 1 and 100000 entries")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._records: OrderedDict[tuple[str, str], ResponsesStateRecord] = OrderedDict()

    def put(
        self,
        *,
        response_id: str,
        tenant_id: str,
        sanitized_text: str,
        media_tainted: bool,
        media_modalities: frozenset[MediaModality],
    ) -> ResponsesStateRecord:
        self._validate_identifiers(response_id, tenant_id)
        if len(sanitized_text) > 200_000:
            raise ValueError("sanitized state text exceeds the limit")
        if media_tainted != bool(media_modalities):
            raise ValueError("state taint and media modalities must agree")
        if not media_modalities.issubset({"image", "pdf"}):
            raise ValueError("state contains an unsupported media modality")

        now = self._clock()
        self._purge_expired(now)
        record = ResponsesStateRecord(
            response_id=response_id,
            tenant_id=tenant_id,
            sanitized_text=sanitized_text,
            media_tainted=media_tainted,
            media_modalities=media_modalities,
            expires_at=now + self._ttl_seconds,
        )
        key = (tenant_id, response_id)
        self._records.pop(key, None)
        self._records[key] = record
        while len(self._records) > self._max_entries:
            self._records.popitem(last=False)
        return record

    def resolve(self, response_id: str, *, tenant_id: str) -> ResponsesStateRecord:
        try:
            self._validate_identifiers(response_id, tenant_id)
        except ValueError as error:
            raise ResponsesStateError() from error
        self._purge_expired(self._clock())
        record = self._records.get((tenant_id, response_id))
        if record is None:
            raise ResponsesStateError()
        return record

    def clear(self) -> None:
        self._records.clear()

    def _purge_expired(self, now: float) -> None:
        expired = [key for key, record in self._records.items() if record.expires_at <= now]
        for key in expired:
            self._records.pop(key, None)

    @staticmethod
    def _validate_identifiers(response_id: str, tenant_id: str) -> None:
        if not _RESPONSE_ID.fullmatch(response_id):
            raise ValueError("response identifier is invalid")
        try:
            validate_tenant_id(tenant_id)
        except AssetAccessError as error:
            raise ValueError("tenant identifier is invalid") from error
