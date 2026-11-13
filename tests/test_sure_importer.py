"""Tests for the Sure Finance importer (src/sure_importer.py)."""

import pytest

from src.sure_importer import (
    SureImporter,
    amount_to_cents,
    normalize_name,
)


class TestSureImporterHelpers:
    def test_normalize_name_uppercases_and_collapses(self):
        assert normalize_name("  Shopee   Pay  ") == "SHOPEE PAY"
        assert normalize_name(None) == ""

    def test_amount_to_cents_rounds(self):
        assert amount_to_cents(150000.0) == 15000000
        assert amount_to_cents(-25000.55) == 2500055
        assert amount_to_cents(0.0) == 0


class TestSureImporterDedup:
    def test_existing_keys(self):
        tx = [
            {
                "date": "2026-08-01",
                "signed_amount_cents": -15000000,
                "amount_cents": 15000000,
                "name": "Shopee Pay",
            },
            {"date": "2026-08-02", "signed_amount_cents": 500000000, "name": "Salary"},
            {"date": "", "signed_amount_cents": 0, "name": "No date"},
        ]
        keys = SureImporter.existing_keys(tx)
        assert ("2026-08-01", 15000000, "SHOPEEPAY") in keys
        assert ("2026-08-02", 500000000, "SALARY") in keys
        # Empty date / zero amount rows are excluded from the key set.
        assert len(keys) == 2

    def test_split_rows_new_and_dupes(self):
        importer = SureImporter(api_key="test")
        rows = [
            {"date": "2026-08-01", "amount": "-150000.0", "name": "Shopee Pay"},
            {"date": "2026-08-03", "amount": "75000.0", "name": "New Income"},
            {"date": "2026-08-04", "amount": "0.0", "name": "Ignored Zero"},
            {"date": "", "amount": "1000.0", "name": "Ignored No Date"},
        ]
        existing = [
            {"date": "2026-08-01", "signed_amount_cents": -15000000, "name": "shopee pay"}
        ]
        new_rows, dupes = importer.split_rows(rows, existing)
        assert len(new_rows) == 1
        assert new_rows[0]["name"] == "New Income"
        assert len(dupes) == 1
        assert dupes[0]["name"] == "Shopee Pay"

    def test_split_rows_case_insensitive_name_match(self):
        importer = SureImporter(api_key="test")
        rows = [{"date": "2026-08-05", "amount": "-50000.0", "name": "ATM WITHDRAWAL"}]
        existing = [{"date": "2026-08-05", "signed_amount_cents": -5000000, "name": "atm withdrawal"}]
        new_rows, dupes = importer.split_rows(rows, existing)
        assert new_rows == []
        assert len(dupes) == 1

    def test_split_rows_whitespace_variant_name_match(self):
        # Regression: old imports stored 'Pembayaran QRke ...' (newline stripped,
        # no space) while the converter now keeps 'Pembayaran QR\\nke ...'. Both
        # are the SAME transaction — dedup must catch it (2026-08-17 incident:
        # 9 duplicates imported because 'QRke' vs 'QR KE' mismatched).
        importer = SureImporter(api_key="test")
        rows = [{
            "date": "2025-09-12", "amount": "-150000.0",
            "name": "Pembayaran QR\nke PPPSRS THE JARDIN APPARTE\n509125378058",
        }]
        existing = [{
            "date": "2025-09-12", "signed_amount_cents": -15000000,
            "name": "Pembayaran QRke PPPSRS THE JARDIN APPARTE509125378058",
        }]
        new_rows, dupes = importer.split_rows(rows, existing)
        assert new_rows == []
        assert len(dupes) == 1

    def test_split_rows_email_anchor_fallback(self):
        # Regression: email-created tx carry an "Email ref:" note and a
        # different name than the statement row ('DINA AYU SYAHPITRI HASIB'
        # vs the bank-truncated 'DINA AYU SYAHPITRI H'). The statement row
        # must be treated as a duplicate (email automation 2026-08-17).
        importer = SureImporter(api_key="test")
        rows = [{
            "date": "2026-08-13", "amount": "-1100000.0",
            "name": "Transfer BI Fast Ke BCA DINA AYU SYAHPITRI H 613624578",
        }]
        existing = [{
            "date": "2026-08-13", "signed_amount_cents": -110000000,
            "name": "Transfer BI Fast Ke BCA DINA AYU SYAHPITRI HASIB 0613624578",
            "notes": "Email ref: 20260813BMRIIDJA010O0224743457 (msgid)",
        }]
        new_rows, dupes = importer.split_rows(rows, existing)
        assert new_rows == []
        assert len(dupes) == 1

    def test_split_rows_email_anchor_count_guard(self):
        # Two same-day same-amount transfers (e.g. PAINO/SYAMSINAR -500.000)
        # where only ONE was email-created: the second statement row is NOT a
        # duplicate and must be imported.
        importer = SureImporter(api_key="test")
        rows = [
            {"date": "2026-07-29", "amount": "-500000.0",
             "name": "Transfer ke BANK MANDIRI PAINO 1050014083699"},
            {"date": "2026-07-29", "amount": "-500000.0",
             "name": "Transfer ke BANK MANDIRI SYAMSINAR 1050012558668"},
        ]
        existing = [{
            "date": "2026-07-29", "signed_amount_cents": -50000000,
            "name": "Transfer ke BANK MANDIRI PAINO 1050014083699",
            "notes": "Email ref: 260729123 (msgid)",
        }]
        new_rows, dupes = importer.split_rows(rows, existing)
        assert len(dupes) == 1  # PAINO covered by email anchor
        assert len(new_rows) == 1
        assert new_rows[0]["name"] == "Transfer ke BANK MANDIRI SYAMSINAR 1050012558668"


class TestSureImporterApi:
    def test_requires_api_key(self):
        with pytest.raises(ValueError):
            SureImporter(api_key="")

    def test_apply_rules_syncs_then_polls_until_categorized(self, monkeypatch):
        importer = SureImporter(api_key="test")
        calls = []
        polls = {"tx1": 0}

        def fake_request(method, path, payload=None):
            calls.append((method, path))
            if path == "/transactions/tx1":
                polls["tx1"] += 1  # rules land on the second poll
                return {"category": {"name": "Fees"}} if polls["tx1"] > 1 else {"category": None}
            return {}

        monkeypatch.setattr(importer, "_request", fake_request)
        monkeypatch.setattr("src.sure_importer.time.sleep", lambda _: None)
        tx = [{"id": "tx1", "name": "Biaya transfer"}, {"id": "tx2", "category": {"name": "Salary"}}]
        result = importer.apply_rules(tx)
        assert calls[0] == ("POST", "/sync")
        assert calls.count(("GET", "/transactions/tx1")) == 2
        assert ("GET", "/transactions/tx2") not in calls  # already categorized
        assert [t["category"]["name"] for t in result] == ["Fees", "Salary"]

    def test_get_transactions_paginates(self, monkeypatch):
        importer = SureImporter(api_key="test")
        pages = [
            {"transactions": [{"id": "a"}], "pagination": {"total_count": 2, "total_pages": 2}},
            {"transactions": [{"id": "b"}], "pagination": {"total_count": 2, "total_pages": 2}},
        ]

        def fake_request(method, path, payload=None):
            import re

            page = int(re.search(r"[?&]page=(\d+)", path).group(1))
            return pages[page - 1]

        monkeypatch.setattr(importer, "_request", fake_request)
        result = importer.get_transactions(account_id="acc-1")
        assert [t["id"] for t in result] == ["a", "b"]

    def test_display_name_flattens_multiline_names(self):
        # Regression: Sure's backend strips embedded newlines without replacing
        # them ('Pembayaran QR\nke X\n608...' -> 'Pembayaran QRke X608...'), so
        # the pipeline must flatten multi-line names to single spaces first.
        from src.sure_importer import display_name

        assert (
            display_name("Pembayaran QR\nke CAFFE EDELWIS\n608544838726")
            == "Pembayaran QR ke CAFFE EDELWIS 608544838726"
        )
        assert (
            display_name("Transfer BI Fast\nKe BSI\nNURMIATI QQ RADIFAH 7103833633")
            == "Transfer BI Fast Ke BSI NURMIATI QQ RADIFAH 7103833633"
        )
        assert display_name("  Biaya transfer BI Fast  ") == "Biaya transfer BI Fast"
        assert display_name("") == ""
