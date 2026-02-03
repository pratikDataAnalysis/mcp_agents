# Excel Analyzer - API Reference

Complete reference for pandas and openpyxl functions used in Excel analysis.

---

## Pandas Excel Functions

### Reading Excel Files

#### `pd.read_excel()`
```python
pd.read_excel(
    io,                    # File path or file-like object
    sheet_name=0,          # Sheet to read (0=first, 'Name', None=all)
    header=0,              # Row number for column names
    names=None,            # List of column names to use
    index_col=None,        # Column to use as row labels
    usecols=None,          # Columns to parse ('A:E' or [0,1,2])
    dtype=None,            # Data types for columns
    skiprows=None,         # Rows to skip at start
    nrows=None,            # Number of rows to read
    na_values=None,        # Additional strings to recognize as NaN
    parse_dates=False,     # Parse date columns
)
```

**Examples:**
```python
# Read first sheet
df = pd.read_excel('file.xlsx')

# Read specific sheet
df = pd.read_excel('file.xlsx', sheet_name='Sheet2')

# Read all sheets
all_sheets = pd.read_excel('file.xlsx', sheet_name=None)

# Read with options
df = pd.read_excel(
    'file.xlsx',
    sheet_name='Data',
    skiprows=2,
    usecols='A:E',
    parse_dates=['Date']
)
```

#### `pd.ExcelFile()`
```python
xl_file = pd.ExcelFile('file.xlsx')
sheet_names = xl_file.sheet_names
df = xl_file.parse('Sheet1')
```

### Writing Excel Files

#### `df.to_excel()`
```python
df.to_excel(
    'output.xlsx',
    sheet_name='Sheet1',
    index=False,           # Don't write row numbers
    header=True,           # Write column names
    startrow=0,            # Starting row
    startcol=0,            # Starting column
    engine='openpyxl'      # Excel engine to use
)
```

### Data Analysis Functions

#### Descriptive Statistics
```python
df.describe()              # Summary statistics
df.info()                  # DataFrame info
df.shape                   # (rows, columns)
df.dtypes                  # Column data types
df.columns                 # Column names
df.head(n)                 # First n rows
df.tail(n)                 # Last n rows
df.sample(n)               # Random n rows
```

#### Aggregation
```python
df['column'].sum()         # Sum
df['column'].mean()        # Average
df['column'].median()      # Median
df['column'].min()         # Minimum
df['column'].max()         # Maximum
df['column'].std()         # Standard deviation
df['column'].count()       # Count non-null
df['column'].nunique()     # Count unique values
```

#### Grouping
```python
# Group by single column
df.groupby('Category')['Sales'].sum()

# Group by multiple columns
df.groupby(['Region', 'Product'])['Sales'].agg(['sum', 'mean', 'count'])

# Custom aggregation
df.groupby('Region').agg({
    'Sales': 'sum',
    'Quantity': 'mean',
    'Customer': 'count'
})
```

#### Filtering
```python
# Single condition
df[df['Sales'] > 1000]

# Multiple conditions
df[(df['Sales'] > 1000) & (df['Region'] == 'North')]

# String contains
df[df['Name'].str.contains('Smith', case=False)]

# isin() for multiple values
df[df['Status'].isin(['Active', 'Pending'])]
```

#### Sorting
```python
df.sort_values('Sales')                    # Ascending
df.sort_values('Sales', ascending=False)   # Descending
df.sort_values(['Region', 'Sales'])        # Multiple columns
df.nlargest(10, 'Sales')                   # Top 10
df.nsmallest(10, 'Sales')                  # Bottom 10
```

#### Missing Data
```python
df.isnull()                # Check for NaN
df.isnull().sum()          # Count NaN per column
df.dropna()                # Remove rows with NaN
df.fillna(0)               # Replace NaN with 0
df.fillna(method='ffill')  # Forward fill
```

#### Pivot Tables
```python
pd.pivot_table(
    df,
    values='Sales',
    index='Region',
    columns='Category',
    aggfunc='sum',
    margins=True
)
```

### Data Conversion

```python
df.to_dict('records')      # List of dicts
df.to_dict('list')         # Dict of lists
df.to_json(orient='records')
df.to_csv('output.csv', index=False)
df.to_markdown(index=False)
df.to_html('output.html')
```

---

## Openpyxl Functions

### Loading Workbooks

```python
import openpyxl

# Read only (faster for large files)
wb = openpyxl.load_workbook('file.xlsx', read_only=True)

# Read/Write mode
wb = openpyxl.load_workbook('file.xlsx')

# With formulas
wb = openpyxl.load_workbook('file.xlsx', data_only=False)

# With calculated values
wb = openpyxl.load_workbook('file.xlsx', data_only=True)
```

### Accessing Sheets

```python
# Get sheet names
sheet_names = wb.sheetnames

# Access sheet by name
sheet = wb['Sheet1']

# Access active sheet
sheet = wb.active

# Create new sheet
new_sheet = wb.create_sheet('NewSheet')
```

### Reading Cells

```python
# Single cell
value = sheet['A1'].value
value = sheet.cell(row=1, column=1).value

# Cell range
for row in sheet['A1':'C10']:
    for cell in row:
        print(cell.value)

# All rows
for row in sheet.iter_rows(min_row=1, max_row=10, values_only=True):
    print(row)

# All columns
for col in sheet.iter_cols(min_col=1, max_col=3, values_only=True):
    print(col)
```

### Cell Properties

```python
cell = sheet['A1']

# Font
font = cell.font
print(font.name, font.size, font.bold, font.italic, font.color)

# Fill (background)
fill = cell.fill
print(fill.start_color.rgb)

# Alignment
alignment = cell.alignment
print(alignment.horizontal, alignment.vertical)

# Number format
print(cell.number_format)

# Value type
print(cell.data_type)  # 'n'=number, 's'=string, 'f'=formula
```

### Working with Formulas

```python
# Set formula
sheet['A1'].value = '=SUM(B1:B10)'

# Read formula (data_only=False)
formula = sheet['A1'].value  # Returns '=SUM(B1:B10)'

# Read calculated value (data_only=True)
result = sheet['A1'].value   # Returns calculated number
```

### Writing Data

```python
# Write single cell
sheet['A1'] = 'Hello'
sheet.cell(row=1, column=1, value='Hello')

# Write multiple cells
data = [
    ['Name', 'Age', 'City'],
    ['Alice', 30, 'NYC'],
    ['Bob', 25, 'LA']
]

for row in data:
    sheet.append(row)
```

### Searching

```python
def search_workbook(wb, search_term):
    results = []
    for sheet_name in wb.sheetnames:
        sheet = wb[sheet_name]
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value and search_term in str(cell.value).lower():
                    results.append({
                        'sheet': sheet_name,
                        'cell': cell.coordinate,
                        'value': cell.value
                    })
    return results
```

### Saving

```python
# Save workbook
wb.save('output.xlsx')

# Close (read_only mode)
wb.close()
```

---

## Common Patterns

### Pattern 1: Read All Sheets Summary

```python
import pandas as pd

xl_file = pd.ExcelFile('file.xlsx')
summary = {}

for sheet_name in xl_file.sheet_names:
    df = xl_file.parse(sheet_name)
    summary[sheet_name] = {
        'rows': len(df),
        'columns': len(df.columns),
        'column_names': list(df.columns)
    }
```

### Pattern 2: Search All Sheets

```python
import openpyxl

def search_excel(file_path, search_term):
    wb = openpyxl.load_workbook(file_path, read_only=True)
    results = []

    for sheet_name in wb.sheetnames:
        sheet = wb[sheet_name]
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value and search_term.lower() in str(cell.value).lower():
                    results.append({
                        'sheet': sheet_name,
                        'cell': cell.coordinate,
                        'value': cell.value
                    })

    wb.close()
    return results
```

### Pattern 3: Extract Column

```python
import pandas as pd

df = pd.read_excel('file.xlsx', sheet_name='Data')
column_values = df['ColumnName'].dropna().tolist()
unique_values = df['ColumnName'].unique()
```

### Pattern 4: Compare Sheets

```python
import pandas as pd

sheet1 = pd.read_excel('file.xlsx', sheet_name='Sheet1')
sheet2 = pd.read_excel('file.xlsx', sheet_name='Sheet2')

# Find differences
diff = sheet1.compare(sheet2)

# Or compare specific columns
comparison = pd.DataFrame({
    'Sheet1': sheet1['Column'].sum(),
    'Sheet2': sheet2['Column'].sum()
})
```

---

## Performance Tips

### For Large Files

```python
# Use read_only mode
wb = openpyxl.load_workbook('large.xlsx', read_only=True)

# Read in chunks
chunk_size = 1000
for chunk in pd.read_excel('large.xlsx', chunksize=chunk_size):
    # Process chunk
    pass

# Read specific columns only
df = pd.read_excel('large.xlsx', usecols='A:E')

# Read limited rows
df = pd.read_excel('large.xlsx', nrows=1000)
```

### Memory Management

```python
# Delete dataframe when done
del df

# Close workbook
wb.close()

# Use context manager
with pd.ExcelFile('file.xlsx') as xl_file:
    df = xl_file.parse('Sheet1')
```

---

## Error Handling

```python
import pandas as pd
import os

def safe_read_excel(file_path, sheet_name=None):
    """Safely read Excel with error handling."""

    # Validate file
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    if not file_path.lower().endswith(('.xlsx', '.xls')):
        raise ValueError("File must be .xlsx or .xls format")

    try:
        # Attempt read
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        return df

    except PermissionError:
        raise PermissionError("File is open in another program")

    except Exception as e:
        raise Exception(f"Error reading Excel: {str(e)}")
```

---

## Dependencies

Required Python packages:
```bash
pip install pandas openpyxl xlrd
```

- **pandas**: Data analysis and manipulation
- **openpyxl**: Read/write Excel 2010 xlsx/xlsm files
- **xlrd**: Read older .xls files (Excel 2003 and earlier)
