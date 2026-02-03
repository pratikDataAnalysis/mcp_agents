# Indian Dishes Chef Agent Setup

A specialized agent that suggests Indian dish recipes and meals from a database of 6000+ dishes.

## Overview

The Chef Agent helps users discover and prepare Indian dishes based on their preferences. It has direct access to your Indian dishes Excel database and uses LLM-powered recommendations to provide personalized suggestions.

## Architecture

```
User: "Suggest a vegetarian dinner recipe"
  ↓
Supervisor (routes to Chef agent)
  ↓
Chef Agent (4 specialized tools)
  ├─→ indianDishes_search (search by ingredient/name/type)
  ├─→ indianDishes_suggest (LLM-powered recommendations)
  ├─→ indianDishes_get_recipe (get full recipe details)
  └─→ indianDishes_analyze_database (database statistics)
  ↓
Excel Scripts (read/search the Excel file)
  ↓
LLM (format and rank results)
  ↓
Chef Agent (formatted response)
  ↓
Supervisor → User
```

## What Was Created

### 1. Chef Tools (`src/app/mcp/tools/chef_tools.py`)

Four specialized tools with `source_server="indianDishes"`:

| Tool | Description | Use Case |
|------|-------------|----------|
| `indianDishes_search` | Search dishes by ingredients, name, cuisine | "Find dishes with paneer" |
| `indianDishes_suggest` | Get top X recommendations (LLM-powered) | "Suggest vegetarian dinner" |
| `indianDishes_get_recipe` | Get detailed recipe for specific dish | "How to make Biryani?" |
| `indianDishes_analyze_database` | Database statistics and overview | "What cuisines are available?" |

### 2. Agent Configuration (`server_agent_map.json`)

```json
"indianDishes": {
  "blacklisted_tools": [],
  "agents": [
    {
      "name": "chef",
      "responsibility": "Suggest Indian dish recipes and meals...",
      "tools": [
        "indianDishes_search",
        "indianDishes_suggest",
        "indianDishes_get_recipe",
        "indianDishes_analyze_database"
      ]
    }
  ]
}
```

### 3. Policy Pack (`policy_packs/indianDishes.json`)

Injects expert Indian cuisine knowledge:
- 6000+ dishes across regional cuisines
- Dietary considerations (vegetarian, vegan, Jain, gluten-free)
- Cultural sensitivity
- Recommendation strategies
- Tool usage guidelines

### 4. Tools Registry (`src/app/mcp/tools/__init__.py`)

Updated to load Chef tools alongside other local tools.

## Setup Instructions

### 1. Place Your Excel File

The system expects your Indian dishes Excel file at:

```
./data/indian_dishes.xlsx
```

**Option A: Use default location**
```bash
mkdir -p data
# Copy your Excel file to data/indian_dishes.xlsx
cp /path/to/your/dishes.xlsx data/indian_dishes.xlsx
```

**Option B: Configure custom path**

Add to your `.env` file:
```bash
INDIAN_DISHES_EXCEL_PATH=/absolute/path/to/your/dishes.xlsx
```

Or add to `src/app/config/settings.py`:
```python
indian_dishes_excel_path: str = Field(default="./data/indian_dishes.xlsx")
```

### 2. Excel File Structure

Your Excel file should have columns like:
- **Dish Name** - Name of the dish
- **Ingredients** - List of ingredients
- **Recipe/Instructions** - Cooking steps
- **Cuisine Type** - Region (Punjabi, South Indian, etc.)
- **Dietary** - Veg/Non-veg/Vegan
- **Meal Type** - Breakfast/Lunch/Dinner/Snack
- *(Any other relevant columns)*

**Note:** The tools will work with any column structure, but having these columns improves recommendations.

### 3. Restart Worker

Restart your worker to load the Chef agent:

```bash
./run.sh
```

### 4. Verify in Logs

Look for:
```
INFO: Local MCP tools loaded | sources={'localAudio': 3, 'excelAnalysis': 3, 'indianDishes': 4} | tools=10
INFO: Agent created | name=chef | tools=4
INFO: Supervisor ready
```

## Usage Examples

### Example 1: Get Recommendations

**User:** "Suggest 3 vegetarian dinner recipes"

**Flow:**
1. Supervisor → Chef agent
2. Chef uses `indianDishes_suggest(criteria="vegetarian dinner", count=3)`
3. Tool searches Excel file for vegetarian dishes
4. LLM ranks and formats top 3 recommendations
5. Chef returns formatted list with reasoning

**Expected Response:**
```
Here are 3 great vegetarian dinner options:

1. Palak Paneer - Creamy spinach curry with cottage cheese, rich in protein
2. Dal Makhani - Slow-cooked black lentils in buttery tomato gravy
3. Vegetable Biryani - Fragrant rice with mixed vegetables and aromatic spices

Would you like the detailed recipe for any of these?
```

### Example 2: Search by Ingredient

**User:** "What dishes can I make with paneer?"

**Flow:**
1. Supervisor → Chef agent
2. Chef uses `indianDishes_search(search_term="paneer", max_results=10)`
3. Excel script searches all sheets for "paneer"
4. Returns matching dishes with cell locations
5. Chef formats and presents options

**Expected Response:**
```
I found 12 dishes with paneer:

Popular options:
- Paneer Tikka (Sheet: Appetizers, Row 45)
- Palak Paneer (Sheet: Main Course, Row 128)
- Paneer Butter Masala (Sheet: Main Course, Row 134)
- Kadai Paneer (Sheet: Main Course, Row 141)
- Shahi Paneer (Sheet: Main Course, Row 156)

Would you like the recipe for any of these?
```

### Example 3: Get Specific Recipe

**User:** "How do I make Dal Makhani?"

**Flow:**
1. Supervisor → Chef agent
2. Chef uses `indianDishes_get_recipe(dish_name="Dal Makhani")`
3. Excel script searches for exact dish name
4. Returns recipe details
5. Chef formats recipe clearly

**Expected Response:**
```
Recipe for Dal Makhani:

Ingredients:
- 1 cup whole black lentils (urad dal)
- 1/4 cup kidney beans (rajma)
- ... [full ingredient list from Excel]

Instructions:
1. Soak lentils and kidney beans overnight
2. Pressure cook for 15-20 minutes
... [full steps from Excel]

Cooking Time: 45 minutes
Serves: 4 people
Cuisine: Punjabi
```

### Example 4: Dietary Restrictions

**User:** "I'm vegan, what can I eat?"

**Flow:**
1. Supervisor → Chef agent
2. Chef uses `indianDishes_search(search_term="vegan")`
3. Also searches for "no dairy", "plant-based"
4. Filters and recommends vegan options

### Example 5: Database Overview

**User:** "What types of dishes do you have?"

**Flow:**
1. Supervisor → Chef agent
2. Chef uses `indianDishes_analyze_database(analysis_type="summary")`
3. Excel script analyzes file structure
4. Returns statistics on cuisine types, dish counts, etc.

## How It Works

### Tool: `indianDishes_search`

**What it does:**
- Searches Excel file for matching dishes
- Uses `search_excel.py` script
- Returns cell locations and values

**Parameters:**
- `search_term`: What to search for
- `max_results`: Limit (default: 20)
- `case_sensitive`: Boolean (default: False)

**Example:**
```python
indianDishes_search(
    search_term="biryani",
    max_results=10
)
```

### Tool: `indianDishes_suggest`

**What it does:**
1. Searches Excel file broadly based on criteria
2. Uses LLM to analyze results and rank dishes
3. Returns top X recommendations with reasoning

**Parameters:**
- `criteria`: User's preferences (e.g., "vegetarian spicy lunch")
- `count`: Number of suggestions (default: 5)

**Example:**
```python
indianDishes_suggest(
    criteria="healthy low-calorie breakfast",
    count=3
)
```

**LLM Prompt:**
```
You are an expert Indian cuisine chef. Suggest the top {count} dishes
matching these criteria: {criteria}

Search Results: {excel_search_results}

Format as numbered list with brief reasoning.
```

### Tool: `indianDishes_get_recipe`

**What it does:**
- Searches for specific dish by name
- Returns full recipe details
- Formats nicely for user

**Parameters:**
- `dish_name`: Name of the dish

**Example:**
```python
indianDishes_get_recipe(dish_name="Butter Chicken")
```

### Tool: `indianDishes_analyze_database`

**What it does:**
- Analyzes Excel file structure
- Returns statistics and summaries
- Helps user understand available options

**Parameters:**
- `analysis_type`: "summary", "counts", or "cuisines"

**Example:**
```python
indianDishes_analyze_database(analysis_type="summary")
```

## Customization

### Add More Tools

Create additional tools in `chef_tools.py`:

```python
@tool(name_or_callable="indianDishes_filter_by_spice")
def indianDishes_filter_by_spice(spice_level: str) -> str:
    """Filter dishes by spice level (mild/medium/spicy)."""
    # Implementation
    ...

# Tag and export
indianDishes_filter_by_spice = tag_tool(
    indianDishes_filter_by_spice,
    source_server=INDIAN_DISHES_SOURCE_SERVER,
)

def get_chef_tools():
    return [
        indianDishes_search,
        indianDishes_suggest,
        indianDishes_get_recipe,
        indianDishes_analyze_database,
        indianDishes_filter_by_spice,  # NEW
    ]
```

Then update `server_agent_map.json` to include the new tool.

### Modify Policy Pack

Edit `policy_packs/indianDishes.json` to:
- Add your family's cooking style preferences
- Include specific dietary guidelines
- Add custom recommendation logic
- Include regional specialties

### Configure Excel Path

**Method 1: Environment Variable**

Add to `.env`:
```bash
INDIAN_DISHES_EXCEL_PATH=/Users/rashmi/recipes/indian_dishes.xlsx
```

**Method 2: Settings File**

Add to `src/app/config/settings.py`:
```python
class Settings(BaseSettings):
    # ... existing settings ...

    indian_dishes_excel_path: str = Field(
        default="./data/indian_dishes.xlsx",
        description="Path to Indian dishes Excel database"
    )
```

### Improve Recommendations

The `indianDishes_suggest` tool uses LLM to rank dishes. You can:

1. **Improve search keywords extraction:**
```python
# Use LLM to extract better search terms from criteria
llm = _build_llm()
keywords = llm.invoke(f"Extract search keywords from: {criteria}")
```

2. **Add more context to LLM prompt:**
```python
prompt = f"""
Consider:
- User preferences: {criteria}
- Time of day: {current_time}
- Season: {current_season}
- Previous recommendations: {user_history}

Suggest dishes accordingly.
"""
```

3. **Filter by additional criteria:**
```python
# Filter by cooking time, difficulty, available ingredients
```

## Testing

### Test 1: Basic Search

```bash
# Via WhatsApp or API
User: "Find dishes with chicken"

# Expected: List of chicken dishes from database
```

### Test 2: Recommendations

```bash
User: "Suggest a healthy vegetarian lunch"

# Expected: 3-5 vegetarian lunch dishes with reasoning
```

### Test 3: Recipe Retrieval

```bash
User: "How to make Chole Bhature?"

# Expected: Full recipe with ingredients and steps
```

### Test 4: Database Analysis

```bash
User: "What regional cuisines are available?"

# Expected: Summary of available cuisines in database
```

## Troubleshooting

### Excel File Not Found

**Symptom:**
```
ToolException: Excel script failed: Error: File not found: ./data/indian_dishes.xlsx
```

**Solution:**
1. Check file exists: `ls -la data/indian_dishes.xlsx`
2. Verify path in logs
3. Set correct path in `.env`: `INDIAN_DISHES_EXCEL_PATH=/full/path/to/file.xlsx`

### No Dishes Found

**Symptom:**
```
No matches found for search term: "paneer"
```

**Solution:**
1. Check Excel file has data
2. Verify column names and content
3. Try broader search term
4. Use `indianDishes_analyze_database` to understand file structure

### LLM Recommendations Failed

**Symptom:**
```
LLM recommendation failed, falling back to raw search results
```

**Solution:**
1. Check LLM provider is configured (OpenAI API key, Ollama running)
2. Verify network connection
3. Check logs for specific error
4. Fallback will return raw search results (still functional)

### Chef Agent Not Created

**Symptom:**
```
INFO: Agent creation complete | agents=4
(No chef agent)
```

**Solution:**
1. Verify `chef_tools.py` has no syntax errors
2. Check `server_agent_map.json` has indianDishes config
3. Restart worker completely
4. Check logs for import errors

## Performance Considerations

### Large Excel Files (6000+ rows)

The Excel file with 6000+ dishes might be slow to search. Optimizations:

1. **Limit search results:**
```python
indianDishes_search(search_term="...", max_results=20)  # Don't return all 6000
```

2. **Use specific search terms:**
```python
# Good: "vegetarian breakfast"
# Better: "idli dosa breakfast South Indian"
```

3. **Cache frequent searches:**
```python
# Add caching layer (Redis, in-memory)
@lru_cache(maxsize=100)
def cached_search(search_term):
    return indianDishes_search(search_term)
```

4. **Pre-filter in Excel:**
Create separate sheets for:
- Vegetarian dishes
- Non-vegetarian dishes
- By cuisine (North, South, etc.)
- By meal type (Breakfast, Lunch, Dinner)

Then search specific sheets instead of entire file.

## Integration with Other Agents

### Chef + Notion Agent

Save favorite recipes to Notion:

```
User: "Save the Dal Makhani recipe to my Notion"

1. Chef agent → gets recipe
2. Supervisor → Notion agent
3. Notion agent → creates page with recipe
```

### Chef + WhatsApp Media

Send recipe as formatted message:

```
User: "Send me the Biryani recipe"

1. Chef agent → gets recipe
2. Formats as WhatsApp message
3. Returns to supervisor
4. Supervisor → WhatsApp (via Twilio)
```

## Future Enhancements

### Meal Planning

Add tool for weekly meal plans:
```python
@tool
def indianDishes_create_meal_plan(days: int, dietary: str):
    """Generate a weekly meal plan."""
    ...
```

### Ingredient Shopping List

Generate shopping list from recipes:
```python
@tool
def indianDishes_shopping_list(dish_names: List[str]):
    """Create ingredient shopping list for multiple dishes."""
    ...
```

### Nutrition Information

If your Excel has nutrition data:
```python
@tool
def indianDishes_nutrition_info(dish_name: str):
    """Get calories, protein, carbs for a dish."""
    ...
```

### Cooking Instructions with Images

If you add image URLs to Excel:
```python
@tool
def indianDishes_recipe_with_images(dish_name: str):
    """Get recipe with step-by-step images."""
    ...
```

## Summary

**What you have now:**

✅ **Chef Agent** with 4 specialized tools
✅ **Direct access** to 6000+ Indian dishes Excel database
✅ **LLM-powered recommendations** for personalized suggestions
✅ **Policy pack** with Indian cuisine expertise
✅ **Automatic routing** via supervisor
✅ **Error handling** and fallbacks
✅ **Configurable** Excel file path

**User Experience:**

```
User: "Suggest a vegetarian dinner"
↓
Chef agent searches database
↓
LLM ranks and recommends top 5 dishes
↓
User receives: "1. Palak Paneer - Creamy spinach curry..."
```

**Next Steps:**

1. Place your Excel file in `./data/indian_dishes.xlsx`
2. Restart worker: `./run.sh`
3. Test via WhatsApp: "Suggest a dinner recipe"
4. Monitor logs for Chef agent activity

The integration is complete! 🎉
