# Data360 MCP Library

Abstraction of MCP specs for Data360 that can be used to build MCP servers or clients.

## Semantic Data Layer

The semantic data layer is a collection of implementations that transforms the data model of Data360 into forms that are closer to use cases that address real-world information needs.

## MCP Spec Support

### Tools

The following tools can be used to interact with the Data360 MCP:

| Tool | Description |
|------|-------------|
| `search` | Search for data360 indicators using the Data360 MCP. |
| `get_metadata` | Get the metadata for a data360 indicator using the Data360 MCP. |
| `get_data` | Get the data for a data360 indicator using the Data360 MCP. |

Note that as [best practices](https://github.com/anthropics/skills/blob/main/skills/mcp-builder/reference/mcp_best_practices.md), tools should be prefixed with the name of the MCP server. In this case, the MCP server is called "data360".

Therefore, exposing the above tools as MCP tools should be called `data360_search`, `data360_get_metadata`, and `data360_get_data` respectively.

### Resources

Under development.

### Prompts

Under development.


## Installation

```bash
pip install data360-mcp
```

## Usage

```python
from data360_mcp import Data360MCP

mcp = Data360MCP()
```