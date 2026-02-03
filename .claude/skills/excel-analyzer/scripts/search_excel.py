#!/usr/bin/env python3
"""
Search for text in Excel files across all sheets.

Usage:
    python search_excel.py file.xlsx "search term"
    python search_excel.py file.xlsx "urgent" --case-sensitive
"""

import sys
import argparse
import openpyxl
from pathlib import Path


def search_excel(file_path, search_term, case_sensitive=False):
    """
    Search for text in all sheets of an Excel file.

    Args:
        file_path: Path to Excel file
        search_term: Text to search for
        case_sensitive: Whether search should be case-sensitive
    """
    wb = openpyxl.load_workbook(file_path, read_only=True)
    results = []

    print(f"\nSearching for '{search_term}' in {Path(file_path).name}...")
    print(f"Case sensitive: {case_sensitive}\n")

    for sheet_name in wb.sheetnames:
        sheet = wb[sheet_name]
        sheet_matches = 0

        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue

                cell_value = str(cell.value)
                search_value = search_term

                if not case_sensitive:
                    cell_value = cell_value.lower()
                    search_value = search_value.lower()

                if search_value in cell_value:
                    results.append({
                        'sheet': sheet_name,
                        'cell': cell.coordinate,
                        'row': cell.row,
                        'column': cell.column,
                        'value': str(cell.value)
                    })
                    sheet_matches += 1

        if sheet_matches > 0:
            print(f"Sheet '{sheet_name}': {sheet_matches} matches")

    wb.close()

    return results


def display_results(results, max_results=50):
    """Display search results in a readable format."""

    if len(results) == 0:
        print("\nNo matches found.")
        return

    print(f"\n{'='*80}")
    print(f"Found {len(results)} matches")
    print(f"{'='*80}")

    # Group by sheet
    by_sheet = {}
    for result in results:
        sheet = result['sheet']
        if sheet not in by_sheet:
            by_sheet[sheet] = []
        by_sheet[sheet].append(result)

    # Display results grouped by sheet
    shown = 0
    for sheet_name, matches in by_sheet.items():
        print(f"\n--- Sheet: {sheet_name} ({len(matches)} matches) ---")

        for match in matches[:min(10, len(matches))]:  # Show first 10 per sheet
            value_preview = match['value']
            if len(value_preview) > 60:
                value_preview = value_preview[:57] + "..."

            print(f"  {match['cell']}: {value_preview}")
            shown += 1

            if shown >= max_results:
                print(f"\n(Showing first {max_results} results)")
                return

        if len(matches) > 10:
            print(f"  ... and {len(matches) - 10} more matches in this sheet")


def main():
    parser = argparse.ArgumentParser(
        description='Search for text in Excel files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python search_excel.py report.xlsx "urgent"
  python search_excel.py data.xlsx "John Smith" --case-sensitive
  python search_excel.py sales.xlsx "error" --max-results 100
        '''
    )

    parser.add_argument('file', help='Path to Excel file')
    parser.add_argument('search_term', help='Text to search for')
    parser.add_argument(
        '--case-sensitive',
        action='store_true',
        help='Perform case-sensitive search'
    )
    parser.add_argument(
        '--max-results',
        type=int,
        default=50,
        help='Maximum number of results to display (default: 50)'
    )

    args = parser.parse_args()

    # Validate file
    if not Path(args.file).exists():
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    if not args.file.lower().endswith(('.xlsx', '.xls')):
        print(f"Error: File must be .xlsx or .xls format", file=sys.stderr)
        sys.exit(1)

    try:
        # Perform search
        results = search_excel(
            args.file,
            args.search_term,
            case_sensitive=args.case_sensitive
        )

        # Display results
        display_results(results, max_results=args.max_results)

    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
