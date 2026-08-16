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
        assert ("2026-08-01", 15000000, "SHOPEE PAY") in keys
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


class TestSureImporterClassify:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Pembayaran BPJS Kesehatan Keluarga", "Insurance"),
            ("SALARY DEPOSIT", "Salary"),
            ("TRF GAJI BULANAN", "Salary"),
            ("Biaya transaksi bank 1000", "Fees"),
            ("BIAYA ADMINISTRASI BULANAN", "Fees"),
            ("SHOPEE PAY", "Shopping"),
            ("Tokopedia - Pembayaran", "Shopping"),
            ("SAMSAT KENDARAAN", "Taxes"),
            ("TRAVELOKA HOTEL", "Travel"),
            ("SEABANK TRANSFER", "Cash Out"),
            ("BANK RAKYAT INDONESIA", "Loan Payments"),
            ("MARUGAME BANDUNG", "Food & Drink"),
            ("Indomaret", None),
            ("", None),
        ],
    )
    def test_classify(self, name, expected):
        assert SureImporter.classify(name) == expected


class TestSureImporterApi:
    def test_requires_api_key(self):
        with pytest.raises(ValueError):
            SureImporter(api_key="")

    def test_categorize_transactions_patches(self, monkeypatch):
        importer = SureImporter(api_key="test")
        patched = []

        def fake_request(method, path, payload=None):
            patched.append((method, path, payload))
            return {}

        monkeypatch.setattr(importer, "_request", fake_request)
        tx = [{"id": "tx1", "name": "BPJS KESEHATAN"}, {"id": "tx2", "name": "Unknown Merchant"}]
        categories = {"Insurance": "cat-insurance"}
        count, skipped = importer.categorize_transactions(tx, categories)
        assert count == 1
        assert skipped == []
        assert patched == [("PATCH", "/transactions/tx1", {"category_id": "cat-insurance"})]

    def test_categorize_skips_missing_category(self, monkeypatch):
        importer = SureImporter(api_key="test")
        patched = []

        def fake_request(method, path, payload=None):
            patched.append((method, path, payload))
            return {}

        monkeypatch.setattr(importer, "_request", fake_request)
        tx = [{"id": "tx1", "name": "BPJS KESEHATAN"}]
        count, skipped = importer.categorize_transactions(tx, {"Insurance": None})
        assert count == 0
        assert skipped == ["Insurance"]
        assert patched == []

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
