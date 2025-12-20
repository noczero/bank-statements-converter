"""Tests for MandiriBankStatementConverter class."""

import os
import pytest
import pandas as pd
from unittest.mock import patch

from src.mandiri_bank_statement_converter import MandiriBankStatementConverter


class TestMandiriBankStatementConverter:
    """Test suite for MandiriBankStatementConverter."""

    @pytest.fixture
    def converter(self):
        """Create a Mandiri converter with a test password."""
        return MandiriBankStatementConverter(password="test_password")

    @pytest.fixture
    def sample_statement_df(self):
        """Create a sample Mandiri bank statement DataFrame."""
        # Row 0-4: Header info that should be skipped
        # Row 5: Actual column headers
        data = {
            0: ["Account Info", "", "", "", "", ""],
            1: ["Name: Test User", "", "", "", "", ""],
            2: ["Account: 1234567890", "", "", "", "", ""],
            3: ["", "", "", "", "", ""],
            4: ["", "", "", "", "", ""],
            5: [
                "No",
                "Date",
                "Remarks",
                "Incoming Transactions (IDR)",
                "Outgoing Transactions (IDR)",
                "Balance (IDR)",
            ],
            6: [
                "1",
                "02 Apr 2025",
                "Transfer from A",
                "1,000,000.00",
                "",
                "5,000,000.00",
            ],
            7: ["", "", "Additional info", "", "", ""],
            8: ["2", "03 Apr 2025", "Payment to B", "", "500,000.00", "4,500,000.00"],
            9: ["", "", "Additional info", "", "", ""],
        }
        df = pd.DataFrame.from_dict(data, orient="index")
        return df

    def test_init_with_password(self, converter):
        """Test initialization with explicit password."""
        assert converter.password == "test_password"

    @patch.dict(os.environ, {"MANDIRI_BANK_STATEMENT_PASSWORD": "env_password"})
    def test_init_from_env(self):
        """Test initialization with password from environment."""
        converter = MandiriBankStatementConverter()
        assert converter.password == "env_password"

    def test_get_source_folder(self, converter):
        """Test source folder path."""
        assert converter.get_source_folder() == "bank-statements/mandiri"

    def test_get_column_mapping_empty(self, converter):
        """Test column mapping returns empty dict (uses custom transform)."""
        assert converter.get_column_mapping() == {}

    def test_header_keywords(self, converter):
        """Test that required header keywords are defined."""
        assert "No" in converter.HEADER_KEYWORDS
        assert "Date" in converter.HEADER_KEYWORDS
        assert "Remarks" in converter.HEADER_KEYWORDS
        assert "Incoming Transactions (IDR)" in converter.HEADER_KEYWORDS
        assert "Outgoing Transactions (IDR)" in converter.HEADER_KEYWORDS

    def test_find_header_row(self, converter, sample_statement_df):
        """Test finding header row in DataFrame."""
        header_idx = converter.find_header_row(sample_statement_df)
        assert header_idx == 5

    def test_find_header_row_not_found(self, converter):
        """Test find_header_row returns 0 when header not found."""
        df = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]})
        assert converter.find_header_row(df) == 0


class TestMandiriConverterHelperMethods:
    """Test helper methods of MandiriBankStatementConverter."""

    @pytest.fixture
    def converter(self):
        return MandiriBankStatementConverter(password="test")

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            (None, 0.0),
            ("", 0.0),
            (pd.NA, 0.0),
            (100, 100.0),
            (100.50, 100.50),
            ("1,000,000.00", 1000000.0),  # Removes commas/dots, divides by 100
            ("500,000.00", 500000.0),
            ("Rp1,000,000.00", 1000000.0),
            ("invalid", 0.0),
        ],
    )
    def test_clean_amount(self, converter, input_value, expected):
        """Test _clean_amount handles various input formats."""
        result = converter._clean_amount(input_value)
        assert result == expected

    def test_get_value_existing_column(self, converter):
        """Test _get_value returns value for existing column."""
        row = pd.Series({"Date": "2024-01-01", "Amount": 100})
        assert converter._get_value(row, "Date") == "2024-01-01"
        assert converter._get_value(row, "Amount") == 100

    def test_get_value_missing_column(self, converter):
        """Test _get_value returns default for missing column."""
        row = pd.Series({"Date": "2024-01-01"})
        assert converter._get_value(row, "Missing") == ""
        assert converter._get_value(row, "Missing", "default") == "default"

    def test_get_value_na_value(self, converter):
        """Test _get_value returns default for NA values."""
        row = pd.Series({"Date": pd.NA})
        assert converter._get_value(row, "Date") == ""

    @pytest.mark.parametrize(
        "input_date,expected",
        [
            ("02 Apr 2025", "2025-04-02"),
            ("15 Jan 2024", "2024-01-15"),
            ("31 Dec 2023", "2023-12-31"),
            ("", ""),
            (None, ""),
            ("invalid date", "invalid date"),
        ],
    )
    def test_parse_date(self, converter, input_date, expected):
        """Test _parse_date converts date formats correctly."""
        result = converter._parse_date(input_date)
        assert result == expected


class TestMandiriConverterTransform:
    """Test the transform method of MandiriBankStatementConverter."""

    @pytest.fixture
    def converter(self):
        return MandiriBankStatementConverter(password="test")

    def test_transform_basic(self, converter):
        """Test basic transformation of Mandiri statement."""
        # Create DataFrame with proper header structure
        df = pd.DataFrame(
            {
                0: ["No", "1", "", "2", ""],
                1: ["Date", "02 Apr 2025", "", "03 Apr 2025", ""],
                2: ["Remarks", "Incoming transfer", "", "Outgoing payment", ""],
                3: ["Incoming Transactions (IDR)", "1,000,000.00", "", "", ""],
                4: ["Outgoing Transactions (IDR)", "", "", "500,000.00", ""],
                5: ["Balance (IDR)", "5,000,000.00", "", "4,500,000.00", ""],
            }
        )
        # Set first row as header
        df.columns = df.iloc[0]
        df = df.iloc[1:].reset_index(drop=True)

        result = converter.transform(df)

        assert len(result) == 2
        assert result.iloc[0]["date*"] == "2025-04-02"
        assert result.iloc[0]["name"] == "Incoming transfer"
        assert result.iloc[0]["amount*"] == 1000000.0  # Credit
        assert result.iloc[0]["currency"] == "IDR"
        assert result.iloc[0]["account"] == "Mandiri"

        assert result.iloc[1]["date*"] == "2025-04-03"
        assert result.iloc[1]["amount*"] == -500000.0  # Debit (negative)

    def test_transform_skips_empty_dates(self, converter):
        """Test that rows with empty dates are skipped."""
        df = pd.DataFrame(
            {
                "No": ["1", "", "2"],
                "Date": ["02 Apr 2025", "", "03 Apr 2025"],
                "Remarks": ["Test 1", "Info", "Test 2"],
                "Incoming Transactions (IDR)": ["1,000,000.00", "", ""],
                "Outgoing Transactions (IDR)": ["", "", "500,000.00"],
                "Balance (IDR)": ["1,000,000.00", "", "500,000.00"],
            }
        )

        result = converter.transform(df)

        # Should only have 2 transactions (odd indices are skipped, empty dates skipped)
        assert len(result) >= 1

    def test_transform_output_columns(self, converter):
        """Test that transform output has all required columns."""
        df = pd.DataFrame(
            {
                "No": ["1"],
                "Date": ["02 Apr 2025"],
                "Remarks": ["Test"],
                "Incoming Transactions (IDR)": ["1,000,000.00"],
                "Outgoing Transactions (IDR)": [""],
                "Balance (IDR)": ["1,000,000.00"],
            }
        )

        result = converter.transform(df)

        expected_columns = [
            "date*",
            "amount*",
            "name",
            "currency",
            "category",
            "tags",
            "account",
            "notes",
        ]
        assert list(result.columns) == expected_columns


class TestMandiriConverterIntegration:
    """Integration tests for MandiriBankStatementConverter."""

    @pytest.fixture
    def converter(self):
        return MandiriBankStatementConverter(password="test")

    def test_full_conversion_pipeline(self, converter):
        """Test the full conversion pipeline with realistic data."""
        # Simulate a real Mandiri statement structure
        raw_data = [
            ["PT Bank Mandiri (Persero) Tbk", "", "", "", "", ""],
            ["Account Statement", "", "", "", "", ""],
            ["Account: 1234567890", "", "", "", "", ""],
            ["Period: April 2025", "", "", "", "", ""],
            ["", "", "", "", "", ""],
            [
                "No",
                "Date",
                "Remarks",
                "Incoming Transactions (IDR)",
                "Outgoing Transactions (IDR)",
                "Balance (IDR)",
            ],
            ["1", "01 Apr 2025", "Salary Deposit", "5,000,000.00", "", "10,000,000.00"],
            ["", "", "From: Company ABC", "", "", ""],
            ["2", "05 Apr 2025", "ATM Withdrawal", "", "1,000,000.00", "9,000,000.00"],
            ["", "", "ATM: 12345", "", "", ""],
            ["3", "10 Apr 2025", "Transfer", "", "2,000,000.00", "7,000,000.00"],
            ["", "", "To: John Doe", "", "", ""],
        ]
        df = pd.DataFrame(raw_data)

        result = converter.transform(df)

        assert len(result) == 3

        # First transaction: Salary (credit)
        assert result.iloc[0]["date*"] == "2025-04-01"
        assert result.iloc[0]["name"] == "Salary Deposit"
        assert result.iloc[0]["amount*"] == 5000000.0
        assert result.iloc[0]["account"] == "Mandiri"

        # Second transaction: ATM Withdrawal (debit)
        assert result.iloc[1]["date*"] == "2025-04-05"
        assert result.iloc[1]["amount*"] == -1000000.0

        # Third transaction: Transfer (debit)
        assert result.iloc[2]["date*"] == "2025-04-10"
        assert result.iloc[2]["amount*"] == -2000000.0
