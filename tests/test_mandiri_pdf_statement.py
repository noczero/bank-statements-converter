import pytest

from src.mandiri_pdf_statement import parse_lines

# Text as pdfplumber extracts it from a Mandiri statement PDF (numbers changed).
LINES = """Periode / Period: 1/10/24 s/d 31/10/24
Tanggal Tanggal Rincian Transaksi / Nomor Referensi Debit / Kredit Saldo
01/10 Saldo Awal 1,000,000.00
02/10 02/10 -UBP123456789012345FFFFFF1234567890121 30,000.00 D 970,000.00
03/10 03/10 -123456789012 25,000.00 D 945,000.00
IRONMAN LAUNDRY
123456789012720
Hal Page 3 of 7
P age
Tanggal Tanggal Rincian Transaksi / Nomor Referensi Debit / Kredit Saldo
25/10 25/10 -20241025CENAIDJA010O123456789 500,000.00 1,445,000.00
CENAIDJA/WISE PAYMENTS INDONESIA
31/10 31/10 Biaya Adm - 12,500.00 D 1,432,500.00
Saldo Awal / Previous Balance : 1,000,000.00
Mutasi Kredit / Total of Credit Transactions : 500,000.00
Saldo Akhir / Current Balance : 1,432,500.00""".splitlines()


def test_rows_names_and_signs():
    rows, opening, closing = parse_lines(LINES)
    assert (opening, closing) == (1_000_000.0, 1_432_500.0)
    assert [(r["date"], r["amount"], r["name"]) for r in rows] == [
        ("2024-10-02", -30_000.0, "Pembayaran UBP"),
        ("2024-10-03", -25_000.0, "IRONMAN LAUNDRY"),  # name from the line below, page footer skipped
        ("2024-10-25", 500_000.0, "CENAIDJA WISE PAYMENTS INDONESIA"),  # no "D": credit
        ("2024-10-31", -12_500.0, "Biaya Adm"),
    ]


def test_broken_balance_chain_raises():
    bad = [l.replace("945,000.00", "946,000.00") for l in LINES]
    with pytest.raises(ValueError, match="balance chain"):
        parse_lines(bad)
