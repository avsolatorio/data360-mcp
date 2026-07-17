import json

def get_chartjs_system_prompt() -> str:
    """
    Returns the system instructions for generating a valid Chart.js JSON configuration.
    """
    return (
        "You are a Chart.js v4 JSON config generator. Return only a valid JSON object. "
        "Normally, the object must contain keys: 'type', 'data', and 'options'. "
        "However, if the dataset is not suitable to chart (e.g. empty, all null, or "
        "insufficient data points), you MUST refuse by returning a JSON object containing "
        "exactly one key: 'error' with a clear explanation. No markdown, no leading/trailing text."
    )

def get_chartjs_user_prompt(question: str, column_names: list[str], sample_data: list[dict]) -> str:
    """
    Generates the user instructions containing the dataset structure, rows,
    and visual grammar instructions for Chart.js.
    """
    return f"""
You are an expert data visualization engineer. You are given a user request and a dataset.
Generate a complete, production-ready Chart.js v4 configuration object (JSON) that best represents the requested chart.

User Request: "{question}"

Dataset columns available: {json.dumps(column_names)}
Dataset:
{json.dumps(sample_data, indent=2)}

Requirements:
1. Data Suitability and Refusal:
   - First, evaluate if the dataset is suitable to chart.
   - Refusal Criteria: If the dataset is empty, contains all null values, or contains insufficient non-null data points (e.g. less than 2 data points for a temporal line trend, or 0 data points for categorical comparison), or the requested series/columns are missing:
     - You MUST refuse to chart.
     - Return a single JSON object containing exactly one key: "error" with a clear, specific, human-readable reason why (e.g. {{"error": "No non-null data points available to plot."}}).
2. JSON Structure: If the dataset is suitable, output a single JSON object with exactly three top-level keys: "type", "data", and "options". Do NOT include an "error" key.
3. Chart Type Selection: Decide the best Chart.js chart type on your own based solely on the user request and dataset structure. Supported types (exactly these 8 standard Chart.js types):
   - "line": Use for multi-year temporal trends (requires at least 2 distinct data points over time).
   - "bar": Use for single-year comparisons, ranking, or categorical comparisons.
   - "radar": Use for multi-dimensional profile comparisons across 3+ categories.
   - "doughnut": Use for part-to-whole breakdown comparisons (preferred over pie).
   - "pie": Use for simple part-to-whole comparisons.
   - "polarArea": Use for comparing categories with similar/equal angles but differing magnitudes.
   - "bubble": Use for 3-dimensional numeric data comparisons.
   - "scatter": Use for correlation between two numerical indicators.
4. "data": Structure it properly based on your chosen chart type:
   - For line/bar/radar/polarArea charts:
     * "labels" should be an array of categories (e.g. years, or country names).
     * "datasets" should be an array of objects, one per series. Each dataset object must have:
       * "label": human-readable series name.
       * "data": array of numeric values corresponding to the "labels" array.
       * "borderColor" and/or "backgroundColor": colors chosen from the World Bank palette.
   - For scatter/bubble plots:
     * "datasets" should contain the data points formatted as objects: {{"x": val1, "y": val2}} (or {{"x": x, "y": y, "r": r}} for bubble).
5. Colors: Use the World Bank palette (cycle through as needed):
   ["#34A7F2", "#FF9800", "#664AB6", "#4EC2C0", "#F3578E", "#081079", "#0C7C68"]
6. "options": Configure title, legend, and scales:
   - "responsive": true, "maintainAspectRatio": false.
   - "plugins": {{"title": {{"display": true, "text": "<descriptive title>"}}, "legend": {{"display": true, "position": "bottom"}}}}
   - "scales": (Only for Cartesian types: line, bar, scatter, bubble):
     {{"x": {{"title": {{"display": true, "text": "<x axis label>"}}}}, "y": {{"title": {{"display": true, "text": "<y axis label>"}}, "beginAtZero": false}}}}
7. Populate "data" only with values from the dataset above. Do NOT use placeholder or dummy data.
8. Return ONLY a valid JSON object. No markdown code blocks, no leading/trailing text.
"""
