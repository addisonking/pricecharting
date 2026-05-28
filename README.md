# pricecharting

unofficial scraper + rest api + mcp server for pricecharting.com  
works for games, consoles, and hardware

## install

```bash
pip install -r requirements.txt
```

## config (optional)

create a `.env` file for Turso caching:

```bash
cp .env.example .env
# edit .env with your Turso DB URL and token
```

get your Turso credentials from https://docs.turso.tech

cache is optional — without config, data is fetched fresh each request. with Turso configured:

- default cache TTL: 1 hour (3600s)
- search results cached for 5 minutes
- requests are served instantly from cache when possible

all API responses include a `cached` field:
```json
{
  "name": "Super Smash Bros for Nintendo 3DS",
  "cached": true,
  "loose": {"price": 12.99, ...}
}
```

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
