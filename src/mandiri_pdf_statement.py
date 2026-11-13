"""Parse a Mandiri "Rekening Koran / Statement of Account" PDF (the monthly
ConsolidatedStatement e-mail attachment) into the same CSV the Excel
converter writes (date*, amount*, name).

Every transaction row carries the running balance, so each row is checked
against the previous balance, and the whole month against the statement's
"Saldo Awal" / "Saldo Akhir". A statement that doesn't add up raises instead
of producing a CSV.
"""

from __future__ import annotations

import csv
import os
import re
from datetime import date
from typing import List, Optional, Tuple

import pdfplumber

ROW = re.compile(
    r"^(\d{2})/(\d{2}) \d{2}/\d{2} (.*?) ?([\d,]+\.\d{2})( D)? (-?[\d,]+\.\d{2})$"
)
PERIOD = re.compile(r"Period: *\d{1,2}/\d{1,2}/(\d{2}) s/d \d{1,2}/(\d{1,2})/(\d{2})")
OPENING = re.compile(r"Saldo Awal / Previous Balance : *(-?[\d,]+\.\d{2})")
CLOSING = re.compile(r"Saldo Akhir / Current Balance : *(-?[\d,]+\.\d{2})")
# Page headers/footers and summary lines that sit between transaction lines.
NOISE = re.compile(
    r"^(Tanggal Tanggal|Transaksi Valuta|Transaction Valuta|Date Date|Hal Page|P age"
    r"|Saldo Awal|Mutasi (Kredit|Debit)|Saldo Akhir|\d{2}/\d{2} Saldo Awal)"
)
LONG_NUMBER = re.compile(r"\d{8,}")


def money(s: str) -> float:
    return float(s.replace(",", ""))


ATM_CODE = re.compile(r"^S1[A-Z0-9]{6}$")
# Bank channel codes -> readable words
CODES = {"VAP": "Pembayaran VA", "ATM": "ATM", "BilPymDbCustAc": "Pembayaran tagihan",
         "JPN": "JPN", "MCM": "", "InhouseTrf": "Transfer"}


def clean_name(parts: List[str]) -> str:
    """Drop reference numbers and codes, keep the words (merchant, payee)."""
    raw = " ".join(parts)
    words: List[str] = []
    for tok in re.split(r"[\s/-]+", raw):
        tok = CODES.get(tok, tok)
        if (not tok or LONG_NUMBER.search(tok) or tok.startswith("UBP")
                or ATM_CODE.match(tok) or re.fullmatch(r"\d{8}", tok) or tok in words):
            continue
        words.append(tok)
    name = " ".join(words)
    if not name:
        if "UBP" in raw:
            name = "Pembayaran UBP"  # bill or e-wallet payment; the PDF names no payee
        elif "BMRIIDJA" in raw or "CENAIDJA" in raw:
            name = "Transfer antar bank"
        else:
            name = "Transaksi"
    return name


def parse(path: str, password: Optional[str] = None) -> Tuple[List[dict], float, float]:
    """Return (rows, opening, closing). Rows: {date, amount, name}."""
    with pdfplumber.open(path, password=password or "") as pdf:
        lines = [l.strip() for p in pdf.pages for l in (p.extract_text() or "").splitlines()]
    return parse_lines(lines, path)


def parse_lines(lines: List[str], path: str = "statement") -> Tuple[List[dict], float, float]:
    text = "\n".join(lines)

    period = PERIOD.search(text)
    opening, closing = OPENING.search(text), CLOSING.search(text)
    if not (period and opening and closing):
        raise ValueError(f"{path}: period or opening/closing balance not found")
    end_month, end_year = int(period.group(2)), 2000 + int(period.group(3))
    opening, closing = money(opening.group(1)), money(closing.group(1))

    rows: List[dict] = []
    balance = opening
    current = None
    for line in lines:
        m = ROW.match(line)
        if m:
            day, month, details, amount, debit, new_balance = m.groups()
            amount = -money(amount) if debit else money(amount)
            if round(balance + amount, 2) != money(new_balance):
                raise ValueError(f"{path}: balance chain breaks at {line!r}")
            balance = money(new_balance)
            year = end_year - 1 if int(month) > end_month else end_year
            current = {"date": date(year, int(month), int(day)).isoformat(),
                       "amount": amount, "parts": [details]}
            rows.append(current)
        elif current is not None and not NOISE.match(line):
            current["parts"].append(line)
        if line.startswith("Saldo Awal / Previous Balance"):
            current = None  # summary block: nothing after it belongs to a row

    if round(balance, 2) != closing:
        raise ValueError(f"{path}: rows end at {balance:,.2f}, statement closes at {closing:,.2f}")
    for r in rows:
        r["name"] = clean_name(r.pop("parts"))
    return rows, opening, closing


def convert(path: str, results_folder: str = "results", password: Optional[str] = None) -> str:
    """Write the converter-style CSV and return its path."""
    rows, _, _ = parse(path, password)
    os.makedirs(results_folder, exist_ok=True)
    out = os.path.join(results_folder, os.path.splitext(os.path.basename(path))[0] + "_converted.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date*", "amount*", "name"])
        for r in rows:
            w.writerow([r["date"], r["amount"], r["name"]])
    return out


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    pw = os.getenv("MANDIRI_BANK_STATEMENT_PASSWORD")
    for p in sys.argv[1:]:
        try:
            rows, o, c = parse(p, pw)
            print(f"OK   {os.path.basename(p)}  rows={len(rows)}  open={o:,.2f}  close={c:,.2f}")
        except Exception as e:
            print(f"FAIL {os.path.basename(p)}  {e}")
