from __future__ import annotations

import json
import logging
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from lmu_ep_client.api_client import ApiError

logger = logging.getLogger(__name__)

OUTBOX_FILENAME = "tracking-outbox.json"
INITIAL_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 300.0
DEFAULT_MAX_SENT_RECORDS = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_output_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "sessions"
    return Path("sessions")


def default_outbox_path(output_dir: Path | None = None) -> Path:
    return (output_dir or _default_output_dir()) / OUTBOX_FILENAME


@dataclass(frozen=True)
class OutboxItem:
    path: str
    body: dict[str, Any]
    idempotency_key: str


class TrackingOutbox:
    """Durable queue for tracking API events.

    Events are persisted before the HTTP call. A sent event stays in the file
    with `sent_at` set, which keeps a local audit trail and prevents restart
    replay once the API acknowledges the event.
    """

    def __init__(
        self,
        path: Path | None = None,
        clock: Callable[[], float] | None = None,
        max_sent_records: int = DEFAULT_MAX_SENT_RECORDS,
    ) -> None:
        self._path = path
        self._clock = clock
        self._max_sent_records = max_sent_records
        self._records: list[dict[str, Any]] = self._load()

    @classmethod
    def in_memory(cls) -> "TrackingOutbox":
        return cls(path=None)

    @property
    def pending_count(self) -> int:
        return sum(
            1
            for record in self._records
            if record.get("sent_at") is None and record.get("failed_at") is None
        )

    def enqueue(self, path: str, body: dict[str, Any]) -> OutboxItem:
        return self._enqueue(path=path, body=body)

    def enqueue_session_status(self, registration_id: str, status: str) -> OutboxItem:
        if status not in {"active", "ended"}:
            raise ValueError("status must be 'active' or 'ended'")
        return self._enqueue(
            path=f"/api/tracking/registrations/{registration_id}/session",
            body={"status": status},
            operation="patch_session_status",
            registration_id=registration_id,
        )

    def _enqueue(
        self,
        path: str,
        body: dict[str, Any],
        operation: str = "post",
        registration_id: str | None = None,
    ) -> OutboxItem:
        record = {
            "path": path,
            "body": body,
            "operation": operation,
            "idempotency_key": str(uuid.uuid4()),
            "created_at": _now_iso(),
            "sent_at": None,
            "failed_at": None,
            "attempts": 0,
            "next_attempt_at": 0.0,
            "last_error": None,
        }
        if registration_id is not None:
            record["registration_id"] = registration_id
        self._records.append(record)
        self._save()
        return self._item(record)

    def drain(self, api: Any, force: bool = False) -> int:
        sent = 0
        for record in self._records:
            if record.get("sent_at") is not None:
                continue
            if record.get("failed_at") is not None:
                continue
            if not force and float(record.get("next_attempt_at") or 0.0) > self._now():
                continue

            try:
                self._send(api, record)
            except ApiError as e:
                if not self._is_retryable(e):
                    record["failed_at"] = _now_iso()
                    record["last_error"] = str(e)
                    self._save()
                    logger.warning(
                        "Dropping non-retryable queued tracking %s: %s",
                        self._describe(record),
                        e,
                    )
                    continue

                attempts = int(record.get("attempts") or 0) + 1
                record["attempts"] = attempts
                record["last_error"] = str(e)
                record["next_attempt_at"] = self._now() + self._backoff(attempts)
                self._save()
                logger.warning(
                    "Failed to send queued tracking %s; retry in %.0fs: %s",
                    self._describe(record),
                    self._backoff(attempts),
                    e,
                )
                break

            record["sent_at"] = _now_iso()
            record["last_error"] = None
            self._save()
            sent += 1
        return sent

    @staticmethod
    def _send(api: Any, record: dict[str, Any]) -> None:
        if record.get("operation") == "patch_session_status":
            api.patch_session_status(record["registration_id"], record["body"]["status"])
            return

        api.post(
            record["path"],
            body=record["body"],
            idempotency_key=record["idempotency_key"],
        )

    @staticmethod
    def _describe(record: dict[str, Any]) -> str:
        if record.get("operation") == "patch_session_status":
            return f"session status {record.get('body', {}).get('status')}"
        return f"{record.get('body', {}).get('type')} event"

    def _load(self) -> list[dict[str, Any]]:
        if self._path is None or not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except OSError as e:
            logger.warning("Failed to load tracking outbox %s: %s", self._path, e)
            return []
        except json.JSONDecodeError as e:
            self._preserve_corrupt_file(e)
            return []
        if not isinstance(raw, list):
            logger.warning("Tracking outbox %s is not a list; ignoring it", self._path)
            self._preserve_corrupt_file("root value is not a list")
            return []
        return [record for record in raw if isinstance(record, dict)]

    def _save(self) -> None:
        if self._path is None:
            return
        self._compact_sent_records()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(f"{self._path.name}.tmp")
        tmp.write_text(json.dumps(self._records, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def _compact_sent_records(self) -> None:
        if self._max_sent_records < 0:
            return

        sent_seen = 0
        keep_reversed: list[dict[str, Any]] = []
        for record in reversed(self._records):
            if record.get("sent_at") is None:
                keep_reversed.append(record)
                continue
            if sent_seen < self._max_sent_records:
                keep_reversed.append(record)
                sent_seen += 1
        self._records = list(reversed(keep_reversed))

    def _preserve_corrupt_file(self, reason: object) -> None:
        if self._path is None or not self._path.exists():
            return
        suffix = f"corrupt-{_now_iso().replace(':', '-')}-{uuid.uuid4().hex[:8]}"
        backup = self._path.with_name(f"{self._path.name}.{suffix}")
        try:
            self._path.replace(backup)
        except OSError as e:
            logger.warning("Failed to preserve corrupt tracking outbox %s: %s", self._path, e)
            return
        logger.warning("Preserved corrupt tracking outbox %s as %s: %s", self._path, backup, reason)

    def _now(self) -> float:
        if self._clock:
            return self._clock()
        return datetime.now(timezone.utc).timestamp()

    @staticmethod
    def _backoff(attempts: int) -> float:
        return min(MAX_BACKOFF_SECONDS, INITIAL_BACKOFF_SECONDS * (2 ** (attempts - 1)))

    @staticmethod
    def _is_retryable(error: ApiError) -> bool:
        return error.status == 0 or error.status == 408 or error.status == 429 or error.status >= 500

    @staticmethod
    def _item(record: dict[str, Any]) -> OutboxItem:
        return OutboxItem(
            path=record["path"],
            body=record["body"],
            idempotency_key=record["idempotency_key"],
        )
