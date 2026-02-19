"""
Visualization Configuration Module

This module centralizes all hardcoded rules, constraints, and mappings
for the Data360 visualization system. This makes the codebase more maintainable,
testable, and easier to modify without touching core logic.
"""

from dataclasses import dataclass
from typing import Literal
import pandas as pd


# ============================================================================
# FREQUENCY MAPPINGS
# ============================================================================

# Map Data360 frequency codes to Vega-Lite timeUnit values
FREQUENCY_TO_TIMEUNIT: dict[str, str] = {
    "A": "year",        # Annual: displays as 2012, 2013, 2014, ...
    "M": "yearmonth",   # Monthly: displays as Jan 2012, Feb 2012, ...
    "Q": "yearquarter", # Quarterly: displays as Q1 2012, Q2 2012, ...
}

# Keywords for inferring frequency from periodicity text (fallback)
PERIODICITY_KEYWORDS: dict[str, list[str]] = {
    "A": ["annual", "yearly"],
    "M": ["month", "monthly"],
    "Q": ["quarter", "quarterly"],
}


# ============================================================================
# CHART TYPE MAPPINGS
# ============================================================================

# Map user-friendly chart type hints to Vega-Lite mark types
CHART_TYPE_KEYWORDS: dict[str, list[str]] = {
    "line": ["line", "trend", "time series"],
    "bar": ["bar", "column", "histogram"],
    "point": ["scatter", "point", "dot"],
    "area": ["area", "filled"],
    "tick": ["tick"],
}

DEFAULT_CHART_TYPE: str = "line"  # Default for time series data


# ============================================================================
# DATA PREPARATION RULES
# ============================================================================

@dataclass
class DataPreparationRule:
    """Rule for how to prepare temporal data based on chart type and frequency."""

    chart_type: str
    frequency: str | None
    action: Literal["year_strings", "datetime"]
    description: str


# Rules are evaluated in order; first match wins
DATA_PREPARATION_RULES: list[DataPreparationRule] = [
    DataPreparationRule(
        chart_type="bar",
        frequency="A",
        action="year_strings",
        description="Bar charts with annual data use year strings for discrete display"
    ),
    # Default: all other cases use datetime
    DataPreparationRule(
        chart_type="*",  # Wildcard
        frequency="*",   # Wildcard
        action="datetime",
        description="Default: use datetime for temporal encoding"
    ),
]


# ============================================================================
# POST-PROCESSING RULES
# ============================================================================

@dataclass
class PostProcessingRule:
    """Rule for post-processing Vega-Lite specs after Draco generation."""

    name: str
    applies_to_mark_types: list[str]
    description: str

    def should_apply(self, mark_type: str, encoding: dict, data: dict) -> bool:
        """Override in subclasses to determine if rule should apply."""
        raise NotImplementedError

    def apply(self, spec: dict, data_frequency: str | None = None) -> dict:
        """Override in subclasses to apply the transformation."""
        raise NotImplementedError


class OrdinalToTemporalRule(PostProcessingRule):
    """Convert ordinal x-axis to temporal for non-bar charts with datetime data."""

    def __init__(self):
        super().__init__(
            name="ordinal_to_temporal",
            applies_to_mark_types=["line", "area", "point", "tick"],
            description="Fix Draco's preference for ordinal on stacked charts"
        )

    def should_apply(self, mark_type: str, x_encoding: dict, dataset: list[dict]) -> bool:
        """Check if we should convert ordinal to temporal."""
        if mark_type not in self.applies_to_mark_types:
            return False

        if x_encoding.get("type") != "ordinal":
            return False

        x_field = x_encoding.get("field")
        if x_field not in ["year", "time_period"]:
            return False

        # Check if data has datetime values
        if dataset and x_field in dataset[0]:
            sample_value = dataset[0][x_field]
            # Datetime strings contain "T"
            return isinstance(sample_value, str) and "T" in sample_value

        return False

    def apply(self, spec: dict, data_frequency: str | None = None) -> dict:
        """Apply the ordinal->temporal conversion."""
        mark_type = spec.get("mark", {}).get("type") if isinstance(spec.get("mark"), dict) else spec.get("mark")

        if "encoding" not in spec or "x" not in spec["encoding"]:
            return spec

        x_enc = spec["encoding"]["x"]

        # Get dataset
        dataset_name = spec.get("data", {}).get("name")
        if not dataset_name or "datasets" not in spec:
            return spec

        dataset = spec["datasets"].get(dataset_name, [])

        if self.should_apply(mark_type, x_enc, dataset):
            x_enc["type"] = "temporal"

        return spec


class ApplyTimeUnitRule(PostProcessingRule):
    """Apply frequency-aware timeUnit to temporal encodings."""

    def __init__(self):
        super().__init__(
            name="apply_timeunit",
            applies_to_mark_types=["line", "area", "point", "tick"],
            description="Add timeUnit based on data frequency"
        )

    def should_apply(self, x_encoding: dict, data_frequency: str | None) -> bool:
        """Check if we should apply timeUnit."""
        return (
            data_frequency is not None
            and data_frequency in FREQUENCY_TO_TIMEUNIT
            and x_encoding.get("type") == "temporal"
        )

    def apply(self, spec: dict, data_frequency: str | None = None) -> dict:
        """Apply timeUnit to x-axis encoding."""
        if "encoding" not in spec or "x" not in spec["encoding"]:
            return spec

        x_enc = spec["encoding"]["x"]

        if self.should_apply(x_enc, data_frequency):
            x_enc["timeUnit"] = FREQUENCY_TO_TIMEUNIT[data_frequency]

        return spec


class FixPointChartEncodingsRule(PostProcessingRule):
    """Fix common Draco issues with point charts (ordinal y-axis, meaningless size)."""

    def __init__(self):
        super().__init__(
            name="fix_point_chart_encodings",
            applies_to_mark_types=["point"],
            description="Fix ordinal y-axis and remove meaningless size encodings"
        )

    def should_apply(self, spec: dict, data_frequency: str | None = None) -> bool:
        """Apply to point charts."""
        mark_type = spec.get("mark", {}).get("type") if isinstance(spec.get("mark"), dict) else spec.get("mark")
        return mark_type == "point"

    def apply(self, spec: dict, data_frequency: str | None = None) -> dict:
        """Fix point chart encoding issues."""
        if not self.should_apply(spec, data_frequency):
            return spec

        if "encoding" not in spec:
            return spec

        # Fix 1: Convert ordinal y-axis to quantitative if field is 'value'
        if "y" in spec["encoding"]:
            y_enc = spec["encoding"]["y"]
            if y_enc.get("type") == "ordinal" and y_enc.get("field") == "value":
                y_enc["type"] = "quantitative"
                # Ensure proper scale
                if "scale" not in y_enc:
                    y_enc["scale"] = {"type": "linear", "zero": True}

        # Fix 2: Remove meaningless size:count encoding
        # (This happens when Draco can't find a good size mapping)
        if "size" in spec["encoding"]:
            size_enc = spec["encoding"]["size"]
            # If size is just aggregate count with no field, remove it
            if size_enc.get("aggregate") == "count" and "field" not in size_enc:
                del spec["encoding"]["size"]

        return spec


# Registry of post-processing rules (applied in order)
POST_PROCESSING_RULES: list[PostProcessingRule] = [
    OrdinalToTemporalRule(),
    ApplyTimeUnitRule(),
    FixPointChartEncodingsRule(),
]



# ============================================================================
# DRACO CONSTRAINT CONFIGURATION
# ============================================================================

@dataclass
class DracoConstraintConfig:
    """Configuration for Draco constraint generation."""

    # Base constraints always applied
    base_constraints: list[str]

    # Fields that should be mapped to nominal color encoding
    nominal_color_fields: list[str]

    # Priority order for color dimension selection
    color_dimension_priority: list[str]

    def __init__(self):
        self.base_constraints = [
            "entity(view,root,view).",
            "entity(mark,view,m).",
        ]

        self.nominal_color_fields = [
            "country",
            "sex",
            "urbanisation",
            "ref_area",
        ]

        self.color_dimension_priority = [
            "country",
            "sex",
            "age",
            "urbanisation",
        ]


# Default configuration instance
DEFAULT_DRACO_CONFIG = DracoConstraintConfig()


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def parse_chart_type_hint(chart_type: str | None) -> str:
    """
    Parse user's chart type hint into Vega-Lite mark type.

    Args:
        chart_type: User's hint like "line chart", "bar", "scatter", etc.

    Returns:
        Vega-Lite mark type, defaults to DEFAULT_CHART_TYPE
    """
    if not chart_type:
        return DEFAULT_CHART_TYPE

    hint = chart_type.lower().strip()

    for mark_type, keywords in CHART_TYPE_KEYWORDS.items():
        if any(keyword in hint for keyword in keywords):
            return mark_type

    return DEFAULT_CHART_TYPE


def get_data_preparation_action(chart_type: str, frequency: str | None) -> Literal["year_strings", "datetime"]:
    """
    Determine how to prepare temporal data based on chart type and frequency.

    Args:
        chart_type: Vega-Lite mark type (line, bar, area, etc.)
        frequency: Data frequency code (A, M, Q, etc.)

    Returns:
        Action to take: "year_strings" or "datetime"
    """
    for rule in DATA_PREPARATION_RULES:
        # Check if rule matches
        type_match = rule.chart_type == "*" or rule.chart_type == chart_type
        freq_match = rule.frequency == "*" or rule.frequency == frequency

        if type_match and freq_match:
            return rule.action

    # Fallback (should never reach here with current rules)
    return "datetime"


def infer_frequency_from_periodicity(periodicity: str) -> str | None:
    """
    Infer frequency code from periodicity text (fallback method).

    Args:
        periodicity: Periodicity text from metadata

    Returns:
        Frequency code (A, M, Q) or None
    """
    periodicity_lower = periodicity.lower()

    for freq_code, keywords in PERIODICITY_KEYWORDS.items():
        if any(keyword in periodicity_lower for keyword in keywords):
            return freq_code

    return None


def should_prepare_as_datetime(viz_data: pd.DataFrame, chart_type: str, frequency: str | None) -> bool:
    """
    Determine if time_period column should be prepared as datetime vs year strings.

    Args:
        viz_data: Visualization dataframe
        chart_type: Vega-Lite mark type
        frequency: Data frequency code

    Returns:
        True if should convert to datetime, False if should convert to year strings
    """
    action = get_data_preparation_action(chart_type, frequency)
    return action == "datetime"


# ============================================================================
# SMART AXIS SELECTION
# ============================================================================

def should_use_temporal_x_axis(
    viz_data: pd.DataFrame,
    chart_type: str | None,
    available_dimensions: list[str]
) -> tuple[bool, str | None]:
    """
    Determine if x-axis should use temporal (year) or categorical dimension.

    This enables cross-sectional comparisons (single year, multiple countries)
    while maintaining backward compatibility with time-series visualizations.

    Args:
        viz_data: Visualization dataframe
        chart_type: Vega-Lite mark type (line, bar, point, tick, area)
        available_dimensions: List of available column names

    Returns:
        Tuple of (use_temporal, categorical_field_suggestion)
        - use_temporal: True if year should be on x-axis
        - categorical_field_suggestion: Suggested categorical field if not temporal

    Examples:
        >>> # Multi-year time series
        >>> should_use_temporal_x_axis(df_2020_2024, "line", ["year", "country", "value"])
        (True, None)

        >>> # Single year, multiple countries
        >>> should_use_temporal_x_axis(df_2024_only, "bar", ["year", "country", "value"])
        (False, "country")

        >>> # Tick chart with single year
        >>> should_use_temporal_x_axis(df_2024_only, "tick", ["year", "country", "value"])
        (False, "country")
    """

    # If no year column, can't use temporal
    if "year" not in available_dimensions:
        # Try to find a good categorical dimension
        return False, _select_categorical_dimension(available_dimensions)

    # Check year cardinality
    year_unique_count = viz_data["year"].nunique() if "year" in viz_data.columns else 0

    # Multiple years → strong signal for time series
    if year_unique_count > 1:
        return True, None

    # Single year → consider alternatives based on chart type and available dimensions

    # Parse chart type
    mark_type = parse_chart_type_hint(chart_type) if chart_type else "line"

    # Chart type preferences
    # line/area: Strongly prefer temporal (even with single year, might want to show trend)
    # bar: Context-dependent (could be temporal or categorical)
    # point: Flexible (works well with both)
    # tick: Strongly prefer categorical (designed for distribution)

    categorical_preference_by_type = {
        "tick": 1.0,     # Strong preference for categorical
        "point": 0.7,    # Moderate preference for categorical
        "bar": 0.5,      # Neutral
        "line": 0.2,     # Weak preference for categorical
        "area": 0.1,     # Very weak preference for categorical
    }

    categorical_score = categorical_preference_by_type.get(mark_type, 0.5)

    # Check if we have good categorical dimensions
    categorical_field = _select_categorical_dimension(available_dimensions)

    if categorical_field is None:
        # No categorical dimension available, stick with year
        return True, None

    # If we have a categorical dimension with decent cardinality and chart type suggests it
    if categorical_score >= 0.5:
        # Prefer categorical
        return False, categorical_field

    # Default to temporal for line/area charts
    return True, None


def _select_categorical_dimension(available_dimensions: list[str]) -> str | None:
    """
    Select the most appropriate categorical dimension for x-axis.

    Priority order: country > sex > age > urbanisation > other

    Args:
        available_dimensions: List of available column names

    Returns:
        Selected categorical field or None
    """
    # Priority order for categorical dimensions
    priority_order = ["country", "sex", "age", "urbanisation", "education", "income_group"]

    for dim in priority_order:
        if dim in available_dimensions:
            return dim

    # Fallback: any non-value, non-year column
    for dim in available_dimensions:
        if dim not in ["year", "value", "time_period", "obs_value"]:
            return dim

    return None
