# Project Conventions

## Overview
Bank statement converter project for transforming bank statements from Excel to standardized CSV format.

## Tech Stack
- **Python**: 3.14+
- **Package Manager**: uv
- **Testing**: pytest with pytest-cov

## Code Structure

### Converters
All bank converters must:
1. Inherit from `BaseBankStatementConverter` in `src/base_bank_statement_converter.py`
2. Implement required abstract methods:
   - `get_source_folder()` - returns folder path for input files
   - `get_column_mapping()` - returns dict mapping source to target columns
3. Override `transform()` for custom transformation logic
4. Place in `src/` directory with naming: `{bank}_bank_statement_converter.py`

### File Organization
```
src/                    # Source code
tests/                  # Test files (test_*.py)
bank-statements/{bank}/ # Input Excel files per bank
results/                # Output CSV files
templates/              # Sample/template files
```

## Naming Conventions

### Files
- Converters: `{bank}_bank_statement_converter.py` (snake_case)
- Tests: `test_{module_name}.py`

### Classes
- Converters: `{Bank}BankStatementConverter` (PascalCase)
- Example: `MandiriBankStatementConverter`

### Methods
- Use snake_case: `get_source_folder`, `convert_file`
- Private methods prefix with underscore: `_clean_amount`, `_parse_date`

## Testing Conventions

### Test Structure
```python
class Test{ClassName}:
    @pytest.fixture
    def converter(self):
        return ConverterClass(password="test")

    def test_method_name(self, converter):
        # Arrange, Act, Assert
```

### Test Naming
- `test_{method}_{scenario}` - e.g., `test_parse_date_valid_format`
- Use parametrize for multiple inputs

### Running Tests
```bash
# Activate venv first
source .venv/bin/activate

# Run tests
pytest -v

# With coverage
pytest --cov=src --cov-report=term-missing
```

## Environment Variables
- Store in `.env` (not committed)
- Document in `.env.example`
- Bank passwords: `{BANK}_BANK_STATEMENT_PASSWORD`

## Output Format
All converters must output CSV with these columns:
- `date*` (YYYY-MM-DD, required)
- `amount*` (float, required, positive=credit, negative=debit)
- `name`, `currency`, `category`, `tags`, `account`, `notes`

## Commands

// turbo-all
```bash
# Install dependencies
uv pip install -e ".[dev]"

# Run converter
python main.py

# Run tests
pytest -v

# Run with coverage
pytest --cov=src --cov-report=term-missing
```
