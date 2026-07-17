# Data360 Surprise Me! Chart Explorer — User Guide & Architecture

Welcome to the **Surprise Me! Chart Explorer**. This interactive dashboard is designed to evaluate, compare, and audit the charting capabilities of the **Data360 MCP** visualization engine against a **Direct LLM (Chart.js)** rendering pipeline. 

Eventually, this application can be hosted in **Hugging Face Spaces** for remote reviews and automated visualization quality audits.

---

## 📋 Table of Contents
1. [Core Features & Purpose](#-core-features--purpose)
2. [Interface & Controls Guide](#-interface--controls-guide)
3. [The "Surprise Me!" Workflow](#-the-surprise-me-workflow)
4. [Vision-Based Evaluation (Visual Critique)](#-vision-based-evaluation-visual-critique)
5. [Hugging Face Spaces Deployment Guide](#-hugging-face-spaces-deployment-guide)

---

## 🎯 Core Features & Purpose

The dashboard presents a side-by-side comparison of two visualization pipelines:
1. **Data360 Engine Spec (System)**: Renders interactive charts using the repository's rules-driven, highly optimized Vega-Lite spec builder.
2. **Direct LLM Spec (LLM)**: Renders charts using a raw Chart.js specification generated dynamically by a standard GPT-4o call.

By comparing the two, developers and domain experts can assess how well the system engine enforces proper World Bank Group style guidelines, handles unit boundaries, clusters scaling-compatible variables, and prevents visual compression compared to unconstrained LLM outputs.

---

## 🕹️ Interface & Controls Guide

### Default Welcome State
When you first open the dashboard, you will see the message:
> **No active query. Click "Surprise Me!" or trigger a batch run.**

This indicates that the session has just initialized. The chart viewports are in empty states, the visual critique controls are hidden, and the explorer is waiting for you to either trigger a new random scenario or select a previous run from the **Past Runs** sidebar.

### Sidebar: Past Runs
* **Overview**: Displays a history of generated scenarios. Each card lists the natural language question, the time it was generated, and the pre-computed evaluation scores.
  * **E**: The G-Eval text-based score for the **System Spec View** (out of 10).
  * **L**: The G-Eval text-based score for the **Direct LLM Spec** (out of 10).
* **Click Behavior**: Clicking any card instantly loads the query, renders the interactive charts, shows compilation logs, updates the spec codes, and displays the visual critique (if already cached).

### Button Definitions
* **`Surprise Me!`**: The primary trigger for generating a new random test scenario. (Defined in detail below).
* **`Run Visual Critique` / `Visual Critique (Cached)`**:
  * **Action**: Located next to the active query text. It runs a GPT-4o Vision model to audit the physical screenshots of both rendered charts side-by-side.
  * **Output**: Renders G-Eval audit scores, qualitative rationales, and list recommendations for both panels.
  * **Caching**: Once generated, the critique is saved locally. The button label updates to **`Visual Critique (Cached)`** and future loads render instantly.

### Details Tabs (Bottom Section)
* **Log Console**: A terminal window displaying the step-by-step pipeline execution, including indicator fetching, routing rules triggered, and rendering outcomes.
* **Vega-Lite Specs Comparison**: The raw JSON specification for the Vega-Lite (System) and Chart.js (LLM) renders.
* **Resolved Parameters**: The exact data profile (indicator IDs, time frames, country cardinalities, and disaggregation filters) fetched from the Data360 API.

---

## 🎲 The "Surprise Me!" Workflow

To prevent LLM prompt bias (where the AI always asks for simple time-series line charts), the **Surprise Me!** button uses a randomized parameter-first generation pipeline:

```
[Surprise Me! Click] 
        │
        ▼
[Random Parameter Generation] ──► Indicator Count (1 to 3)
        │                     ──► Country Cardinality (1 to 5)
        │                     ──► Start & End Years
        │                     ──► Disaggregations (Sex, Age, Urbanisation)
        │                     ──► Custom Breakdown Dimensions
        ▼
[Data360 MCP Schema Validation] (Verifies breakdown codes exist)
        │
        ▼
[GPT-4o Question Framing] (Generates natural language query matching parameters)
        │
        ▼
[Dual Pipeline Execution] ──► System Engine (Vega-Lite Spec)
                          ──► Direct LLM (Chart.js Config)
```

This ensures that the visualization routing is tested against complex, arbitrary scenarios (e.g., single-year multi-indicator bar charts, multi-indicator small multiples, percentage-clamped population pyramids, etc.).

---

## 👁️ Vision-Based Evaluation (Visual Critique)

While text-based G-Eval metrics evaluate the structural correctness of the generated JSON code, they cannot detect visual layout bugs (e.g., overlapping labels, clipped legends, poor contrast, flatlined scales, or crowded axes). 

The **Visual Critique** button fills this gap:
1. When a scenario renders, the dashboard captures high-fidelity screenshots of both chart viewports as PNGs and uploads them to the server.
2. Clicking the critique button sends both PNGs to GPT-4o Vision alongside the system's design guidelines (contrast, label placement, grouping, layout).
3. The scorer returns a numerical score and bulleted improvements. Both results render under their respective cards for direct quality comparison.

---

## 🚀 Hugging Face Spaces Deployment Guide

To deploy the Surprise Me! Chart Explorer on Hugging Face Spaces:

### 1. Create a New Space
1. Log in to [Hugging Face](https://huggingface.co/).
2. Click **New Space**.
3. Name your space (e.g., `data360-chart-explorer`).
4. Select **Docker** as the SDK.
5. Choose the **Blank** template.

### 2. Prepare the Dockerfile
Create a `Dockerfile` in the root of your repository to containerize the dashboard:

```dockerfile
FROM python:3.11-slim

# Install system dependencies (needed for browser screenshot captures)
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency configs
COPY pyproject.toml uv.lock ./

# Install python dependencies
RUN uv sync --frozen --no-dev

# Install playwright browsers (for chart screenshot captures)
RUN uv run playwright install chromium

# Copy project source code
COPY . .

# Expose the dashboard port
EXPOSE 7860

# Run the interactive explorer on port 7860
CMD ["uv", "run", "python", "evals/interactive_explorer.py", "--port", "7860"]
```

### 3. Add Secrets & Environment Variables
In your Hugging Face Space settings, add the following variables under **Repository secrets**:
* `OPENAI_API_KEY`: Required for the question-framing LLM and GPT-4o Vision critique audits.
* `PREFAB_BUNDLED_RENDERER`: Set to `1`.

### 4. Push Code to Spaces Git
Initialize git, add the Hugging Face space remote, and push:
```bash
git remote add space https://huggingface.co/spaces/<your-username>/<space-name>
git add .
git commit -m "Deploy chart explorer to Hugging Face Spaces"
git push space main
```

Your space will build and launch automatically, making the Surprise Me Explorer accessible via a public web URL.
