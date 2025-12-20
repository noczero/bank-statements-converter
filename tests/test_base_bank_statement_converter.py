"""Tests for BaseBankStatementConverter class."""

import os
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
import tempfile
import shutil

from src.base_bank_statement_converter import BaseBankStatementConverter


class ConcreteConverter(BaseBankStatementConverter):
    """Concrete implementation for testing the abstract base class."""

    def get_column_mapping(self):
        return {
            "source_date": "date*",
            "source_amount": "amount*",
            "source_name": "name",
        }

    def get_source_folder(self):
        return "test-statements"


class TestBaseBankStatementConverter:
    """Test suite for BaseBankStatementConverter."""

    @pytest.fixture
    def converter(self):
        """Create a concrete converter instance for testing."""
        return ConcreteConverter(password="test_password")

    @pytest.fixture
    def converter_no_password(self):
        """Create a converter without password."""
        return ConcreteConverter()

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        temp_path = tempfile.mkdtemp()
        yield temp_path
        shutil.rmtree(temp_path)

    def test_init_with_password(self, converter):
        """Test initialization with password."""
        assert converter.password == "test_password"
        assert converter.results_folder == "results"

    def test_init_without_password(self, converter_no_password):
        """Test initialization without password."""
        assert converter_no_password.password is None

    def test_get_target_columns(self, converter):
        """Test that target columns are returned correctly."""
        expected = [
            "date*",
            "amount*",
            "name",
            "currency",
            "category",
            "tags",
            "account",
            "notes",
        ]
        assert converter.get_target_columns() == expected

    def test_get_output_filename(self, converter):
        """Test output filename generation."""
        assert (
            converter.get_output_filename("statement.xlsx") == "statement_converted.csv"
        )
        assert (
            converter.get_output_filename("/path/to/file.xlsx") == "file_converted.csv"
        )
        assert (
            converter.get_output_filename("multi.part.name.xlsx")
            == "multi.part.name_converted.csv"
        )

    def test_output_exists_true(self, converter, temp_dir):
        """Test output_exists returns True when file exists."""
        converter.results_folder = temp_dir
        # Create the output file
        output_path = os.path.join(temp_dir, "test_converted.csv")
        with open(output_path, "w") as f:
            f.write("test")

        assert converter.output_exists("test.xlsx") is True

    def test_output_exists_false(self, converter, temp_dir):
        """Test output_exists returns False when file doesn't exist."""
        converter.results_folder = temp_dir
        assert converter.output_exists("nonexistent.xlsx") is False

    def test_transform_with_mapping(self, converter):
        """Test transform applies column mapping correctly."""
        input_df = pd.DataFrame(
            {
                "source_date": ["2024-01-01", "2024-01-02"],
                "source_amount": [100.0, 200.0],
                "source_name": ["Transaction 1", "Transaction 2"],
            }
        )

        result = converter.transform(input_df)

        assert list(result.columns) == converter.get_target_columns()
        assert result["date*"].tolist() == ["2024-01-01", "2024-01-02"]
        assert result["amount*"].tolist() == [100.0, 200.0]
        assert result["name"].tolist() == ["Transaction 1", "Transaction 2"]
        # Check that unmapped columns have empty values
        assert result["currency"].tolist() == ["", ""]

    def test_transform_with_missing_columns(self, converter):
        """Test transform handles missing source columns gracefully."""
        input_df = pd.DataFrame(
            {
                "source_date": ["2024-01-01"],
            }
        )

        result = converter.transform(input_df)

        assert result["date*"].tolist() == ["2024-01-01"]
        assert result["amount*"].tolist() == [""]
        assert result["name"].tolist() == [""]

    @patch("src.base_bank_statement_converter.pd.read_excel")
    def test_load_excel_without_password(self, mock_read_excel, converter_no_password):
        """Test loading Excel file without password."""
        mock_df = pd.DataFrame({"col": [1, 2, 3]})
        mock_read_excel.return_value = mock_df

        result = converter_no_password.load_excel("test.xlsx")

        mock_read_excel.assert_called_once_with("test.xlsx")
        pd.testing.assert_frame_equal(result, mock_df)

    @patch("src.base_bank_statement_converter.msoffcrypto.OfficeFile")
    def test_load_excel_with_password(self, mock_office_file, converter):
        """Test loading password-protected Excel file."""
        mock_file_instance = MagicMock()
        mock_office_file.return_value = mock_file_instance

        with patch("builtins.open", MagicMock()):
            with patch("src.base_bank_statement_converter.pd.read_excel") as mock_read:
                mock_df = pd.DataFrame({"col": [1, 2, 3]})
                mock_read.return_value = mock_df

                result = converter.load_excel("test.xlsx")

                mock_file_instance.load_key.assert_called_once_with(
                    password="test_password"
                )
                mock_file_instance.decrypt.assert_called_once()

    def test_convert_file_skip_existing(self, converter, temp_dir, capsys):
        """Test convert_file skips when output already exists."""
        converter.results_folder = temp_dir

        # Create existing output file
        output_path = os.path.join(temp_dir, "test_converted.csv")
        with open(output_path, "w") as f:
            f.write("existing")

        result = converter.convert_file("test.xlsx")

        assert result is None
        captured = capsys.readouterr()
        assert "Skipping" in captured.out

    @patch.object(ConcreteConverter, "load_excel")
    def test_convert_file_success(self, mock_load, converter, temp_dir):
        """Test successful file conversion."""
        converter.results_folder = temp_dir
        mock_load.return_value = pd.DataFrame(
            {
                "source_date": ["2024-01-01"],
                "source_amount": [100.0],
                "source_name": ["Test"],
            }
        )

        result = converter.convert_file("input.xlsx")

        assert result is not None
        assert result.endswith("input_converted.csv")
        assert os.path.exists(result)

    @patch("src.base_bank_statement_converter.glob.glob")
    def test_convert_all_no_files(self, mock_glob, converter, capsys):
        """Test convert_all with no files found."""
        mock_glob.return_value = []

        result = converter.convert_all()

        assert result == []
        captured = capsys.readouterr()
        assert "No xlsx files found" in captured.out

    @patch("src.base_bank_statement_converter.glob.glob")
    @patch.object(ConcreteConverter, "convert_file")
    def test_convert_all_with_files(self, mock_convert, mock_glob, converter):
        """Test convert_all processes all files."""
        mock_glob.return_value = ["file1.xlsx", "file2.xlsx", "file3.xlsx"]
        mock_convert.side_effect = ["output1.csv", None, "output3.csv"]

        result = converter.convert_all()

        assert len(result) == 2
        assert mock_convert.call_count == 3
