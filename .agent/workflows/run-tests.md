---
description: How to run tests for this project
---

# Running Tests

// turbo-all

1. Activate virtual environment:
   ```bash
   source .venv/bin/activate
   ```

2. Run all tests:
   ```bash
   pytest -v
   ```

3. Run tests with coverage:
   ```bash
   pytest --cov=src --cov-report=term-missing
   ```

4. Run specific test file:
   ```bash
   pytest tests/test_mandiri_bank_statement_converter.py -v
   ```

5. Run specific test class:
   ```bash
   pytest tests/test_mandiri_bank_statement_converter.py::TestMandiriBankStatementConverter -v
   ```

6. Run specific test:
   ```bash
   pytest tests/test_mandiri_bank_statement_converter.py::TestMandiriBankStatementConverter::test_init_with_password -v
   ```
