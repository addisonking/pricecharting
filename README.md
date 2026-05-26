# pricecharting

unofficial scraper + rest api + mcp server for pricecharting.com

## install

```bash
pip install -r requirements.txt
```

## rest api

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

- `GET /game/{slug}` — prices + recent sales
- `GET /search?q=...` — search by title

## mcp server (lm studio)

add a stdio server in lm studio settings:

- **command**: `/path/to/repo/run_mcp.sh`
- **args**: *(empty)*

### tools

- `search_games(query)` — search by title
- `get_game_prices(slug)` — current prices + volume
- `get_game_sales(slug, condition, limit=5)` — recent sales for one condition
