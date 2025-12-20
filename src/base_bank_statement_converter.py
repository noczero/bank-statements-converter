from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import pandas as pd
import msoffcrypto
import io
import os
import glob


class BaseBankStatementConverter(ABC):
    """
    Base class for bank statement converters.
    Subclasses must implement get_column_mapping() and get_source_folder().
    """

    def __init__(self, password: Optional[str] = None):
        """
        Initialize the converter.

        Args:
            password: Optional password for encrypted Excel files.
        """
        self.password = password
        self.results_folder = "results"

    @abstractmethod
    def get_column_mapping(self) -> Dict[str, str]:
        """
        Return a dictionary mapping source columns to target columns.
        Example: {'Tanggal': 'date*', 'Keterangan': 'name'}
        """
        pass

    @abstractmethod
    def get_source_folder(self) -> str:
        """
        Return the path to the folder containing source Excel files.
        Example: 'bank-statements/mandiri'
        """
        pass

    def get_target_columns(self) -> List[str]:
        """
        Return the target CSV columns in order.
        """
        return [
            "date*",
            "amount*",
            "name",
            "currency",
            "category",
            "tags",
            "account",
            "notes",
        ]

    def get_output_filename(self, input_file: str) -> str:
        """
        Generate output filename from input filename.
        """
        basename = os.path.basename(input_file)
        name_without_ext = os.path.splitext(basename)[0]
        return f"{name_without_ext}_converted.csv"

    def output_exists(self, input_file: str) -> bool:
        """
        Check if the output file already exists in results folder.
        """
        output_name = self.get_output_filename(input_file)
        output_path = os.path.join(self.results_folder, output_name)
        return os.path.exists(output_path)

    def load_excel(self, file_path: str) -> pd.DataFrame:
        """
        Load an Excel file, handling password protection if necessary.
        """
        if self.password:
            try:
                decrypted_workbook = io.BytesIO()
                with open(file_path, "rb") as file:
                    office_file = msoffcrypto.OfficeFile(file)
                    office_file.load_key(password=self.password)
                    office_file.decrypt(decrypted_workbook)
                decrypted_workbook.seek(0)
                return pd.read_excel(decrypted_workbook)
            except Exception as e:
                raise RuntimeError(f"Error decrypting file {file_path}: {e}")
        else:
            return pd.read_excel(file_path)

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Transform the dataframe to match the target schema.
        Subclasses can override for custom transformations.
        """
        mapping = self.get_column_mapping()
        target_cols = self.get_target_columns()

        # Rename columns based on mapping
        df = df.rename(columns=mapping)

        # Create output dataframe with target columns
        output_df = pd.DataFrame(columns=target_cols)
        for col in target_cols:
            if col in df.columns:
                output_df[col] = df[col]
            else:
                output_df[col] = ""

        return output_df

    def convert_file(self, input_file: str) -> Optional[str]:
        """
        Convert a single file.

        Returns:
            Path to output file if successful, None if skipped.
        """
        if self.output_exists(input_file):
            print(f"Skipping {input_file} - output already exists")
            return None

        print(f"Converting {input_file}...")
        df = self.load_excel(input_file)
        result_df = self.transform(df)

        os.makedirs(self.results_folder, exist_ok=True)
        output_name = self.get_output_filename(input_file)
        output_path = os.path.join(self.results_folder, output_name)
        result_df.to_csv(output_path, index=False)
        print(f"  -> Saved to {output_path}")
        return output_path

    def convert_all(self) -> List[str]:
        """
        Find all xlsx files in source folder and convert them.

        Returns:
            List of paths to converted files.
        """
        source_folder = self.get_source_folder()
        pattern = os.path.join(source_folder, "*.xlsx")
        files = glob.glob(pattern)

        if not files:
            print(f"No xlsx files found in {source_folder}")
            return []

        converted = []
        for file_path in files:
            result = self.convert_file(file_path)
            if result:
                converted.append(result)

        print(
            f"\nConverted {len(converted)} file(s), skipped {len(files) - len(converted)} file(s)"
        )
        return converted
