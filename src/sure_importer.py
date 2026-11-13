"""Sure Finance API client for importing converted bank-statement CSVs.

Wraps the Sure REST API (https://finance.zeroinside.id/api/v1):

1.  ``create_import``  -> feeds the app's native CSV import pipeline
    (``POST /imports`` with ``type=TransactionImport`` + ``account_id`` +
    ``raw_file_content`` + column configuration + ``publish=true``). The import
    job runs async on the server; ``wait_import`` polls until terminal.
2.  ``apply_rules`` -> queues a family sync so Sure's own rules categorize
    new transactions (the keyword rules live in Sure, not here).

Auth: header ``X-Api-Key`` (NOT Bearer). A browser User-Agent is required or
the server returns 403.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Set, Tuple

DEFAULT_BASE_URL = "https://finance.zeroinside.id/api/v1"
USER_AGENT = "bank-statements-converter/1.0 (sure-import)"
POLL_INTERVAL_S = 4
POLL_TIMEOUT_S = 300

# Mandiri bank statements carry 3rd-party info in the second row of each
# transaction (e.g. "From: Company ABC"). The converter already drops those.
_WS_RE = re.compile(r"\s+")


class SureAPIError(RuntimeError):
    """Raised when the Sure API returns an error status."""


def normalize_name(name: str) -> str:
    """Normalize a transaction name for dedup matching."""
    return _WS_RE.sub(" ", str(name or "").strip().upper())


def dedup_name(name: str) -> str:
    """Dedup-key name: uppercase with ALL whitespace removed.

    Existing Sure rows are stored with inconsistent whitespace (some imports
    strip newlines entirely, e.g. 'Pembayaran QRke ...' vs 'Pembayaran QR\\nke
    ...'). Collapsing to a single space is NOT enough — 'QRke' vs 'QR KE'
    still differ. Removing all whitespace makes both match.
    """
    return _WS_RE.sub("", str(name or "").upper())


def display_name(name: str) -> str:
    """User-facing name: collapse ALL whitespace (incl. newlines) to single spaces.

    The Sure backend's CSV import strips embedded newlines WITHOUT replacing
    them ('Pembayaran QR\\nke X\\n608...' -> 'Pembayaran QRke X608...'), so
    multi-line names must be flattened to spaces before sending.
    """
    return _WS_RE.sub(" ", str(name or "").strip())


def amount_to_cents(amount: float) -> int:
    """Convert a float amount (Rupiah) to integer cents (amount x 100)."""
    return int(round(abs(float(amount)) * 100))


class SureImporter:
    """Thin client over the Sure REST API used by the import pipeline."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str = USER_AGENT,
    ):
        if not api_key:
            raise ValueError("api_key is required (SURE_API_KEY env or --api-key)")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent

    # -- HTTP -------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[dict] = None,
        retries: int = 3,
    ) -> dict:
        """JSON request with retry/backoff on transient failures.

        Retries on network timeouts and HTTP 5xx (the import job can keep the
        server busy right after publish). Non-transient 4xx errors raise.
        """
        url = f"{self.base_url}{path}"
        last_error: Optional[Exception] = None
        for attempt in range(retries + 1):
            if attempt:
                time.sleep(2 ** attempt)  # 2s, 4s backoff
            try:
                return self._request_once(url, method, payload)
            except urllib.error.HTTPError as e:
                if e.code < 500 or attempt == retries:
                    detail = ""
                    try:
                        detail = e.read().decode()[:500]
                    except Exception:
                        pass
                    raise SureAPIError(
                        f"{method} {url} -> HTTP {e.code}: {detail}"
                    ) from e
                last_error = e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_error = e
        raise SureAPIError(f"{method} {url} failed after {retries} retries: {last_error}")

    def _request_once(self, url: str, method: str, payload: Optional[dict]) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "X-Api-Key": self.api_key,
                "User-Agent": self.user_agent,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode()
            return json.loads(body) if body else {}

    # -- Reads ------------------------------------------------------------

    def get_accounts(self) -> List[dict]:
        data = self._request("GET", "/accounts")
        # API returns {"accounts": [...]}; tolerate other shapes too.
        accounts = (
            data.get("accounts")
            or data.get("data")
            or (data if isinstance(data, list) else [])
        )
        return accounts if isinstance(accounts, list) else []

    def get_transactions(
        self,
        account_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[dict]:
        """Fetch ALL transactions (paginated, 50/page), optionally filtered
        by account and/or date range (start_date/end_date, YYYY-MM-DD)."""
        transactions: List[dict] = []
        page = 1
        while True:
            query = f"?per_page=50&page={page}"
            if account_id:
                query += f"&account_id={account_id}"
            if start_date:
                query += f"&start_date={start_date}"
            if end_date:
                query += f"&end_date={end_date}"
            data = self._request("GET", f"/transactions{query}")
            batch = data.get("transactions") or data.get("data") or []
            transactions.extend(batch)
            pagination = data.get("pagination") or {}
            total_pages = pagination.get("total_pages", 1)
            total_count = pagination.get("total_count", len(batch))
            if page >= total_pages or len(transactions) >= total_count or not batch:
                break
            page += 1
        return transactions

    # -- Dedup ------------------------------------------------------------

    @staticmethod
    def existing_keys(transactions: List[dict]) -> Set[Tuple[str, int, str]]:
        """Dedup key per existing transaction: (date, abs(cents), NAME)."""
        keys: Set[Tuple[str, int, str]] = set()
        for tx in transactions:
            date = (tx.get("date") or "").strip()
            cents = abs(int(tx.get("signed_amount_cents") or tx.get("amount_cents") or 0))
            name = dedup_name(tx.get("name") or "")
            if date and cents:
                keys.add((date, cents, name))
        return keys

    def split_rows(
        self, rows: List[dict], existing: List[dict]
    ) -> Tuple[List[dict], List[dict]]:
        """Split converted CSV rows into (new_rows, duplicates) vs existing tx.

        Two layers: (1) exact (date, |amount|, whitespace-stripped NAME) keys,
        (2) an email-anchor fallback — existing transactions carrying an
        "Email ref:" note were created from Mandiri email notifications and
        may have a different name than the statement row (e.g. 'DINA AYU
        SYAHPITRI HASIB' vs the bank-truncated 'DINA AYU SYAHPITRI H'). If
        enough email-created tx cover all statement rows for a (date, amount)
        key, the rows are duplicates. The count guard keeps two same-day
        same-amount payments (e.g. two -500.000 transfers) from being wrongly
        collapsed.
        """
        email_anchor: Dict[Tuple[str, int], int] = {}
        for tx in existing:
            if "email ref:" in (tx.get("notes") or "").lower():
                date = (tx.get("date") or "").strip()
                cents = abs(int(tx.get("signed_amount_cents") or tx.get("amount_cents") or 0))
                if date and cents:
                    email_anchor[(date, cents)] = email_anchor.get((date, cents), 0) + 1

        batch_count: Dict[Tuple[str, int], int] = {}
        for row in rows:
            date = str(row.get("date") or "").strip()
            try:
                amount = float(row.get("amount") or 0)
            except (TypeError, ValueError):
                amount = 0.0
            if date and amount:
                key = (date, amount_to_cents(amount))
                batch_count[key] = batch_count.get(key, 0) + 1

        keys = self.existing_keys(existing)
        new_rows: List[dict] = []
        dupes: List[dict] = []
        for row in rows:
            date = str(row.get("date") or "").strip()
            try:
                amount = float(row.get("amount") or 0)
            except (TypeError, ValueError):
                amount = 0.0
            if not date or amount == 0:
                continue  # not importable; silently drop
            dc = (date, amount_to_cents(amount))
            key = (date, amount_to_cents(amount), dedup_name(row.get("name") or ""))
            email_dupe = (
                dc in email_anchor and batch_count.get(dc, 0) <= email_anchor[dc]
            )
            (dupes if (key in keys or email_dupe) else new_rows).append(row)
        return new_rows, dupes

    # -- Writes -----------------------------------------------------------

    def create_import(
        self,
        account_id: str,
        csv_content: str,
        publish: bool = True,
        date_format: str = "%Y-%m-%d",
    ) -> dict:
        """Create a TransactionImport via the native CSV pipeline.

        Returns the import object (``data``) from the API response.
        """
        payload = {
            "type": "TransactionImport",
            "account_id": account_id,
            "raw_file_content": csv_content,
            "date_format": date_format,
            "number_format": "1,234.56",
            "signage_convention": "inflows_positive",
            "date_col_label": "date",
            "amount_col_label": "amount",
            "name_col_label": "name",
            "col_sep": ",",
            "publish": "true" if publish else "false",
        }
        data = self._request("POST", "/imports", payload)
        return data.get("data", data)

    def wait_import(
        self, import_id: str, timeout: int = POLL_TIMEOUT_S, interval: int = POLL_INTERVAL_S
    ) -> dict:
        """Poll the import until terminal (complete/failed) or timeout."""
        data: dict = {}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self._request("GET", f"/imports/{import_id}").get("data", {})
            status = data.get("status", "")
            if status in ("complete", "failed"):
                return data
            time.sleep(interval)
        return data  # last known state on timeout

    def get_import_rows(self, import_id: str) -> List[dict]:
        data = self._request("GET", f"/imports/{import_id}/rows")
        rows = data.get("data", [])
        return rows if isinstance(rows, list) else []

    def apply_rules(
        self, transactions: List[dict], timeout: int = 90, interval: int = 5
    ) -> List[dict]:
        """Have Sure categorize ``transactions`` with its own rules.

        Rules run only after a family sync, which ``POST /sync`` queues
        (creating a transaction through the API does not). Polls until every
        transaction has a category or ``timeout`` passes, then returns the
        transactions as Sure now has them. Ones no rule matches stay without
        a category.
        """
        if not transactions:
            return transactions
        self._request("POST", "/sync")
        fresh = {tx["id"]: tx for tx in transactions}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(interval)
            for tx_id, tx in fresh.items():
                if not tx.get("category"):
                    fresh[tx_id] = {**tx, **self._request("GET", f"/transactions/{tx_id}")}
            if all(tx.get("category") for tx in fresh.values()):
                break
        return list(fresh.values())

    def delete_transactions(self, transaction_ids: List[str]) -> int:
        deleted = 0
        for tx_id in transaction_ids:
            try:
                self._request("DELETE", f"/transactions/{tx_id}")
                deleted += 1
            except SureAPIError:
                pass
        return deleted
