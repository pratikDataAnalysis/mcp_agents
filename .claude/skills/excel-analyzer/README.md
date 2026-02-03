# Excel Analyzer Agent Skill

A comprehensive custom agent skill for reading, analyzing, and extracting insights from Excel spreadsheets.

## Directory Structure

```
.claude/skills/excel-analyzer/
├── README.md              # This file
├── SKILL.md               # Main skill definition (loaded by Claude)
├── EXAMPLES.md            # Detailed usage examples
├── REFERENCE.md           # Complete API reference
└── scripts/
    ├── read_excel.py      # Read and summarize Excel files
    ├── analyze_data.py    # Perform data analysis operations
    └── search_excel.py    # Search for text across all sheets
```

## What This Skill Does

The Excel Analyzer skill gives Claude the ability to:

✅ Read Excel files (.xlsx and .xls)
✅ Extract data from specific sheets or all sheets
✅ Analyze data with statistics, totals, averages
✅ Search for text across all sheets and cells
✅ Filter and extract specific data
✅ Compare data across multiple sheets
✅ Generate summaries and reports
✅ Handle large files efficiently
✅ Validate data quality
✅ Export data to different formats

## How It Works

### Progressive Loading

The skill uses Anthropic's progressive disclosure model:

1. **Metadata** (~100 tokens) - Always loaded, helps Claude know when to use this skill
2. **SKILL.md** (~5k tokens) - Loaded when Claude detects Excel-related tasks
3. **Supporting files** - Only loaded when Claude references them:
   - `EXAMPLES.md` - Loaded when Claude needs examples
   - `REFERENCE.md` - Loaded for detailed API information
   - Scripts - Executed without loading code into context

### When Claude Uses This Skill

Claude automatically loads this skill when:
- User mentions Excel files, spreadsheets, or .xlsx/.xls files
- User asks to read, analyze, or search Excel data
- User wants data extraction or summary from spreadsheets
- User needs to compare data across sheets

## Quick Start

### 1. Read an Excel File

**User**: "Read sales_report.xlsx and summarize it"

**Claude will**:
```python
import pandas as pd

df = pd.read_excel('sales_report.xlsx')
print(f"Rows: {len(df)}, Columns: {len(df.columns)}")
print(df.describe())
```

### 2. Search for Data

**User**: "Find all mentions of 'urgent' in customer_data.xlsx"

**Claude will**:
```bash
python scripts/search_excel.py customer_data.xlsx "urgent"
```

### 3. Analyze Data

**User**: "Calculate total sales by region"

**Claude will**:
```python
df = pd.read_excel('sales.xlsx')
totals = df.groupby('Region')['Sales'].sum()
print(totals)
```

## Helper Scripts Usage

### read_excel.py

Read and summarize Excel files:

```bash
# Show comprehensive summary
python scripts/read_excel.py file.xlsx --summary

# List all sheets
python scripts/read_excel.py file.xlsx --list-sheets

# Read specific sheet
python scripts/read_excel.py file.xlsx --sheet "Q1 Data"
```

### analyze_data.py

Perform analysis operations:

```bash
# Calculate totals
python scripts/analyze_data.py file.xlsx --sheet "Sales" --operation totals

# Calculate averages
python scripts/analyze_data.py file.xlsx --sheet "Sales" --operation averages

# Show summary statistics
python scripts/analyze_data.py file.xlsx --sheet "Sales" --operation summary

# Show value counts
python scripts/analyze_data.py file.xlsx --sheet "Sales" --operation counts

# Show correlations
python scripts/analyze_data.py file.xlsx --sheet "Sales" --operation correlations
```

### search_excel.py

Search for text across all sheets:

```bash
# Case-insensitive search (default)
python scripts/search_excel.py file.xlsx "search term"

# Case-sensitive search
python scripts/search_excel.py file.xlsx "SearchTerm" --case-sensitive

# Limit results
python scripts/search_excel.py file.xlsx "urgent" --max-results 100
```

## Dependencies

The skill requires these Python packages:

```bash
pip install pandas openpyxl xlrd
```

- **pandas** (2.2.0+) - Data analysis and manipulation
- **openpyxl** (3.1.2+) - Read/write Excel 2010+ files
- **xlrd** (2.0.1+) - Read older .xls files

## Integration with Your Project

### Option 1: Use with Claude Agent SDK

If you migrate to Claude Agent SDK (as discussed), this skill works natively:

```python
from claude_agent_sdk import query, ClaudeAgentOptions

options = ClaudeAgentOptions(
    cwd="/path/to/notion-play",
    setting_sources=["user", "project"],  # Loads skills from .claude/skills/
    allowed_tools=["Skill", "Read", "Write", "Bash"]
)

async for message in query("Analyze this Excel file", options=options):
    print(message)
```

### Option 2: Use with Claude API

Call Claude API with skills enabled:

```python
import anthropic

client = anthropic.Anthropic()

# For custom skills, you'd upload first or use in Agent SDK
# Pre-built skills work directly via skill_id
response = client.messages.create(
    model="claude-opus-4-5",
    max_tokens=4096,
    messages=[{
        "role": "user",
        "content": "Analyze sales_report.xlsx"
    }]
)
```

### Option 3: Use Scripts Standalone

The scripts work independently too:

```bash
# Direct script execution
python .claude/skills/excel-analyzer/scripts/read_excel.py data.xlsx --summary

# Integrate into your worker as subprocess
import subprocess
result = subprocess.run([
    'python', 'scripts/read_excel.py',
    'file.xlsx', '--summary'
], capture_output=True, text=True)
```

## Customization

### Modify the Skill

Edit `SKILL.md` to:
- Add domain-specific analysis patterns
- Include your company's Excel conventions
- Add industry-specific calculations
- Customize output formats

### Add More Scripts

Create new scripts in `scripts/` directory:
- `export_to_notion.py` - Export Excel data to Notion
- `generate_charts.py` - Create visualizations
- `validate_format.py` - Validate Excel structure

### Extend Examples

Add your use cases to `EXAMPLES.md`:
- Industry-specific analyses
- Custom reporting formats
- Integration workflows

## Best Practices

1. **Keep skill focused** - This skill does Excel analysis well, don't mix unrelated capabilities
2. **Reference supporting files** - Use `[EXAMPLES.md](EXAMPLES.md)` to load only when needed
3. **Update description** - Keep SKILL.md frontmatter description accurate for auto-triggering
4. **Test scripts independently** - Ensure scripts work standalone before relying on them
5. **Handle errors gracefully** - Scripts include error handling for common issues

## Troubleshooting

### Skill Not Loading

If Claude doesn't use the skill:
- Check the description in SKILL.md frontmatter
- Make sure file path is `.claude/skills/excel-analyzer/SKILL.md`
- Verify setting_sources includes "project" or "user"

### Script Errors

If scripts fail:
- Check Python dependencies are installed
- Verify script has execute permissions (`chmod +x scripts/*.py`)
- Ensure file paths are correct
- Check Python version (requires 3.8+)

### Large File Issues

For very large Excel files:
- Use `read_only=True` mode in openpyxl
- Read specific columns: `usecols='A:E'`
- Limit rows: `nrows=1000`
- Process in chunks

## Example Workflows

### Workflow 1: Daily Sales Report

```python
# 1. Read sales data
df = pd.read_excel('daily_sales.xlsx')

# 2. Calculate metrics
total_sales = df['Sales'].sum()
top_product = df.groupby('Product')['Sales'].sum().idxmax()

# 3. Save to Notion (using your existing MCP tool)
# notionApi:API-post-page with sales summary
```

### Workflow 2: Data Quality Audit

```python
# 1. Read customer data
df = pd.read_excel('customers.xlsx')

# 2. Check quality
missing = df.isnull().sum()
duplicates = df.duplicated().sum()

# 3. Report issues via WhatsApp
# Return formatted report to user
```

### Workflow 3: Multi-Sheet Comparison

```python
# 1. Read quarterly sheets
q1 = pd.read_excel('annual.xlsx', sheet_name='Q1')
q2 = pd.read_excel('annual.xlsx', sheet_name='Q2')

# 2. Compare and analyze
growth = ((q2['Sales'].sum() - q1['Sales'].sum()) / q1['Sales'].sum()) * 100

# 3. Generate insights
# Return growth analysis to user
```

## Future Enhancements

Potential additions:
- Chart generation from Excel data
- Export to multiple formats (PDF, JSON, CSV)
- Data validation rules
- Pivot table creation
- Conditional formatting analysis
- Formula parsing and evaluation

## Support

For issues or questions:
1. Check `EXAMPLES.md` for usage patterns
2. Review `REFERENCE.md` for API details
3. Test scripts independently
4. Check pandas/openpyxl documentation

## License

This skill is part of your notion-play project.
