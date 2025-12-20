from src.mandiri_bank_statement_converter import MandiriBankStatementConverter


def main():
    """
    Main entry point for the bank statement converter.
    """
    print("Bank Statement Converter")
    print("=" * 40)

    # Run Mandiri converter
    print("\n[Mandiri Bank Statements]")
    converter = MandiriBankStatementConverter()
    converter.convert_all()


if __name__ == "__main__":
    main()
