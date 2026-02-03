#!/usr/bin/env python3
"""
Read and summarize Excel files.

Usage:
    python read_excel.py file.xlsx --summary
    python read_excel.py file.xlsx --sheet "Sheet1"
    python read_excel.py file.xlsx --list-sheets
"""

import sys
import argparse
import pandas as pd
from pathlib import Path


def list_sheets(file_path):
    """List all sheet names in the Excel file."""
    xl_file = pd.ExcelFile(file_path)
    print(f"Sheets in {file_path}:")
    for i, sheet_name in enumerate(xl_file.sheet_names, 1):
        print(f"  {i}. {sheet_name}")
    return xl_file.sheet_names


def read_sheet(file_path, sheet_name=None):
    """Read and display a specific sheet."""
    df = pd.read_excel(file_path, sheet_name=sheet_name)

    print(f"\n=== Sheet: {sheet_name or 'First Sheet'} ===")
    print(f"Rows: {len(df)}")
    print(f"Columns: {len(df.columns)}")
    print(f"Column names: {', '.join(df.columns)}")
    print(f"\nFirst 10 rows:")
    print(df.head(10).to_string())

    return df


def summarize_file(file_path):
    """Generate a comprehensive summary of the Excel file."""
    xl_file = pd.ExcelFile(file_path)

    print(f"\n{'='*60}")
    print(f"Excel File Summary: {Path(file_path).name}")
    print(f"{'='*60}")

    print(f"\nTotal Sheets: {len(xl_file.sheet_names)}")

    for sheet_name in xl_file.sheet_names:
        df = xl_file.parse(sheet_name)

        print(f"\n--- Sheet: {sheet_name} ---")
        print(f"  Rows: {len(df)}")
        print(f"  Columns: {len(df.columns)}")
        print(f"  Column names: {', '.join(df.columns)}")

        # Show data types
        print(f"  Data types:")
        for col, dtype in df.dtypes.items():
            print(f"    {col}: {dtype}")

        # Missing values
        missing = df.isnull().sum()
        if missing.sum() > 0:
            print(f"  Missing values:")
            for col, count in missing[missing > 0].items():
                print(f"    {col}: {count}")

        # Numeric column statistics
        numeric_cols = df.select_dtypes(include=['number']).columns
        if len(numeric_cols) > 0:
            print(f"  Numeric statistics:")
            for col in numeric_cols:
                print(f"    {col}:")
                print(f"      Min: {df[col].min()}")
                print(f"      Max: {df[col].max()}")
                print(f"      Mean: {df[col].mean():.2f}")
                print(f"      Sum: {df[col].sum():.2f}")

        # Sample data
        print(f"  Sample data (first 3 rows):")
        for idx, row in df.head(3).iterrows():
            print(f"    Row {idx + 1}: {row.to_dict()}")


def main():
    parser = argparse.ArgumentParser(
        description='Read and analyze Excel files',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('file', help='Path to Excel file')
    parser.add_argument('--summary', action='store_true', help='Show comprehensive summary')
    parser.add_argument('--sheet', help='Read specific sheet')
    parser.add_argument('--list-sheets', action='store_true', help='List all sheet names')

    args = parser.parse_args()

    # Check file exists
    if not Path(args.file).exists():
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.list_sheets:
            list_sheets(args.file)
        elif args.summary:
            summarize_file(args.file)
        elif args.sheet:
            read_sheet(args.file, args.sheet)
        else:
            # Default: show summary
            summarize_file(args.file)

    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
