# Bank Statement Converter

A Python tool for converting bank statements from various formats (Excel) into a standardized CSV format for financial tracking applications.

## Features

- 🔐 **Password-protected Excel support** - Handles encrypted bank statement files
- 🏦 **Mandiri Bank support** - Converts Mandiri bank statements to CSV
- 📊 **Standardized output** - Exports to a consistent format for easy import
- 🔄 **Batch processing** - Converts all files in a folder at once
- ⏭️ **Skip existing** - Automatically skips already-converted files
- 💸 **Sure Finance import** - Imports converted statements into Sure
  (finance.zeroinside.id) via its native CSV import API, with dedup + auto-categorization

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
├── sure_import_statement.py    # Convert + import into Sure Finance (CLI)
├── src/
│   ├── __init__.py
│   ├── base_bank_statement_converter.py    # Abstract base class
│   ├── mandiri_bank_statement_converter.py # Mandiri implementation
│   └── sure_importer.py                    # Sure Finance API client (import/dedup/categorize)
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

## Sure Finance Import

Convert a Mandiri statement and push it straight into Sure (the user's self-hosted
ledger at finance.zeroinside.id) with one command. The pipeline:

1. **Convert** the Excel statement to CSV (`MandiriBankStatementConverter`)
2. **Dedup** against existing Sure transactions in the statement's date range
   (date + amount + name) — re-running a monthly statement is a no-op
3. **Import** via Sure's native CSV import API (`POST /imports`, `TransactionImport`,
   `publish=true`) — the same pipeline the app's UI uses, so rows are validated and
   created by a background job
4. **Auto-categorize** (optional) using a regex taxonomy on the transaction name
   (BPJS→Insurance, Shopee/Tokopedia→Shopping, bank fees→Fees, salary→Salary, ...)

```bash
# Preview only — converts and shows what would be imported, no writes
python sure_import_statement.py bank-statements/mandiri/statement.xlsx --dry-run

# Full import + auto-categorize
python sure_import_statement.py bank-statements/mandiri/statement.xlsx --categorize

# Create the import without publishing (review in the app first, publish there)
python sure_import_statement.py statement.xlsx --no-publish
```

Environment (see `.env.example`):

| Variable | Purpose |
|---|---|
| `MANDIRI_BANK_STATEMENT_PASSWORD` | Password for the encrypted Mandiri Excel |
| `SURE_API_KEY` | Sure REST API key (`X-Api-Key` header) |
| `SURE_BASE_URL` | Default `https://finance.zeroinside.id/api/v1` |

`SURE_API_KEY` falls back to `~/.hermes/.env` if not set (the Hermes-managed
secrets file), so the agent can run imports without extra setup.

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
