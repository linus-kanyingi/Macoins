"""chat/tools_schema.py — Anthropic tool-use schema for Claude trading assistant."""

TOOLS = [
    {
        "name": "run_analysis",
        "description": "Run a multi-agent debate analysis on a stock. Use when the user wants to analyze, get a recommendation, or decide whether to buy/sell/hold a stock.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker":         {"type": "string",  "description": "Stock ticker e.g. AAPL, TSLA"},
                "rounds":         {"type": "integer", "description": "Debate rounds 1-3", "default": 1},
                "include_hold":   {"type": "boolean", "default": False},
                "auto_execute":   {"type": "boolean", "description": "Execute if confidence is high", "default": False},
                "skip_judges":    {"type": "boolean", "default": False},
                "skip_factcheck": {"type": "boolean", "default": False},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_portfolio",
        "description": "Get current portfolio: positions, P&L, and account equity.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_account",
        "description": "Get account balance, buying power, and cash.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "place_order",
        "description": "Place a buy or sell order for a stock.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker":      {"type": "string"},
                "side":        {"type": "string", "enum": ["buy", "sell"]},
                "qty":         {"type": "integer"},
                "order_type":  {"type": "string", "enum": ["market", "limit"], "default": "market"},
                "limit_price": {"type": "number"},
            },
            "required": ["ticker", "side", "qty"],
        },
    },
    {
        "name": "cancel_order",
        "description": "Cancel an open order by order ID.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "cancel_all_orders",
        "description": "Cancel ALL open orders immediately.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_quote",
        "description": "Get the latest price for a stock ticker.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_orders",
        "description": "Get recent order history.",
        "input_schema": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["open", "closed", "all"], "default": "all"}},
        },
    },
    {
        "name": "get_analysis_history",
        "description": "Get past debate analyses and their verdicts.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10}},
        },
    },
    {
        "name": "get_market_status",
        "description": "Check if the US stock market is currently open or closed.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "emergency_stop",
        "description": "EMERGENCY: Close all positions in a specific ticker immediately.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "Ticker to flatten"}},
            "required": ["ticker"],
        },
    },
]

def get_anthropic_tools() -> list:
    """Return tools in Anthropic's native format."""
    return TOOLS

def get_openai_tools() -> list:
    """Convert Anthropic tool schema to OpenAI/Ollama native format."""
    openai_tools = []
    for tool in TOOLS:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            }
        })
    return openai_tools

def get_gemini_tools() -> list:
    """Convert Anthropic tool schema to Gemini native format."""
    gemini_funcs = []
    for tool in TOOLS:
        gemini_funcs.append({
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        })
    return [{"function_declarations": gemini_funcs}]
