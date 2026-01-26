"""
Visualization generation for Data360 data.

This module fetches data from a Data360 API URL and generates
Vega-Lite visualization specifications optimized for the data structure.
"""

import json
import logging
import os
import uuid
from typing import Any
from urllib.parse import urlparse, parse_qs

import httpx
import pandas as pd
from draco import Draco, dict_to_facts, schema_from_dataframe, answer_set_to_dict

_logger = logging.getLogger(__name__)


def save_specs_to_static(vl_spec: dict) -> str:
    """Save Vega-Lite spec to static/specs/ directory.
    
    Returns:
        URL for the saved spec
    """
    spec_id = str(uuid.uuid4())
    specs_dir = os.path.join(os.getcwd(), "static", "specs")
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
    base_url = "http://localhost:8021/static/specs"
    return f"{base_url}/{spec_id}_vega.json"


def _parse_chart_type_hint(chart_type: str | None) -> str:
    """Parse user's chart type hint into Vega-Lite mark type.
    
    Args:
        chart_type: User's hint like "line chart", "bar", "scatter", etc.
        
    Returns:
        Vega-Lite mark type, defaults to 'line' for time series data
    """
    if not chart_type:
        return 'line'  # Default to line for time series
    
    hint = chart_type.lower().strip()
    
    # Map common terms to Vega-Lite mark types
    if any(x in hint for x in ['line', 'trend', 'time series']):
        return 'line'
    elif any(x in hint for x in ['bar', 'column', 'histogram']):
        return 'bar'
    elif any(x in hint for x in ['scatter', 'point', 'dot']):
        return 'point'
    elif any(x in hint for x in ['area', 'filled']):
        return 'area'
    elif any(x in hint for x in ['tick']):
        return 'tick'
    
    return 'line'  # Default


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


def _draco_spec_to_vegalite(draco_spec: dict, data_records: list[dict], title: str) -> dict:
    """Transform Draco ASP output to a full Vega-Lite specification."""
    try:
        view = draco_spec['view'][0]
        mark_entry = view.get('mark', [{'type': 'point'}])[0]
        mark_type = mark_entry.get('type', 'point')
        
        encoding = {}
        if 'encoding' in mark_entry:
            for enc in mark_entry['encoding']:
                channel = enc.get('channel')
                field = enc.get('field')
                aggregate = enc.get('aggregate')
                binning = enc.get('binning')
                # IMPORTANT: Extract 'type' if Draco output it
                enc_type = enc.get('type')
                
                if channel:
                    enc_def = {}
                    if field:
                        enc_def['field'] = field
                        enc_def['title'] = field.replace('_', ' ').title()
                        
                        # Apply Type Inference if missing from Draco
                        if not enc_type:
                            if field == 'time_period' or 'date' in field:
                                enc_type = 'temporal'
                            elif field == 'obs_value' or 'value' in field or 'gdp' in field:
                                enc_type = 'quantitative'
                            else:
                                enc_type = 'nominal'
                    
                    if enc_type:
                        enc_def['type'] = enc_type
                    
                    if aggregate:
                        enc_def['aggregate'] = aggregate
                        
                    if binning:
                        enc_def['bin'] = True
                        
                    encoding[channel] = enc_def

        # --- Task #7: Add Interactivity ---
        # 1. Tooltips (if not already present via Draco)
        if 'tooltip' not in encoding:
             # Basic Tooltip with all encoded fields
             tooltip_fields = []
             for channel, dfn in encoding.items():
                 if 'field' in dfn:
                     tooltip_fields.append({"field": dfn['field'], "title": dfn.get('title', dfn['field']), "type": dfn.get('type')})
             if tooltip_fields:
                encoding['tooltip'] = tooltip_fields

        spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
            "title": title,
            "data": {"values": data_records},
            # Enable default tooltips on mark
            "mark": {"type": mark_type, "tooltip": True}, 
            "encoding": encoding,
            # 2. Zoom/Pan
            "params": [{
                "name": "grid",
                "select": "interval",
                "bind": "scales"
            }]
        }
        return spec
        
    except (KeyError, IndexError) as e:
        _logger.error(f"Error parsing Draco spec: {e}")
        # Fallback basic spec if parsing fails
        return {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "title": title,
            "data": {"values": data_records},
            "mark": "bar",
            "encoding": {}
        }


async def get_viz_spec(
    database_id: str,
    indicator_id: str,
    country_code: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    disaggregation_filters: dict[str, str | None] | None = None,
    chart_type: str | None = None,
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
        disaggregation_filters=disaggregation_filters
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
    if 'time_period' in data.columns:
        try:
             # FORCE DATETIME for Draco Schema to see 'datetime'
             # This assumes proper dates. If year-only '2019', to_datetime handles it (default Jan 1)
             data['time_period'] = pd.to_datetime(data['time_period'])
        except (ValueError, TypeError):
             pass

    if 'obs_value' in data.columns:
        # TODO: to confirm with viz team on how to populate null values from api
         data['obs_value'] = pd.to_numeric(data['obs_value'], errors='coerce').fillna(0)
    
    # --- Task #8: Fetch Indicator Name for Title ---
    chart_title = "Generated Visualization"
    try:
        # Extract params from URL
        parsed = urlparse(data_url)
        params = parse_qs(parsed.query)
        db_id = params.get('DATABASE_ID', [None])[0]
        ind_id_param = (
            params.get('indicatorId', [None])[0] or 
            params.get('INDICATOR', [None])[0] or 
            params.get('indicator', [None])[0]
        )
        
        if db_id and ind_id_param:
            from data360.api import get_metadata
            meta = await get_metadata(db_id, ind_id_param)
            # Fix: Access name from indicator_metadata dict if present
            if meta and meta.indicator_metadata and 'name' in meta.indicator_metadata:
                chart_title = meta.indicator_metadata['name']
    except Exception as e:
        _logger.warning(f"Could not fetch metadata for title: {e}")

    # 3. Use Draco2 to find optimal visualization
    d = Draco()
    
    # We need to ensure Draco picks the right columns 
    relevant_cols = []
    if 'time_period' in data.columns: relevant_cols.append('time_period')
    if 'obs_value' in data.columns: relevant_cols.append('obs_value')
    if 'ref_area' in data.columns: relevant_cols.append('ref_area') 
    
    # Breakdowns
    breakdown_dims = ['sex', 'age', 'urbanisation']
    for dim in breakdown_dims:
        if dim in data.columns:
            unique_vals = data[dim].unique()
            if len(unique_vals) > 1 or (len(unique_vals) == 1 and unique_vals[0] != '_T'):
                relevant_cols.append(dim)
    
    if relevant_cols:
        viz_data = data[relevant_cols].copy()
    else:
        viz_data = data.copy()
        
    viz_data = viz_data.dropna()
    
    if viz_data.empty:
        return "Error: No data available for visualization after cleaning."

    try:
        schema = schema_from_dataframe(viz_data)
        facts = dict_to_facts(schema)
    except Exception as e:
        _logger.exception(f"Error generating data schema: {e}")
        return f"Error generating data schema: {e}"

    # Base constraints
    program_constraints = [
        "entity(view,root,view).",
        "entity(mark,view,m)."
    ]
    
    if use_default_constraints:
        # --- EXPLICITLY DEFINE X/Y ROLES FOR DATA360 ---
        if 'time_period' in viz_data.columns:
            program_constraints.append("entity(encoding,m,e1).")
            program_constraints.append("attribute((encoding,channel),e1,x).")
            program_constraints.append("attribute((encoding,field),e1,time_period).")
            
        if 'obs_value' in viz_data.columns:
            program_constraints.append("entity(encoding,m,e2).")
            program_constraints.append("attribute((encoding,channel),e2,y).")
            program_constraints.append("attribute((encoding,field),e2,obs_value).")

        # Constraint for Color/Breakdown
        # We iterate through potential breakdown dims that we found relevant earlier
        # If any are present in viz_data (and not x/y), we map to color
        # We prioritize ref_area > sex > others
        color_dim = None
        if 'ref_area' in viz_data.columns and 'ref_area' in relevant_cols:
            color_dim = 'ref_area'
        elif 'sex' in viz_data.columns and 'sex' in relevant_cols:
            color_dim = 'sex'
        elif 'age' in viz_data.columns and 'age' in relevant_cols:
             color_dim = 'age'
        elif 'urbanisation' in viz_data.columns and 'urbanisation' in relevant_cols:
             color_dim = 'urbanisation'
             
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
        
        # Safe data serialization: use pandas to_json to handle Timestamps/NumPy types, then load back
        # Use iso format for dates so Vega-Lite can parse them
        data_records = json.loads(viz_data.to_json(orient="records", date_format="iso"))

        # Transform to Vega-Lite
        vl_spec = _draco_spec_to_vegalite(
            draco_spec, 
            data_records, 
            chart_title
        )
        
        # Save
        vega_url = save_specs_to_static(vl_spec)
        return vega_url
        
    except StopIteration:
        _logger.warning("Draco failed to find a visualization spec.")
        return "Error: Draco could not determine a suitable visualization for this data."
    except Exception as e:
        _logger.exception(f"Draco execution error: {e}")
        return f"Error generating visualization: {e}"
