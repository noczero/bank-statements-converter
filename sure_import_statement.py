#!/usr/bin/env python3
"""Convert a Mandiri bank statement (.xlsx) and import it into Sure Finance.

Pipeline:
    1. Convert the (optionally password-protected) Excel statement to CSV
       using MandiriBankStatementConverter.
    2. Normalize the CSV to Sure's import schema (date/amount/name).
    3. Dedup against existing Mandiri transactions (date + amount + name).
    4. Create a native Sure TransactionImport via the REST API (publish=true).
    5. Poll until the import job finishes and print a summary.

Environment variables (or .env in this repo):
    MANDIRI_BANK_STATEMENT_PASSWORD   password for encrypted Mandiri Excel
    SURE_API_KEY                      X-Api-Key for finance.zeroinside.id
    SURE_BASE_URL                     default https://finance.zeroinside.id/api/v1

Examples:
    # Preview only (no writes to Sure)
    python sure_import_statement.py bank-statements/mandiri/statement.xlsx --dry-run

    # Convert + import + auto-categorize using the known taxonomy
    python sure_import_statement.py bank-statements/mandiri/statement.xlsx --categorize

    # Import without auto-publishing (reviewable in the app, then publish)
    python sure_import_statement.py statement.xlsx --no-publish
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from typing import List, Optional

import pandas as pd
from dotenv import load_dotenv

from src.mandiri_bank_statement_converter import MandiriBankStatementConverter
from src.sure_importer import (
    DEFAULT_BASE_URL,
    SureAPIError,
    SureImporter,
)

CSV_COLUMNS = ["date", "amount", "name"]


def load_env() -> None:
    load_dotenv()  # repo .env
    # Fall back to the Hermes-managed env file if SURE_API_KEY is absent.
    if not os.getenv("SURE_API_KEY"):
        hermes_env = os.path.expanduser("~/.hermes/.env")
        if os.path.exists(hermes_env):
            load_dotenv(hermes_env)


def normalize_csv(csv_path: str) -> str:
    """Read the converter CSV and emit Sure-ready CSV (date,amount,name)."""
    df = pd.read_csv(csv_path, dtype=str)
    df = df.rename(columns={"date*": "date", "amount*": "amount"})
    missing = [c for c in CSV_COLUMNS if c not in df.columns]
    if missing:
        raise SystemExit(f"Converted CSV missing required columns: {missing}")

    df = df[CSV_COLUMNS].copy()
    df["date"] = df["date"].fillna("").str.strip()
    df["amount"] = pd.to_numeric(df["amount"].str.replace(",", "", regex=False), errors="coerce")
    df["name"] = df["name"].fillna("").str.strip()
    df = df.dropna(subset=["amount"])
    df = df[df["amount"] != 0]

    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def pick_account(importer: SureImporter, name: str) -> str:
    accounts = importer.get_accounts()
    for acc in accounts:
        if (acc.get("name") or "").lower() == name.lower():
            return acc["id"]
    raise SystemExit(
        f"Account '{name}' not found. Available: "
        + ", ".join(a.get("name", "?") for a in accounts)
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("statement", help="Path to the Mandiri .xlsx bank statement")
    parser.add_argument("--dry-run", action="store_true", help="Convert + dedup only, no API writes")
    parser.add_argument("--no-publish", action="store_true", help="Create the import but don't publish")
    parser.add_argument("--categorize", action="store_true", help="Auto-categorize imported tx (taxonomy)")
    parser.add_argument("--account", default="Mandiri", help="Sure account name to import into (default: Mandiri)")
    parser.add_argument("--password", default=None, help="Excel password (overrides env)")
    parser.add_argument("--api-key", default=None, help="Sure API key (overrides env)")
    parser.add_argument("--base-url", default=os.getenv("SURE_BASE_URL", DEFAULT_BASE_URL))
    args = parser.parse_args(argv)

    load_env()

    if not os.path.exists(args.statement):
        parser.error(f"statement not found: {args.statement}")

    # 1. Convert ----------------------------------------------------------
    print(f"[1/4] Converting {args.statement} ...")
    converter = MandiriBankStatementConverter(password=args.password)
    output_path = converter.convert_file(args.statement)
    if not output_path:
        print("  (already converted — reusing existing CSV)")
        output_path = os.path.join(
            converter.results_folder,
            converter.get_output_filename(args.statement),
        )
    csv_content = normalize_csv(output_path)
    rows = pd.read_csv(io.StringIO(csv_content), dtype=str).to_dict("records")
    print(f"  {len(rows)} transaction(s) parsed from statement")

    # 2. Connect + dedup ---------------------------------------------------
    api_key = args.api_key or os.getenv("SURE_API_KEY")
    if not api_key:
        print("ERROR: SURE_API_KEY not set (export it or add to .env)", file=sys.stderr)
        return 2
    importer = SureImporter(api_key=api_key, base_url=args.base_url)

    account_id = pick_account(importer, args.account)
    # Dedup only needs the statement's own date range — keeps the fetch to
    # 1-2 pages instead of the whole account history.
    dates = [r["date"] for r in rows if r.get("date")]
    start_date, end_date = (min(dates), max(dates)) if dates else (None, None)
    print(f"[2/4] Fetching existing '{args.account}' transactions ({start_date}..{end_date}) ...")
    existing = importer.get_transactions(
        account_id=account_id, start_date=start_date, end_date=end_date
    )
    new_rows, dupes = importer.split_rows(rows, existing)
    print(f"  {len(new_rows)} new, {len(dupes)} already in Sure (skipped)")

    if args.dry_run:
        print("\n=== DRY RUN — no changes made to Sure ===")
        for row in new_rows[:10]:
            print(f"  {row['date']}  {float(row['amount']):>15,.0f}  {row['name']}")
        if len(new_rows) > 10:
            print(f"  ... and {len(new_rows) - 10} more")
        if dupes:
            print(f"\n  Duplicates skipped ({len(dupes)}):")
            for row in dupes[:5]:
                print(f"  {row['date']}  {float(row['amount']):>15,.0f}  {row['name']}")
        return 0

    # 3. Create import ------------------------------------------------------
    print(f"[3/4] Creating Sure import ({'publish' if not args.no_publish else 'no-publish'}) ...")
    csv_out = _to_csv(new_rows)
    if not new_rows:
        print("  Nothing new to import.")
        return 0
    import_obj = importer.create_import(
        account_id=account_id,
        csv_content=csv_out,
        publish=not args.no_publish,
    )
    import_id = import_obj.get("id")
    print(f"  Import {import_id} created (status: {import_obj.get('status')})")

    if args.no_publish:
        print(f"\nReview it at https://finance.zeroinside.id/imports/{import_id}")
        print("Publish it there when you're happy.")
        return 0

    # 4. Wait for completion ------------------------------------------------
    print("[4/4] Waiting for import job ...")
    final = importer.wait_import(import_id)
    status = final.get("status")
    stats = final.get("stats") or {}
    print(f"  Final status: {status}")
    if status != "complete":
        print(f"  error: {final.get('error') or 'unknown'}")
        return 1

    imported = stats.get("valid_rows_count", len(new_rows))
    invalid = stats.get("invalid_rows_count", 0)
    summary = final.get("summary") or {}
    created = summary.get("created", imported)
    print(f"  rows imported={created} invalid={invalid}")
    print(f"\nDone. {len(new_rows)} statement row(s) imported into Sure ({args.account}).")
    print(f"Import record: https://finance.zeroinside.id/imports/{import_id}")

    # 5. Optional categorization --------------------------------------------
    if args.categorize and new_rows:
        print("\nCategorizing imported transactions ...")
        # Match back the created transactions by dedup key (date, cents, name).
        keys = {
            (r["date"].strip(), int(round(abs(float(r["amount"])) * 100)),
             (r["name"] or "").strip().upper())
            for r in new_rows
        }
        fresh = importer.get_transactions(
            account_id=account_id, start_date=start_date, end_date=end_date
        )
        created_tx = [tx for tx in fresh if _tx_key(tx) in keys]
        categories = importer.get_categories()
        count, skipped = importer.categorize_transactions(created_tx, categories)
        print(f"  categorized {count} transaction(s)")
        for name in skipped:
            print(f"  WARN: category '{name}' not found in Sure — skipped")
    return 0


def _tx_key(tx: dict):
    date = (tx.get("date") or "").strip()
    cents = abs(int(tx.get("signed_amount_cents") or tx.get("amount_cents") or 0))
    name = (tx.get("name") or "").strip().upper()
    return (date, cents, name)


def _to_csv(rows: List[dict]) -> str:
    import csv

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in CSV_COLUMNS})
    return buf.getvalue()


if __name__ == "__main__":
    sys.exit(main())
