# Excel Analyzer - Usage Examples

Complete examples of common Excel analysis tasks.

---

## Example 1: Basic Sales Report Analysis

**User Request**: "Read sales_report.xlsx and give me a summary"

**Solution**:
```python
import pandas as pd

# Read the Excel file
df = pd.read_excel('sales_report.xlsx')

# Generate summary statistics
print("=== Sales Report Summary ===\n")
print(f"Total Rows: {len(df)}")
print(f"Columns: {', '.join(df.columns)}")
print(f"\nSales Statistics:")
print(df['Sales'].describe())

# Calculate key metrics
total_sales = df['Sales'].sum()
avg_sale = df['Sales'].mean()
max_sale = df['Sales'].max()

print(f"\nKey Metrics:")
print(f"Total Sales: ${total_sales:,.2f}")
print(f"Average Sale: ${avg_sale:,.2f}")
print(f"Highest Sale: ${max_sale:,.2f}")

# Show top 5 sales
print(f"\nTop 5 Sales:")
print(df.nlargest(5, 'Sales')[['Date', 'Customer', 'Sales']])
```

**Output**:
```
=== Sales Report Summary ===

Total Rows: 234
Columns: Date, Customer, Product, Sales, Region

Sales Statistics:
count     234.00
mean     5234.12
std      2145.67
min       125.00
max     15430.00

Key Metrics:
Total Sales: $1,224,784.08
Average Sale: $5,234.12
Highest Sale: $15,430.00

Top 5 Sales:
         Date         Customer     Sales
45  2024-01-15    Acme Corp    15430.00
78  2024-01-22    TechStart    14220.50
...
```

---

## Example 2: Search for Specific Data

**User Request**: "Find all mentions of 'urgent' in customer_data.xlsx"

**Solution**:
```python
import pandas as pd

# Read the file
df = pd.read_excel('customer_data.xlsx')

# Search in all text columns
results = []

for column in df.select_dtypes(include=['object']).columns:
    matches = df[df[column].str.contains('urgent', case=False, na=False)]
    if not matches.empty:
        results.append({
            'column': column,
            'matches': len(matches),
            'rows': matches.index.tolist()
        })

# Display results
print(f"Found 'urgent' in {len(results)} columns:\n")
for result in results:
    print(f"Column '{result['column']}': {result['matches']} matches")
    print(f"  Rows: {result['rows'][:10]}")  # Show first 10 row numbers
```

**Output**:
```
Found 'urgent' in 2 columns:

Column 'Notes': 5 matches
  Rows: [23, 45, 67, 89, 102]
Column 'Status': 3 matches
  Rows: [12, 34, 56]
```

---

## Example 3: Compare Monthly Data

**User Request**: "Compare sales between January and February in monthly_report.xlsx"

**Solution**:
```python
import pandas as pd

# Read both sheets
jan_data = pd.read_excel('monthly_report.xlsx', sheet_name='January')
feb_data = pd.read_excel('monthly_report.xlsx', sheet_name='February')

# Calculate totals
jan_total = jan_data['Sales'].sum()
feb_total = feb_data['Sales'].sum()

# Calculate growth
growth = ((feb_total - jan_total) / jan_total) * 100

# Compare by category
jan_by_category = jan_data.groupby('Category')['Sales'].sum()
feb_by_category = feb_data.groupby('Category')['Sales'].sum()

print(f"=== Monthly Comparison ===\n")
print(f"January Total: ${jan_total:,.2f}")
print(f"February Total: ${feb_total:,.2f}")
print(f"Growth: {growth:+.1f}%")

print(f"\nBy Category:")
comparison = pd.DataFrame({
    'January': jan_by_category,
    'February': feb_by_category,
    'Change': feb_by_category - jan_by_category,
    'Growth %': ((feb_by_category - jan_by_category) / jan_by_category * 100)
})
print(comparison)
```

**Output**:
```
=== Monthly Comparison ===

January Total: $125,430.50
February Total: $142,567.80
Growth: +13.7%

By Category:
              January    February     Change  Growth %
Electronics   45230.00   52340.00   7110.00     15.7
Clothing      38420.00   41230.00   2810.00      7.3
Home          41780.50   48997.80   7217.30     17.3
```

---

## Example 4: Extract Top Performers

**User Request**: "Who are the top 10 salespeople this quarter?"

**Solution**:
```python
import pandas as pd

# Read sales data
df = pd.read_excel('quarterly_sales.xlsx')

# Group by salesperson and sum sales
top_performers = df.groupby('Salesperson').agg({
    'Sales': 'sum',
    'Transactions': 'count'
}).reset_index()

# Sort by total sales
top_performers = top_performers.sort_values('Sales', ascending=False)

# Get top 10
top_10 = top_performers.head(10)

# Calculate average per transaction
top_10['Avg per Transaction'] = top_10['Sales'] / top_10['Transactions']

print("=== Top 10 Salespeople ===\n")
for idx, row in top_10.iterrows():
    print(f"{idx+1}. {row['Salesperson']}")
    print(f"   Total Sales: ${row['Sales']:,.2f}")
    print(f"   Transactions: {row['Transactions']}")
    print(f"   Avg/Transaction: ${row['Avg per Transaction']:,.2f}\n")
```

---

## Example 5: Data Quality Check

**User Request**: "Check customer_list.xlsx for any issues"

**Solution**:
```python
import pandas as pd

df = pd.read_excel('customer_list.xlsx')

print("=== Data Quality Report ===\n")

# 1. Check for missing values
missing = df.isnull().sum()
if missing.sum() > 0:
    print("Missing Values Found:")
    print(missing[missing > 0])
else:
    print("✓ No missing values")

# 2. Check for duplicates
duplicates = df.duplicated().sum()
if duplicates > 0:
    print(f"\n⚠ Found {duplicates} duplicate rows")
    # Show duplicate examples
    dupes = df[df.duplicated(keep=False)].sort_values(by=list(df.columns))
    print("First few duplicates:")
    print(dupes.head())
else:
    print("\n✓ No duplicate rows")

# 3. Check email format
def is_valid_email(email):
    import re
    if pd.isna(email):
        return False
    return bool(re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', str(email)))

if 'Email' in df.columns:
    invalid_emails = df[~df['Email'].apply(is_valid_email)]
    if len(invalid_emails) > 0:
        print(f"\n⚠ Found {len(invalid_emails)} invalid email addresses")
    else:
        print("\n✓ All email addresses valid")

# 4. Check for blank entries
blank_entries = (df == '').sum()
if blank_entries.sum() > 0:
    print(f"\nBlank Entries Found:")
    print(blank_entries[blank_entries > 0])

print("\n--- Report Complete ---")
```

---

## Example 6: Create Summary Statistics

**User Request**: "Give me detailed statistics for the sales data"

**Solution**:
```python
import pandas as pd

df = pd.read_excel('sales_data.xlsx')

print("=== Comprehensive Statistics ===\n")

# Overall statistics
print("Overall Summary:")
print(df.describe())

# Statistics by region
print("\n\nBy Region:")
region_stats = df.groupby('Region')['Sales'].agg([
    ('Total', 'sum'),
    ('Average', 'mean'),
    ('Median', 'median'),
    ('Min', 'min'),
    ('Max', 'max'),
    ('Count', 'count')
])
print(region_stats)

# Month-over-month trends
df['Month'] = pd.to_datetime(df['Date']).dt.to_period('M')
monthly_trend = df.groupby('Month')['Sales'].agg(['sum', 'mean', 'count'])
print("\n\nMonthly Trends:")
print(monthly_trend)

# Product performance
print("\n\nTop 5 Products:")
top_products = df.groupby('Product')['Sales'].sum().nlargest(5)
print(top_products)
```

---

## Example 7: Filter and Export Data

**User Request**: "Get all sales over $5000 from the North region and save to new file"

**Solution**:
```python
import pandas as pd

# Read data
df = pd.read_excel('all_sales.xlsx')

# Apply filters
filtered = df[
    (df['Sales'] > 5000) &
    (df['Region'] == 'North')
]

print(f"Found {len(filtered)} sales matching criteria")

# Show summary
print(f"\nTotal Value: ${filtered['Sales'].sum():,.2f}")
print(f"Average: ${filtered['Sales'].mean():,.2f}")

# Preview data
print("\nFirst 10 matching records:")
print(filtered.head(10))

# Export to new Excel file
output_file = 'north_high_value_sales.xlsx'
filtered.to_excel(output_file, index=False)
print(f"\n✓ Data exported to {output_file}")
```

---

## Example 8: Multi-Sheet Analysis

**User Request**: "Analyze all quarterly sheets in annual_report.xlsx"

**Solution**:
```python
import pandas as pd

# Read all sheets
xl_file = pd.ExcelFile('annual_report.xlsx')

quarterly_summary = []

for sheet_name in xl_file.sheet_names:
    if sheet_name.startswith('Q'):  # Q1, Q2, Q3, Q4
        df = xl_file.parse(sheet_name)

        summary = {
            'Quarter': sheet_name,
            'Total Sales': df['Sales'].sum(),
            'Transactions': len(df),
            'Avg Sale': df['Sales'].mean(),
            'Top Product': df.groupby('Product')['Sales'].sum().idxmax()
        }
        quarterly_summary.append(summary)

# Create summary dataframe
summary_df = pd.DataFrame(quarterly_summary)

print("=== Annual Summary by Quarter ===\n")
print(summary_df.to_string(index=False))

# Calculate year-over-year
total_annual = summary_df['Total Sales'].sum()
print(f"\nTotal Annual Sales: ${total_annual:,.2f}")

# Find best quarter
best_quarter = summary_df.loc[summary_df['Total Sales'].idxmax()]
print(f"Best Quarter: {best_quarter['Quarter']} (${best_quarter['Total Sales']:,.2f})")
```

---

## Example 9: Pivot Analysis

**User Request**: "Create a pivot table showing sales by region and product category"

**Solution**:
```python
import pandas as pd

df = pd.read_excel('sales_data.xlsx')

# Create pivot table
pivot = pd.pivot_table(
    df,
    values='Sales',
    index='Region',
    columns='Category',
    aggfunc='sum',
    margins=True,  # Add totals
    margins_name='Total'
)

print("=== Sales by Region and Category ===\n")
print(pivot)

# Format as currency
print("\n=== Formatted View ===\n")
formatted = pivot.applymap(lambda x: f"${x:,.2f}" if pd.notna(x) else "N/A")
print(formatted)
```

---

## Example 10: Time Series Analysis

**User Request**: "Show sales trends over time"

**Solution**:
```python
import pandas as pd

df = pd.read_excel('historical_sales.xlsx')

# Convert date column
df['Date'] = pd.to_datetime(df['Date'])

# Group by month
df['Month'] = df['Date'].dt.to_period('M')
monthly_sales = df.groupby('Month')['Sales'].agg(['sum', 'count', 'mean'])

print("=== Monthly Sales Trends ===\n")
print(monthly_sales)

# Calculate month-over-month growth
monthly_sales['MoM Growth %'] = monthly_sales['sum'].pct_change() * 100

print("\n=== With Growth Rates ===\n")
print(monthly_sales)

# Identify trends
avg_growth = monthly_sales['MoM Growth %'].mean()
print(f"\nAverage Monthly Growth: {avg_growth:+.1f}%")

if avg_growth > 0:
    print("📈 Overall trend: Growing")
else:
    print("📉 Overall trend: Declining")
```

---

These examples cover the most common Excel analysis scenarios. Use them as templates and adapt to your specific needs!
