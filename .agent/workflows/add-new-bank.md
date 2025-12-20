---
description: How to add a new bank converter
---

# Adding a New Bank Converter

## Steps

1. Create converter file in `src/`:
   ```bash
   touch src/{bank}_bank_statement_converter.py
   ```

2. Implement the converter class:
   ```python
   from typing import Dict, Optional
   import os
   import pandas as pd
   from dotenv import load_dotenv
   from .base_bank_statement_converter import BaseBankStatementConverter

   class {Bank}BankStatementConverter(BaseBankStatementConverter):
       def __init__(self, password: Optional[str] = None):
           load_dotenv()
           if password is None:
               password = os.getenv("{BANK}_BANK_STATEMENT_PASSWORD")
           super().__init__(password=password)

       def get_source_folder(self) -> str:
           return "bank-statements/{bank}"

       def get_column_mapping(self) -> Dict[str, str]:
           return {}  # Or mapping dict

       def transform(self, df: pd.DataFrame) -> pd.DataFrame:
           # Custom transformation logic
           pass
   ```

3. Create input folder:
   ```bash
   mkdir -p bank-statements/{bank}
   ```

4. Add environment variable to `.env.example`:
   ```
   {BANK}_BANK_STATEMENT_PASSWORD=your_password_here
   ```

5. Register in `main.py`:
   ```python
   from src.{bank}_bank_statement_converter import {Bank}BankStatementConverter

   # In main():
   print("\n[{Bank} Bank Statements]")
   converter = {Bank}BankStatementConverter()
   converter.convert_all()
   ```

// turbo
6. Create tests in `tests/test_{bank}_bank_statement_converter.py`

// turbo
7. Run tests:
   ```bash
   pytest tests/test_{bank}_bank_statement_converter.py -v
   ```
