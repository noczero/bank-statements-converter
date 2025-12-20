# Bank Statement Converter

A Python tool for converting bank statements from various formats (Excel) into a standardized CSV format for financial tracking applications.

## Features

- 🔐 **Password-protected Excel support** - Handles encrypted bank statement files
- 🏦 **Mandiri Bank support** - Converts Mandiri bank statements to CSV
- 📊 **Standardized output** - Exports to a consistent format for easy import
- 🔄 **Batch processing** - Converts all files in a folder at once
- ⏭️ **Skip existing** - Automatically skips already-converted files

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/noczero/bank-statement-converter.git
   cd bank-statement-converter
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   uv venv
   source .venv/bin/activate
   uv pip install -e .
   ```

3. Set up environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your bank statement passwords
   ```

## Configuration

Create a `.env` file with the following variables:

```env
MANDIRI_BANK_STATEMENT_PASSWORD=your_password_here
```

## Usage

### Basic Usage

1. Place your bank statement Excel files in the appropriate folder:
   - Mandiri: `bank-statements/mandiri/`

2. Run the converter:
   ```bash
   python main.py
   ```

3. Find your converted CSV files in the `results/` folder.

### Programmatic Usage

```python
from src.mandiri_bank_statement_converter import MandiriBankStatementConverter

# Initialize converter (password loaded from .env)
converter = MandiriBankStatementConverter()

# Convert all files in the source folder
converted_files = converter.convert_all()

# Or convert a single file
output_path = converter.convert_file("bank-statements/mandiri/statement.xlsx")
```

## Output Format

The converter outputs CSV files with the following columns:

| Column | Required | Description |
|--------|----------|-------------|
| `date*` | ✅ | Transaction date (YYYY-MM-DD) |
| `amount*` | ✅ | Transaction amount (positive for credit, negative for debit) |
| `name` | | Transaction description/payee |
| `currency` | | Currency code (e.g., IDR) |
| `category` | | Transaction category |
| `tags` | | Tags separated by `\|` |
| `account` | | Account name |
| `notes` | | Additional notes |

### Example Output

```csv
date*,amount*,name,currency,category,tags,account,notes
2025-04-01,5000000.0,Salary Deposit,IDR,,,Mandiri,
2025-04-05,-1000000.0,ATM Withdrawal,IDR,,,Mandiri,
```

## Project Structure

```
bank-statement-converter/
├── main.py                     # Entry point
├── src/
│   ├── __init__.py
│   ├── base_bank_statement_converter.py    # Abstract base class
│   └── mandiri_bank_statement_converter.py # Mandiri implementation
├── tests/
│   ├── test_base_bank_statement_converter.py
│   └── test_mandiri_bank_statement_converter.py
├── bank-statements/
│   └── mandiri/               # Place Mandiri Excel files here
├── results/                   # Converted CSV files output here
├── templates/
│   └── transaction_sample.csv # Sample output format
├── pyproject.toml
├── pytest.ini
└── .env.example
```

## Development

### Install dev dependencies

```bash
uv pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=src --cov-report=term-missing
```

### Adding a New Bank

1. Create a new converter class in `src/`:
   ```python
   from src.base_bank_statement_converter import BaseBankStatementConverter

   class NewBankConverter(BaseBankStatementConverter):
       def get_source_folder(self) -> str:
           return "bank-statements/newbank"

       def get_column_mapping(self) -> dict:
           return {"source_col": "target_col"}

       # Override transform() for custom logic
   ```

2. Add the converter to `main.py`
3. Create a folder `bank-statements/newbank/`
4. Add tests in `tests/`

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
