#!/usr/bin/env python3
"""
Analyze Excel data with various operations.

Usage:
    python analyze_data.py file.xlsx --sheet "Sales" --operation totals
    python analyze_data.py file.xlsx --sheet "Sales" --operation averages
    python analyze_data.py file.xlsx --sheet "Sales" --operation summary
"""

import sys
import argparse
import pandas as pd
from pathlib import Path


def calculate_totals(df):
    """Calculate totals for numeric columns."""
    numeric_cols = df.select_dtypes(include=['number']).columns

    if len(numeric_cols) == 0:
        print("No numeric columns found.")
        return

    print("\n=== Column Totals ===")
    for col in numeric_cols:
        total = df[col].sum()
        print(f"{col}: {total:,.2f}")


def calculate_averages(df):
    """Calculate averages for numeric columns."""
    numeric_cols = df.select_dtypes(include=['number']).columns

    if len(numeric_cols) == 0:
        print("No numeric columns found.")
        return

    print("\n=== Column Averages ===")
    for col in numeric_cols:
        avg = df[col].mean()
        print(f"{col}: {avg:,.2f}")


def show_summary(df):
    """Show comprehensive summary statistics."""
    print("\n=== Data Summary ===")
    print(df.describe(include='all'))

    print("\n=== Data Types ===")
    print(df.dtypes)

    print("\n=== Missing Values ===")
    missing = df.isnull().sum()
    if missing.sum() > 0:
        print(missing[missing > 0])
    else:
        print("No missing values found.")

    print("\n=== Duplicate Rows ===")
    duplicates = df.duplicated().sum()
    print(f"Found {duplicates} duplicate rows")


def show_counts(df):
    """Show value counts for each column."""
    print("\n=== Value Counts ===")

    for col in df.columns:
        print(f"\n{col}:")
        print(f"  Total values: {df[col].count()}")
        print(f"  Unique values: {df[col].nunique()}")

        if df[col].nunique() < 20:  # Only show for columns with few unique values
            print(f"  Value distribution:")
            counts = df[col].value_counts().head(10)
            for value, count in counts.items():
                print(f"    {value}: {count}")


def show_correlations(df):
    """Show correlations between numeric columns."""
    numeric_cols = df.select_dtypes(include=['number']).columns

    if len(numeric_cols) < 2:
        print("Need at least 2 numeric columns for correlation analysis.")
        return

    print("\n=== Correlations ===")
    corr = df[numeric_cols].corr()
    print(corr)


def main():
    parser = argparse.ArgumentParser(description='Analyze Excel data')

    parser.add_argument('file', help='Path to Excel file')
    parser.add_argument('--sheet', required=True, help='Sheet name to analyze')
    parser.add_argument(
        '--operation',
        choices=['totals', 'averages', 'summary', 'counts', 'correlations'],
        default='summary',
        help='Analysis operation to perform'
    )

    args = parser.parse_args()

    # Validate file
    if not Path(args.file).exists():
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    try:
        # Read data
        df = pd.read_excel(args.file, sheet_name=args.sheet)

        print(f"\nAnalyzing: {args.file}")
        print(f"Sheet: {args.sheet}")
        print(f"Rows: {len(df)}, Columns: {len(df.columns)}")

        # Perform operation
        if args.operation == 'totals':
            calculate_totals(df)
        elif args.operation == 'averages':
            calculate_averages(df)
        elif args.operation == 'summary':
            show_summary(df)
        elif args.operation == 'counts':
            show_counts(df)
        elif args.operation == 'correlations':
            show_correlations(df)

    except ValueError as e:
        print(f"Error: Sheet '{args.sheet}' not found.", file=sys.stderr)
        print("Available sheets:", file=sys.stderr)
        xl_file = pd.ExcelFile(args.file)
        for sheet_name in xl_file.sheet_names:
            print(f"  - {sheet_name}", file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
