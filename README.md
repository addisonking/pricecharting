# Unofficial PriceCharting API

Scrapes [pricecharting.com](https://www.pricecharting.com) and exposes it as a FastAPI REST API and an MCP server for LM Studio / Claude Desktop.

## Install

```bash
pip install -r requirements.txt
```

## FastAPI Server

```bash
python3 -m uvicorn api:app --host 0.0.0.0 --port 8000
```

### Endpoints

- `GET /game/{slug}` — get full price data and recent sales  
  Example: `/game/nintendo-3ds/super-smash-bros-for-nintendo-3ds`

- `GET /search?q={query}` — search for games  
  Example: `/search?q=super+smash+bros+3ds`

Optional `cookie` query param on both endpoints if you need to pass session cookies.

## MCP Server (LM Studio)

```bash
python3 /full/path/to/pricecharting/mcp_server.py
```

In **LM Studio** go to `Settings -> MCP Servers` and add a new stdio server:

- **Command**: `python3`
- **Arguments**: `/full/path/to/pricecharting/mcp_server.py`

### Tools

- `search_games(query)` — search by title, returns slugs + current prices
- `get_game_details(slug)` — full data for a game including recent eBay sales

## Notes

- This is an unofficial scraper. The site may change and break things.
- No cookies are required for basic read-only data.
- Prices are in USD. Historical chart data is embedded in `chart_data` (cents, monthly averages).
