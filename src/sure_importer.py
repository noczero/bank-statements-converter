"""Sure Finance API client for importing converted bank-statement CSVs.

Wraps the Sure REST API (https://finance.zeroinside.id/api/v1):

1.  ``create_import``  -> feeds the app's native CSV import pipeline
    (``POST /imports`` with ``type=TransactionImport`` + ``account_id`` +
    ``raw_file_content`` + column configuration + ``publish=true``). The import
    job runs async on the server; ``wait_import`` polls until terminal.
2.  ``categorize_transactions`` -> PATCHes categories using a regex taxonomy
    on the transaction name (bank fees, BPJS, Shopee, ...).

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

# Category classification taxonomy — regexes matched against the UPPERCASED
# transaction name. Order matters: bank-fee patterns first, then merchants.
CATEGORY_RULES: List[Tuple[str, str]] = [
    (r"BIAYA TRANSAKSI BANK|BIAYA ADMINISTRASI|BIAYA TRANSFER", "Fees"),
    (r"BPJS KESEHATAN", "Insurance"),
    (r"SALARY|GAJI", "Salary"),
    (r"SAMSAT", "Taxes"),
    (r"MESJID|QURBAN|ZAKAT|MASJID", "Gifts & Donations"),
    (r"TRAVELOKA", "Travel"),
    (r"SEABANK|SAQU INDONESIA", "Cash Out"),
    (r"BANK RAKYAT INDONESIA", "Loan Payments"),
    (r"SHOPEE|TOKOPEDIA", "Shopping"),
    (r"SHOES AND CARE|RING SHOES CARE", "Shopping"),
    (r"MARUGAME", "Food & Drink"),
]

# Mandiri bank statements carry 3rd-party info in the second row of each
# transaction (e.g. "From: Company ABC"). The converter already drops those.
_WS_RE = re.compile(r"\s+")


class SureAPIError(RuntimeError):
    """Raised when the Sure API returns an error status."""


def normalize_name(name: str) -> str:
    """Normalize a transaction name for dedup matching."""
    return _WS_RE.sub(" ", str(name or "").strip().upper())


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

    def get_categories(self) -> Dict[str, str]:
        """Return {category_name: uuid} from /categories."""
        data = self._request("GET", "/categories")
        items = (
            data.get("categories")
            or data.get("data")
            or (data if isinstance(data, list) else [])
        )
        if not isinstance(items, list):
            return {}
        return {c.get("name"): c.get("id") for c in items if c.get("id")}

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
            name = normalize_name(tx.get("name") or "")
            if date and cents:
                keys.add((date, cents, name))
        return keys

    def split_rows(
        self, rows: List[dict], existing: List[dict]
    ) -> Tuple[List[dict], List[dict]]:
        """Split converted CSV rows into (new_rows, duplicates) vs existing tx."""
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
            key = (date, amount_to_cents(amount), normalize_name(row.get("name") or ""))
            (dupes if key in keys else new_rows).append(row)
        return new_rows, dupes

    # -- Classification ---------------------------------------------------

    @classmethod
    def classify(cls, name: str) -> Optional[str]:
        """Return the category name for a transaction name, or None."""
        upper = normalize_name(name)
        if not upper:
            return None
        for pattern, category in CATEGORY_RULES:
            if re.search(pattern, upper):
                return category
        return None

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

    def categorize_transactions(
        self, transactions: List[dict], categories_by_name: Dict[str, str]
    ) -> Tuple[int, List[str]]:
        """PATCH categories for transactions whose name matches the taxonomy.

        Returns (categorized_count, skipped_names_without_category).
        """
        categorized = 0
        skipped: List[str] = []
        for tx in transactions:
            category = self.classify(tx.get("name") or "")
            if not category:
                continue
            category_id = categories_by_name.get(category)
            if not category_id:
                skipped.append(category)
                continue
            self._request(
                "PATCH", f"/transactions/{tx['id']}", {"category_id": category_id}
            )
            categorized += 1
        return categorized, skipped

    def delete_transactions(self, transaction_ids: List[str]) -> int:
        deleted = 0
        for tx_id in transaction_ids:
            try:
                self._request("DELETE", f"/transactions/{tx_id}")
                deleted += 1
            except SureAPIError:
                pass
        return deleted
