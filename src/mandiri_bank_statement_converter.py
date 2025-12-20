from typing import Dict, Optional
import os
import pandas as pd
from dotenv import load_dotenv
from .base_bank_statement_converter import BaseBankStatementConverter


class MandiriBankStatementConverter(BaseBankStatementConverter):
    """
    Converter for Mandiri bank statements.
    Reads password from MANDIRI_BANK_STATEMENT_PASSWORD environment variable.
    """

    # Known header keywords to identify the table start
    HEADER_KEYWORDS = [
        "No",
        "Date",
        "Remarks",
        "Incoming Transactions (IDR)",
        "Outgoing Transactions (IDR)",
        "Balance (IDR)",
    ]

    def __init__(self, password: Optional[str] = None):
        """
        Initialize Mandiri converter.
        Password is loaded from .env if not provided.
        """
        load_dotenv()

        if password is None:
            password = os.getenv("MANDIRI_BANK_STATEMENT_PASSWORD")

        super().__init__(password=password)

    def get_source_folder(self) -> str:
        return "bank-statements/mandiri"

    def get_column_mapping(self) -> Dict[str, str]:
        """
        Mapping from INPUT column names to OUTPUT column names.
        Format: {"input_column": "output_column"}
        """
        return {}

    def find_header_row(self, df: pd.DataFrame) -> int:
        """
        Find the row index that contains the actual table header.
        Searches for rows containing known header keywords.

        Returns:
            Row index of the header, or 0 if not found.
        """
        for idx, row in df.iterrows():
            row_values = [str(val).strip() for val in row.values]
            matches = sum(
                1 for keyword in self.HEADER_KEYWORDS if keyword in row_values
            )
            if matches >= 2:  # At least 2 header keywords found
                return idx
        return 0

    def _clean_amount(self, value) -> float:
        """Clean and convert amount value to float."""
        if pd.isna(value) or value == "" or value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        # Handle string with formatting (commas, currency symbols)
        val_str = str(value).replace(",", "").replace(".", "").replace("Rp", "").strip()
        try:
            return float(val_str) / 100
        except ValueError:
            return 0.0

    def _get_value(self, row: pd.Series, column_name: str, default=""):
        """Safely get a value from a row by column name."""
        if column_name in row.index:
            val = row[column_name]
            if pd.isna(val):
                return default
            return val
        return default

    def _parse_date(self, date_str: str) -> str:
        """
        Convert date string like '02 Apr 2025' to 'YYYY-MM-DD' format.
        """
        if not date_str or pd.isna(date_str):
            return ""
        try:
            from datetime import datetime

            dt = datetime.strptime(str(date_str).strip(), "%d %b %Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return str(date_str)

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Transform Mandiri bank statement to target schema.
        Manually maps each input column to output columns.
        """
        # Find the header row
        header_row_idx = self.find_header_row(df)

        if header_row_idx > 0:
            # Set the header row as column names
            df.columns = df.iloc[header_row_idx]
            # Skip rows before and including the header
            df = df.iloc[header_row_idx + 1 :].reset_index(drop=True)
            print(f"  Found table header at row {header_row_idx + 2}")

        # Get original column names
        input_cols = list(df.columns)
        print(f"  Input columns: {input_cols}")

        # Build output rows manually
        # Each transaction spans 2 rows, only process the first row (even indices)
        target_cols = self.get_target_columns()
        output_rows = []

        for idx, row in df.iterrows():
            # Skip every second row (only process first row of each transaction)
            if idx % 2 != 0 or self._get_value(row, "Date") == "":
                continue

            output_row = {}

            output_row["date*"] = self._parse_date(self._get_value(row, "Date"))
            output_row["name"] = self._get_value(row, "Remarks")
            debit = self._clean_amount(
                self._get_value(row, "Outgoing Transactions (IDR)", 0)
            )
            credit = self._clean_amount(
                self._get_value(row, "Incoming Transactions (IDR)", 0)
            )
            output_row["amount*"] = credit - debit

            # Default values
            output_row["currency"] = "IDR"
            output_row["category"] = ""
            output_row["tags"] = ""
            output_row["account"] = "Mandiri"
            output_row["notes"] = ""

            output_rows.append(output_row)

        output_df = pd.DataFrame(output_rows, columns=target_cols)
        return output_df
