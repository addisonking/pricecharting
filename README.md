# pricecharting

unofficial scraper + rest api + mcp server for pricecharting.com  
works for games, consoles, and hardware

## install

```bash
pip install -r requirements.txt
```

## caching

caching works out of the box with a local SQLite database (`cache.db`). no config needed.

- default cache TTL: 1 hour (3600s)
- search results cached for 5 minutes
- all API responses include `cached: true` when served from cache

### turso (optional)

for a persistent remote cache, create a `.env`:

```bash
cp .env.example .env
# fill in your Turso DB URL and token from https://docs.turso.tech
```

### disable cache

set `DISABLE_CACHE=1` in your environment to fetch fresh data every request.

## rest api

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

- `GET /game/{slug}` — prices + recent sales for games, consoles, or hardware
  - response includes `cached: true` when served from cache
- `GET /search?q=...` — search by title

## mcp server (lm studio)

add a stdio server in lm studio settings:

- **command**: `/path/to/repo/run_mcp.sh`
- **args**: *(empty)*

### tools

- `search_products(query)` — search games, consoles, or hardware by title
- `get_product_prices(slug)` — current prices + volume
- `get_product_sales(slug, condition, limit=5)` — recent sales for one condition
