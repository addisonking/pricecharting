#!/usr/bin/env python3
"""stdio MCP server for PriceCharting."""

import sys
import json
import traceback
import asyncio
from concurrent.futures import ThreadPoolExecutor

from scraper import get_game
import httpx
from bs4 import BeautifulSoup
from scraper import _headers

MAX_CONCURRENT = 3
_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT)

BASE = "https://www.pricecharting.com"


VALID_CONDITIONS = {
    "loose", "complete", "new", "graded", "box_only", "manual_only"
}


def _search(query: str) -> list:
    with httpx.Client(headers=_headers(), follow_redirects=True, timeout=20) as client:
        r = client.get(
            f"{BASE}/search-products",
            params={"type": "prices", "q": query, "go": "Go"},
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    return _parse_search_results(soup)


def _parse_search_results(soup) -> list:
    results = []
    for tr in soup.select("#search-results tbody tr"):
        title_a = tr.select_one("td.title a")
        used = tr.select_one("td.used_price span.js-price")
        cib = tr.select_one("td.cib_price span.js-price")
        new = tr.select_one("td.new_price span.js-price")
        if not title_a:
            continue
        href = title_a.get("href", "")
        slug = href.split("/game/", 1)[1] if "/game/" in href else ""
        results.append({
            "name": title_a.get_text(strip=True),
            "slug": slug,
            "loose": used.get_text(strip=True) if used else None,
            "complete": cib.get_text(strip=True) if cib else None,
            "new": new.get_text(strip=True) if new else None,
        })
    return results


async def _search_async(query: str, sem: asyncio.Semaphore) -> dict:
    async with sem:
        async with httpx.AsyncClient(headers=_headers(), follow_redirects=True, timeout=20) as client:
            r = await client.get(
                f"{BASE}/search-products",
                params={"type": "prices", "q": query, "go": "Go"},
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
        return {"query": query, "results": _parse_search_results(soup)}


async def _get_game_async(slug: str, sem: asyncio.Semaphore) -> dict:
    async with sem:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(_executor, get_game, slug)
    return {"slug": slug, **{"name": data.name, "console": data.console, "prices": _compact_prices(data)["prices"]}}


def _compact_prices(data):
    def pp(p):
        if p is None:
            return None
        return {"price": p.price, "change": p.change, "volume": p.volume}
    return {
        "name": data.name,
        "console": data.console,
        "slug": data.slug,
        "prices": {
            "loose": pp(data.loose),
            "complete": pp(data.complete),
            "new": pp(data.new),
            "graded": pp(data.graded),
            "box_only": pp(data.box_only),
            "manual_only": pp(data.manual_only),
        },
    }


def _compact_sales(data, condition: str, limit: int):
    if condition not in VALID_CONDITIONS:
        return {"error": f"invalid condition: {condition}. use: {', '.join(sorted(VALID_CONDITIONS))}"}
    sales = (data.recent_sales or {}).get(condition, [])
    return {
        "condition": condition,
        "name": data.name,
        "sales": [
            {"date": s.date, "price": s.price, "title": s.title}
            for s in sales[:limit]
        ],
    }


TOOLS = [
    {
        "name": "search_products",
        "description": "Search PriceCharting for games, consoles, or hardware by title. Returns name, slug, and current prices.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Game title to search for",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_product_prices",
        "description": "Get current prices and sales volume for a game, console, or hardware item. Use the slug from search_products.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "PriceCharting product slug, e.g. 'nintendo-3ds/super-smash-bros-for-nintendo-3ds' or 'nintendo-3ds/new-nintendo-3ds-xl-black'",
                },
            },
            "required": ["slug"],
        },
    },
    {
        "name": "get_product_sales",
        "description": "Get recent completed sales for a specific condition. Use the slug from search_products.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "PriceCharting product slug",
                },
                "condition": {
                    "type": "string",
                    "description": "Which condition to fetch sales for",
                    "enum": ["loose", "complete", "new", "graded", "box_only", "manual_only"],
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of sales to return (default 5)",
                    "default": 5,
                },
            },
            "required": ["slug", "condition"],
        },
    },
    {
        "name": "search_products_batch",
        "description": "Search PriceCharting for multiple games/consoles at once. Runs up to 3 searches concurrently. Returns results keyed by each query.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of game titles to search for (max 10)",
                },
            },
            "required": ["queries"],
        },
    },
    {
        "name": "get_product_prices_batch",
        "description": "Get current prices for multiple products at once. Runs up to 3 fetches concurrently. Returns prices keyed by each slug.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "slugs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of product slugs to fetch prices for (max 10)",
                },
            },
            "required": ["slugs"],
        },
    },
]


def _json(text: str, req_id) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": text}]}}


def handle_request(req: dict) -> dict:
    method = req.get("method")
    params = req.get("params", {})
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "pricecharting-mcp", "version": "0.1.0"},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        try:
            if name == "search_products":
                return _json(json.dumps({"results": _search(args.get("query", ""))}), req_id)

            if name == "get_product_prices":
                data = get_game(args.get("slug", ""))
                return _json(json.dumps(_compact_prices(data)), req_id)

            if name == "get_product_sales":
                data = get_game(args.get("slug", ""))
                result = _compact_sales(
                    data,
                    args.get("condition", "loose"),
                    args.get("limit", 5),
                )
                return _json(json.dumps(result), req_id)

            if name == "search_products_batch":
                queries = args.get("queries", [])
                if not isinstance(queries, list) or not queries:
                    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "queries must be a non-empty array"}}
                if len(queries) > 10:
                    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "max 10 queries per batch"}}
                results = asyncio.run(_batch_search(queries))
                return _json(json.dumps(results), req_id)

            if name == "get_product_prices_batch":
                slugs = args.get("slugs", [])
                if not isinstance(slugs, list) or not slugs:
                    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "slugs must be a non-empty array"}}
                if len(slugs) > 10:
                    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "max 10 slugs per batch"}}
                results = asyncio.run(_batch_prices(slugs))
                return _json(json.dumps(results), req_id)

            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"unknown tool: {name}"}}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(exc), "data": traceback.format_exc()},
            }

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"method not found: {method}"}}


async def _batch_search(queries: list) -> list:
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    tasks = [_search_async(q, sem) for q in queries]
    return await asyncio.gather(*tasks)


async def _batch_prices(slugs: list) -> list:
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    tasks = [_get_game_async(s, sem) for s in slugs]
    return await asyncio.gather(*tasks)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in req:
            continue
        print(json.dumps(handle_request(req)), flush=True)


if __name__ == "__main__":
    main()
