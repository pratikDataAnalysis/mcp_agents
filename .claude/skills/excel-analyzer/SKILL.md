---
name: excel-analyzer
description: Read, analyze, and extract insights from Excel spreadsheets (.xlsx, .xls files). Performs data analysis, searches content, generates summaries, and extracts specific information. Use when user mentions Excel files, spreadsheets, data analysis, or asks to read/analyze tabular data.
---

# Excel Analyzer

A comprehensive skill for reading and analyzing Excel spreadsheets with advanced data analysis capabilities.

## Quick Start

### Read an Excel File
```python
import pandas as pd

# Read all sheets
xl_file = pd.ExcelFile('report.xlsx')
print(f"Available sheets: {xl_file.sheet_names}")

# Read specific sheet
df = pd.read_excel('report.xlsx', sheet_name='Sales')
print(df.head())
```

### Get File Summary
```python
!`python scripts/read_excel.py report.xlsx --summary`
```

## Core Capabilities

### 1. Read Excel Files

**Read entire file:**
```python
import pandas as pd

# Read all sheets into dictionary
all_data = pd.read_excel('file.xlsx', sheet_name=None)

for sheet_name, df in all_data.items():
    print(f"\n=== {sheet_name} ===")
    print(f"Rows: {len(df)}, Columns: {len(df.columns)}")
    print(f"Columns: {list(df.columns)}")
```

**Read specific sheet:**
```python
df = pd.read_excel('file.xlsx', sheet_name='Q1 Sales')
```

**Read with options:**
```python
df = pd.read_excel(
    'file.xlsx',
    sheet_name='Data',
    skiprows=2,        # Skip header rows
    usecols='A:E',     # Only columns A through E
    nrows=100          # Limit to 100 rows
)
```

### 2. Analyze Data

**Basic statistics:**
```python
# Get summary statistics
summary = df.describe()
print(summary)

# Get data types
print(df.dtypes)

# Check for missing values
print(df.isnull().sum())
```

**Calculate totals and averages:**
```python
# Sum numeric columns
totals = df.select_dtypes(include='number').sum()

# Calculate averages
averages = df.select_dtypes(include='number').mean()

# Group by category
grouped = df.groupby('Category').agg({
    'Sales': 'sum',
    'Quantity': 'mean'
})
```

**Find specific data:**
```python
# Filter rows
high_sales = df[df['Sales'] > 10000]

# Sort data
top_10 = df.nlargest(10, 'Revenue')

# Search for text
contains_word = df[df['Description'].str.contains('urgent', case=False, na=False)]
```

### 3. Search Across Sheets

**Search all sheets for text:**
```python
!`python scripts/search_excel.py file.xlsx "search term"`
```

**Manual search:**
```python
import openpyxl

wb = openpyxl.load_workbook('file.xlsx')
results = []

for sheet_name in wb.sheetnames:
    sheet = wb[sheet_name]
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value and 'search_term' in str(cell.value).lower():
                results.append({
                    'sheet': sheet_name,
                    'cell': cell.coordinate,
                    'value': cell.value
                })

print(f"Found {len(results)} matches")
```

### 4. Extract Specific Data

**Extract column:**
```python
# Get all values from a column
names = df['Name'].tolist()
unique_names = df['Name'].unique()

# Get specific columns
subset = df[['Name', 'Email', 'Sales']]
```

**Extract by criteria:**
```python
# Active customers only
active = df[df['Status'] == 'Active']

# Date range
from datetime import datetime
recent = df[df['Date'] > '2024-01-01']

# Multiple conditions
filtered = df[(df['Sales'] > 1000) & (df['Region'] == 'North')]
```

### 5. Compare Multiple Sheets

**Compare data across sheets:**
```python
sheet1 = pd.read_excel('file.xlsx', sheet_name='January')
sheet2 = pd.read_excel('file.xlsx', sheet_name='February')

# Compare totals
jan_total = sheet1['Sales'].sum()
feb_total = sheet2['Sales'].sum()
growth = ((feb_total - jan_total) / jan_total) * 100

print(f"January: ${jan_total:,.2f}")
print(f"February: ${feb_total:,.2f}")
print(f"Growth: {growth:.1f}%")
```

## Advanced Features

### Working with Formulas

```python
import openpyxl

# Load with formulas preserved
wb = openpyxl.load_workbook('file.xlsx', data_only=False)
sheet = wb['Sheet1']

# Read cell formula
formula = sheet['A1'].value
print(f"Formula: {formula}")

# Load with calculated values
wb_values = openpyxl.load_workbook('file.xlsx', data_only=True)
calculated_value = wb_values['Sheet1']['A1'].value
```

### Extract Cell Formatting

```python
cell = sheet['A1']

# Font information
print(f"Font: {cell.font.name}, Size: {cell.font.size}")
print(f"Bold: {cell.font.bold}, Italic: {cell.font.italic}")

# Cell fill color
print(f"Background: {cell.fill.start_color.rgb}")

# Number format
print(f"Format: {cell.number_format}")
```

### Pivot Table Analysis

```python
# Create pivot table from data
pivot = pd.pivot_table(
    df,
    values='Sales',
    index=['Region', 'Product'],
    aggfunc='sum'
)
print(pivot)
```

### Data Validation

```python
# Check for duplicates
duplicates = df[df.duplicated()]
print(f"Found {len(duplicates)} duplicate rows")

# Validate data types
def validate_email(email):
    import re
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return bool(re.match(pattern, str(email)))

invalid_emails = df[~df['Email'].apply(validate_email)]
```

## Output Formats

### Convert to JSON
```python
# Convert to JSON
json_data = df.to_json(orient='records', indent=2)
print(json_data)
```

### Convert to CSV
```python
df.to_csv('output.csv', index=False)
```

### Convert to Dictionary
```python
# Records format (list of dicts)
records = df.to_dict('records')

# Columns format (dict of lists)
columns = df.to_dict('list')
```

### Generate Markdown Table
```python
markdown = df.to_markdown(index=False)
print(markdown)
```

## Using Helper Scripts

The skill includes ready-to-use scripts in the `scripts/` directory:

### Read and Summarize
```bash
python scripts/read_excel.py file.xlsx --summary
```

### Analyze Specific Sheet
```bash
python scripts/analyze_data.py file.xlsx --sheet "Sales Data" --operation totals
```

### Search Content
```bash
python scripts/search_excel.py file.xlsx "customer name"
```

## Error Handling

Always handle common errors gracefully:

```python
import os

def safe_read_excel(file_path, sheet_name=None):
    """Safely read Excel file with proper error handling."""

    # Check file exists
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}

    # Check file extension
    if not file_path.lower().endswith(('.xlsx', '.xls')):
        return {"error": "File must be .xlsx or .xls format"}

    try:
        # Try reading file
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        return {"success": True, "data": df}

    except PermissionError:
        return {"error": "File is open in another program. Please close it."}

    except Exception as e:
        return {"error": f"Error reading file: {str(e)}"}
```

## Best Practices

1. **Always validate file paths** before attempting to read
2. **Limit data returned** to avoid token overflow (use `.head()`, `.tail()`, or sample)
3. **Specify dtypes** when reading to ensure correct data types
4. **Handle missing values** appropriately
5. **Close workbooks** when using openpyxl
6. **Use read_only mode** for large files: `openpyxl.load_workbook(file, read_only=True)`

## Common Workflows

### Workflow 1: Sales Report Analysis

```python
# 1. Read the file
df = pd.read_excel('sales_report.xlsx')

# 2. Calculate key metrics
total_sales = df['Sales'].sum()
avg_sale = df['Sales'].mean()
top_product = df.groupby('Product')['Sales'].sum().idxmax()

# 3. Generate summary
print(f"""
Sales Report Summary:
- Total Sales: ${total_sales:,.2f}
- Average Sale: ${avg_sale:,.2f}
- Top Product: {top_product}
- Total Transactions: {len(df)}
""")
```

### Workflow 2: Data Quality Check

```python
# 1. Read data
df = pd.read_excel('customer_data.xlsx')

# 2. Check quality
missing_data = df.isnull().sum()
duplicates = df.duplicated().sum()

# 3. Report issues
print("Data Quality Report:")
print(f"Missing values:\n{missing_data[missing_data > 0]}")
print(f"Duplicate rows: {duplicates}")
```

### Workflow 3: Multi-Sheet Comparison

```python
# 1. Read multiple sheets
q1 = pd.read_excel('quarterly.xlsx', sheet_name='Q1')
q2 = pd.read_excel('quarterly.xlsx', sheet_name='Q2')

# 2. Compare metrics
q1_revenue = q1['Revenue'].sum()
q2_revenue = q2['Revenue'].sum()
growth = ((q2_revenue - q1_revenue) / q1_revenue) * 100

# 3. Generate comparison
print(f"Q1 Revenue: ${q1_revenue:,.2f}")
print(f"Q2 Revenue: ${q2_revenue:,.2f}")
print(f"Quarter-over-Quarter Growth: {growth:.1f}%")
```

## Tips for Large Files

```python
# Read in chunks
chunk_size = 1000
chunks = []

for chunk in pd.read_excel('large_file.xlsx', chunksize=chunk_size):
    # Process each chunk
    processed = chunk[chunk['Status'] == 'Active']
    chunks.append(processed)

# Combine results
result = pd.concat(chunks, ignore_index=True)
```

## Additional Resources

- **Examples**: See [EXAMPLES.md](EXAMPLES.md) for detailed usage examples
- **Reference**: See [REFERENCE.md](REFERENCE.md) for complete API reference
- **Scripts**: Ready-to-use Python scripts in `scripts/` directory
