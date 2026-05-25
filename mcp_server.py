#!/usr/bin/env python3
"""
Lightweight stdio MCP server for PriceCharting.
Works with LM Studio and any MCP client that speaks JSON-RPC over stdio.
"""

import sys
import json
import traceback
from typing import Any

from scraper import get_game
import httpx
from bs4 import BeautifulSoup

BASE = "https://www.pricecharting.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:136.0) "
        "Gecko/20100101 Firefox/136.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}


def _search(query: str) -> list:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=20) as client:
        r = client.get(
            f"{BASE}/search-products",
            params={"type": "prices", "q": query, "go": "Go"},
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

    results = []
    for tr in soup.select("#search-results tbody tr"):
        title_a = tr.select_one("td.title a")
        console_a = tr.select_one("td.console a")
        used = tr.select_one("td.used_price span.js-price")
        cib = tr.select_one("td.cib_price span.js-price")
        new = tr.select_one("td.new_price span.js-price")
        if not title_a:
            continue
        href = title_a.get("href", "")
        slug = ""
        if "/game/" in href:
            slug = href.split("/game/", 1)[1]
        results.append({
            "name": title_a.get_text(strip=True),
            "console": console_a.get_text(strip=True) if console_a else None,
            "slug": slug,
            "prices": {
                "loose": used.get_text(strip=True) if used else None,
                "complete": cib.get_text(strip=True) if cib else None,
                "new": new.get_text(strip=True) if new else None,
            },
        })
    return results


def _game_summary(data) -> dict:
    def pp(p):
        if p is None:
            return None
        return {"price": p.price, "change": p.change, "volume": p.volume}

    sales_summary = {}
    for k, v in (data.recent_sales or {}).items():
        sales_summary[k] = [
            {"date": s.date, "title": s.title, "price": s.price}
            for s in v[:5]
        ]

    return {
        "product_id": data.product_id,
        "name": data.name,
        "console": data.console,
        "slug": data.slug,
        "image": data.image,
        "prices": {
            "loose": pp(data.loose),
            "complete": pp(data.complete),
            "new": pp(data.new),
            "graded": pp(data.graded),
            "box_only": pp(data.box_only),
            "manual_only": pp(data.manual_only),
        },
        "recent_sales": sales_summary,
    }


TOOLS = [
    {
        "name": "search_games",
        "description": "Search PriceCharting for games by title.",
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
        "name": "get_game_details",
        "description": (
            "Get full price data and recent sales for a specific game. "
            "Use the slug from search_games (e.g. 'nintendo-3ds/super-smash-bros-for-nintendo-3ds')."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "PriceCharting game slug, usually console/name",
                },
            },
            "required": ["slug"],
        },
    },
]


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
                "serverInfo": {
                    "name": "pricecharting-mcp",
                    "version": "0.1.0",
                },
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        try:
            if name == "search_games":
                results = _search(args.get("query", ""))
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps({"results": results}, indent=2),
                            }
                        ]
                    },
                }

            if name == "get_game_details":
                data = get_game(args.get("slug", ""))
                summary = _game_summary(data)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(summary, indent=2),
                            }
                        ]
                    },
                }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"unknown tool: {name}"},
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32000,
                    "message": str(exc),
                    "data": traceback.format_exc(),
                },
            }

    # unknown method
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        # ignore notifications (no id)
        if "id" not in req:
            continue

        resp = handle_request(req)
        print(json.dumps(resp), flush=True)


if __name__ == "__main__":
    main()
