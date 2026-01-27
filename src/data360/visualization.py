"""
Visualization generation for Data360 data.

This module fetches data from a Data360 API URL and generates
Vega-Lite visualization specifications optimized for the data structure.
"""

import json
import logging
import os
import uuid
from urllib.parse import parse_qs, urlparse

import altair as alt
import httpx
import pandas as pd
from draco import Draco, answer_set_to_dict, dict_to_facts, schema_from_dataframe
from draco.renderer import AltairRenderer

_logger = logging.getLogger(__name__)


def save_specs_to_static(vl_spec: dict) -> str:
    """Save Vega-Lite spec to static/viz_specs/ directory.

    Returns:
        URL for the saved spec
    """
    spec_id = str(uuid.uuid4())
    specs_dir = os.path.join(os.getcwd(), "static", "viz_specs")
    os.makedirs(specs_dir, exist_ok=True)

    # Save Vega-Lite spec
    vega_path = os.path.join(specs_dir, f"{spec_id}_vega.json")
    with open(vega_path, "w") as f:
        json.dump(vl_spec, f, indent=2)

    # Return URL (assuming server runs on port 8021)
    # Use host.docker.internal for Docker compatibility, or localhost if running natively
    # For now, we default to localhost because the Frontend (browser) needs to access this,
    # and host.docker.internal typically doesn't resolve in the browser on Mac/Windows without /etc/hosts hacks.
    # HOWEVER, since the user explicitly asked for Docker support, we will stick to localhost
    # because the browser (client-side) is what fetches this JSON, not the Docker container.
    base_url = "http://localhost:8021/static/viz_specs"
    return f"{base_url}/{spec_id}_vega.json"


def _parse_chart_type_hint(chart_type: str | None) -> str:
    """Parse user's chart type hint into Vega-Lite mark type.

    Args:
        chart_type: User's hint like "line chart", "bar", "scatter", etc.

    Returns:
        Vega-Lite mark type, defaults to 'line' for time series data
    """
    if not chart_type:
        return "line"  # Default to line for time series

    hint = chart_type.lower().strip()

    # Map common terms to Vega-Lite mark types https://dig.cmu.edu/draco2/facts/mark.html
    # rect and text are not supported as of now
    if any(x in hint for x in ["line", "trend", "time series"]):
        return "line"
    elif any(x in hint for x in ["bar", "column", "histogram"]):
        return "bar"
    elif any(x in hint for x in ["scatter", "point", "dot"]):
        return "point"
    elif any(x in hint for x in ["area", "filled"]):
        return "area"
    elif any(x in hint for x in ["tick"]):
        return "tick"

    return "line"  # Default


async def _fetch_data_internal(url: str) -> pd.DataFrame:
    """Fetch data from a Data360 API URL and return as DataFrame.

    Args:
        url: Data360 API URL

    Returns:
        pandas DataFrame with the data

    Raises:
        ValueError: If no data found or fetch fails
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

    raw_data = data.get("value", [])
    if not raw_data:
        raise ValueError("No data found at the provided URL.")

    df = pd.DataFrame(raw_data)
    return df


def get_supported_chart_types() -> str:
    """Return a list of supported chart types and their data requirements.

    Returns:
        JSON string containing the list of supported chart types.
    """
    chart_types = {
        "chart_types": [
            {
                "id": "line",
                "description": "Line chart for showing trends over time.",
                "when_to_use": "Use when you have a continuous time variable and a quantitative measure.",
                "data_requirements": "Requires 'time_period' (or similar date field) and 'obs_value' (metric).",
            },
            {
                "id": "bar",
                "description": "Bar chart for comparing values across categories.",
                "when_to_use": "Use for comparing metrics between discrete categories or time periods.",
                "data_requirements": "Requires one categorical/ordinal field and 'obs_value'.",
            },
            {
                "id": "point",
                "description": "Scatter plot (point chart) for correlation.",
                "when_to_use": "Use to show the relationship between two quantitative variables.",
                "data_requirements": "Requires two quantitative fields.",
            },
            {
                "id": "area",
                "description": "Area chart for cumulative trends.",
                "when_to_use": "Use to show volume or quantity over time.",
                "data_requirements": "Similar to line chart: 'time_period' and 'obs_value'.",
            },
            {
                "id": "tick",
                "description": "Tick plot for distribution.",
                "when_to_use": "Use to show the distribution of values along an axis.",
                "data_requirements": "Requires one quantitative field.",
            },
        ],
        "guidance": "Select the 'relevant_fields' from the available data that match the 'data_requirements' of the desired chart type.",
    }
    return json.dumps(chart_types, indent=2)


async def get_viz_spec(
    database_id: str,
    indicator_id: str,
    country_code: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    disaggregation_filters: dict[str, str | None] | None = None,
    chart_type: str | None = None,
    relevant_fields: list[str] | None = None,
    custom_constraints: list[str] | None = None,
    use_default_constraints: bool = True,
) -> str:
    """Generate a Vega-Lite visualization specification from Data360 API parameters.

    This function:
    1. Generates the Data API URL internally
    2. Fetches data from that URL
    3. Cleans and prepares the data
    4. Uses Draco2 to generate optimal chart configuration
    5. Saves the Vega-Lite spec to static/specs/
    6. Returns the URL to the spec

    Args:
        database_id: Database identifier (e.g., WB_HNP, WB_WDI)
        indicator_id: Indicator ID (e.g., WB_HNP_SP_POP_TOTL)
        country_code: Optional country code (e.g., "KEN" or "CHN,USA")
        start_year: Optional start year
        end_year: Optional end year
        disaggregation_filters: Optional dict of dimension filters (e.g., {"SEX": "F"})
        chart_type: Optional hint for chart type (e.g., "line chart", "bar chart").
        relevant_fields: Optional list of column names to strictly use for visualization.
                         The LLM should identify these based on the data structure.
        custom_constraints: Optional list of raw Draco ASP constraints.
        use_default_constraints: Use standard heuristics (default: True).

    Returns:
        URL to the generated Vega-Lite spec
    """
    # 0. Generate URL internally
    # Import locally to avoid circular top-level imports if any
    from data360.api import get_data_api_url

    data_url = await get_data_api_url(
        database_id=database_id,
        indicator_id=indicator_id,
        country_code=country_code,
        start_year=start_year,
        end_year=end_year,
        disaggregation_filters=disaggregation_filters,
    )

    # 1. Fetch data
    try:
        data = await _fetch_data_internal(data_url)
    except ValueError as e:
        return f"Error: {e}"
    except httpx.HTTPStatusError as e:
        return f"Error fetching data: {e.response.status_code}"
    except Exception as e:
        _logger.exception("Failed to fetch data")
        return f"Error fetching data: {e}"

    # 2. Clean data - standardize column names to lowercase
    data.columns = [c.lower() for c in data.columns]

    # Clean up dates and numerics
    # Data360 convention: TIME_PERIOD, OBS_VALUE
    if "time_period" in data.columns:
        try:
            # FORCE DATETIME for Draco Schema to see 'datetime'
            # This assumes proper dates. If year-only '2019', to_datetime handles it (default Jan 1)
            data["time_period"] = pd.to_datetime(data["time_period"])
        except (ValueError, TypeError):
            pass

    if "obs_value" in data.columns:
        # TODO: to confirm with viz team on how to populate null values from api
        data["obs_value"] = pd.to_numeric(data["obs_value"], errors="coerce").fillna(0)

    # --- Task #8: Fetch Indicator Name for Title ---
    chart_title = "Generated Visualization"
    try:
        # Extract params from URL
        parsed = urlparse(data_url)
        params = parse_qs(parsed.query)
        db_id = params.get("DATABASE_ID", [None])[0]
        ind_id_param = (
            params.get("indicatorId", [None])[0]
            or params.get("INDICATOR", [None])[0]
            or params.get("indicator", [None])[0]
        )

        if db_id and ind_id_param:
            from data360.api import get_metadata

            meta = await get_metadata(db_id, ind_id_param)
            # Fix: Access name from indicator_metadata dict if present
            if meta and meta.indicator_metadata and "name" in meta.indicator_metadata:
                chart_title = meta.indicator_metadata["name"]
    except Exception as e:
        _logger.warning(f"Could not fetch metadata for title: {e}")

    # 3. Use Draco2 to find optimal visualization
    d = Draco()

    # Determine relevant columns
    if relevant_fields:
        # User/LLM explicitly asked for specific fields
        # Filter to only those that exist in the dataframe
        # Lowercase check
        req_fields = [f.lower() for f in relevant_fields]
        existing_cols = set(data.columns)
        missing_fields = [f for f in req_fields if f not in existing_cols]

        if missing_fields:
            return f"Error: The following requested fields were not found in the data: {missing_fields}. Available columns: {list(data.columns)}"

        valid_cols = req_fields

        # Smart enrichment: If ref_area (country) is in the data but not requested,
        # check if it's needed to distinguish data points (multi-country) and keep it.
        # Also check other breakdown dimensions.
        potential_enrichments = ["ref_area", "sex", "age", "urbanisation"]
        for dim in potential_enrichments:
            if dim in data.columns and dim not in valid_cols:
                # Check if this dimension has multiple values (or is not just "_T")
                unique_vals = data[dim].unique()
                if len(unique_vals) > 1 or (
                    len(unique_vals) == 1 and unique_vals[0] != "_T"
                ):
                    valid_cols.append(dim)
                    _logger.info(f"Auto-enriched relevant_fields with {dim}")

        viz_data = data[valid_cols].copy()
        # Ensure relevant_cols is defined for downstream logic
        relevant_cols = valid_cols
    else:
        # Auto-selection logic
        relevant_cols = []
        if "time_period" in data.columns:
            relevant_cols.append("time_period")
        if "obs_value" in data.columns:
            relevant_cols.append("obs_value")
        if "ref_area" in data.columns:
            relevant_cols.append("ref_area")

        # Breakdowns
        breakdown_dims = ["sex", "age", "urbanisation"]
        for dim in breakdown_dims:
            if dim in data.columns:
                unique_vals = data[dim].unique()
                if len(unique_vals) > 1 or (
                    len(unique_vals) == 1 and unique_vals[0] != "_T"
                ):
                    relevant_cols.append(dim)

        if relevant_cols:
            viz_data = data[relevant_cols].copy()
        else:
            viz_data = data.copy()

    # Create map for renaming (User friendly labels, but lowercase for Draco/ASP safety)
    # Vega-Lite will auto-capitalize these for Axis titles (e.g. "year" -> "Year")
    column_renames = {
        "time_period": "year",
        "obs_value": "value",
        "ref_area": "country",
    }

    # Task #9: Map REF_AREA codes to Names if present
    if "ref_area" in viz_data.columns:
        try:
            from data360.providers import get_codelist_mapping

            country_map = await get_codelist_mapping("REF_AREA")
            # Map codes to names, keep original if not found
            viz_data["ref_area"] = viz_data["ref_area"].map(
                lambda x: country_map.get(x, x)
            )
        except Exception as e:
            _logger.warning(f"Could not map country codes: {e}")

    # Rename columns in dataframe
    viz_data = viz_data.rename(columns=column_renames)

    # Update relevant_cols logic to match new names for Draco check
    # Note: Draco/Altair is case sensitive.

    if viz_data.empty:
        return "Error: No data available for visualization after cleaning."

    try:
        schema = schema_from_dataframe(viz_data)
        facts = dict_to_facts(schema)
    except Exception as e:
        _logger.exception(f"Error generating data schema: {e}")
        return f"Error generating data schema: {e}"

    # Base constraints
    program_constraints = ["entity(view,root,view).", "entity(mark,view,m)."]

    if use_default_constraints:
        # --- EXPLICITLY DEFINE X/Y ROLES FOR DATA360 (UPDATED NAMES) ---
        if "year" in viz_data.columns:
            program_constraints.append("entity(encoding,m,e1).")
            program_constraints.append("attribute((encoding,channel),e1,x).")
            program_constraints.append("attribute((encoding,field),e1,year).")

        if "value" in viz_data.columns:
            program_constraints.append("entity(encoding,m,e2).")
            program_constraints.append("attribute((encoding,channel),e2,y).")
            program_constraints.append("attribute((encoding,field),e2,value).")

        # Constraint for Color/Breakdown
        # We iterate through potential breakdown dims that we found relevant earlier
        # If any are present in viz_data (and not x/y), we map to color
        # We prioritize Country (was ref_area) > sex > others
        color_dim = None
        if "country" in viz_data.columns:  # Was ref_area
            color_dim = "country"
        elif "sex" in viz_data.columns and "sex" in relevant_cols:
            color_dim = "sex"
        elif "age" in viz_data.columns and "age" in relevant_cols:
            color_dim = "age"
        elif "urbanisation" in viz_data.columns and "urbanisation" in relevant_cols:
            color_dim = "urbanisation"

        if color_dim:
            program_constraints.append("entity(encoding,m,e3).")
            program_constraints.append("attribute((encoding,channel),e3,color).")
            program_constraints.append(f"attribute((encoding,field),e3,{color_dim}).")

        # Optional: Apply user chart type hint
        user_mark_type = _parse_chart_type_hint(chart_type)

        if chart_type:
            program_constraints.append(f"attribute((mark,type),m,{user_mark_type}).")

    # Apply Custom Constraints from LLM/Developer
    if custom_constraints:
        _logger.info(f"Applying custom Draco constraints: {custom_constraints}")
        program_constraints.extend(custom_constraints)

    program = "\n".join(facts) + "\n" + "\n".join(program_constraints)

    try:
        # Solve
        model = next(d.complete_spec(program))
        draco_spec = answer_set_to_dict(model.answer_set)

        # RENDER USING STANDARD DRACO RENDERER

        if "view" in draco_spec:
            for view in draco_spec["view"]:
                if "mark" in view:
                    for mark in view["mark"]:
                        if "encoding" in mark:
                            for encoding in mark["encoding"]:
                                encoding.pop("type", None)

        # Merge data schema (stats) with the view spec
        full_spec = {**schema, **draco_spec}

        renderer = AltairRenderer()
        chart = renderer.render(spec=full_spec, data=viz_data)

        # Apply customizations

        # 1. Custom Interactive + Title
        chart = chart.properties(title=chart_title).interactive()

        # 2. Force Rich Tooltips
        tooltip_cols = list(viz_data.columns)
        chart = chart.encode(tooltip=tooltip_cols)

        # 3. Force NOMINAL type for categorical channels (Color) if applicable
        # Draco renderer might infer ordinal, but users prefer nominal for countries etc.
        # We manually patch the encoding if the color field is categorical.
        if color_dim:
            # We can't easily modify the altair object's encoding type in place deeply?
            # Easier to patch the dictionary.
            pass

        vl_spec = chart.to_dict()

        # Manual Patching of Types in the final Spec
        if "encoding" in vl_spec:
            if "color" in vl_spec["encoding"]:
                # If color is used, force nominal if it corresponds to our breakdown dims
                # color_dim var holds the name of the column used for color
                if color_dim in ["country", "sex", "urbanisation", "ref_area"]:
                    vl_spec["encoding"]["color"]["type"] = "nominal"

        # Save
        vega_url = save_specs_to_static(vl_spec)
        return vega_url

    except StopIteration:
        _logger.warning(
            "Draco failed to find a visualization spec. Falling back to manual generation."
        )
        _logger.debug(f"Failed Program:\n{program}")

        # Fallback: Manual Altair Generation
        try:
            fc = list(viz_data.columns)
            base = alt.Chart(viz_data).mark_line().encode(tooltip=fc)

            # Map known columns
            if "year" in fc:
                x_enc = alt.X("year", title="Year")
            elif "time_period" in fc:
                x_enc = alt.X("time_period", title="Year")
            else:
                # Last resort: first column
                x_enc = alt.X(fc[0])

            if "value" in fc:
                y_enc = alt.Y("value", title="Value")
            elif "obs_value" in fc:
                y_enc = alt.Y("obs_value", title="Value")
            else:
                y_enc = alt.Y(fc[1] if len(fc) > 1 else fc[0])

            encoding = {"x": x_enc, "y": y_enc}

            # Add color if breakdown found
            if "country" in fc:
                encoding["color"] = alt.Color(
                    "country", type="nominal", title="Country"
                )
            elif "sex" in fc:
                encoding["color"] = alt.Color("sex", type="nominal", title="Sex")
            elif "age" in fc:
                encoding["color"] = alt.Color("age", type="nominal", title="Age")

            chart = base.encode(**encoding).properties(title=chart_title).interactive()
            vl_spec = chart.to_dict()
            vega_url = save_specs_to_static(vl_spec)
            return vega_url

        except Exception as fallback_err:
            _logger.exception(f"Fallback generation failed: {fallback_err}")
            return "Error: Draco could not determine a suitable visualization, and fallback failed."
    except Exception as e:
        _logger.exception(f"Draco execution error: {e}")
        return f"Error generating visualization: {e}"
