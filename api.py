from typing import Optional

from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel

from scraper import get_game, Sale, PricePoint, GameData

app = FastAPI(title="Unofficial PriceCharting API")


class SaleOut(BaseModel):
    date: str
    title: str
    price: Optional[float]
    url: Optional[str]


class PricePointOut(BaseModel):
    price: Optional[float]
    change: Optional[float]
    volume: Optional[str]


class GameOut(BaseModel):
    product_id: Optional[int]
    name: str
    console: str
    console_slug: str
    slug: str
    image: Optional[str]
    loose: Optional[PricePointOut]
    complete: Optional[PricePointOut]
    new: Optional[PricePointOut]
    graded: Optional[PricePointOut]
    box_only: Optional[PricePointOut]
    manual_only: Optional[PricePointOut]
    chart_data: Optional[dict]
    recent_sales: Optional[dict[str, list[SaleOut]]]
    cached: bool  # Whether data came from cache


def _to_out(data: GameData) -> GameOut:
    def pp(p: Optional[PricePoint]) -> Optional[PricePointOut]:
        if p is None:
            return None
        return PricePointOut(price=p.price, change=p.change, volume=p.volume)

    def sl(s: Optional[Sale]) -> Optional[SaleOut]:
        if s is None:
            return None
        return SaleOut(date=s.date, title=s.title, price=s.price, url=s.url)

    return GameOut(
        product_id=data.product_id,
        name=data.name,
        console=data.console,
        console_slug=data.console_slug,
        slug=data.slug,
        image=data.image,
        loose=pp(data.loose),
        complete=pp(data.complete),
        new=pp(data.new),
        graded=pp(data.graded),
        box_only=pp(data.box_only),
        manual_only=pp(data.manual_only),
        chart_data=data.chart_data,
        recent_sales={k: [sl(s) for s in v] for k, v in (data.recent_sales or {}).items()},
        cached=data.cached,
    )


@app.get("/game/{game_id:path}", response_model=GameOut)
def read_game(
    game_id: str,
    cookie: Optional[str] = None,
):
    """
    Fetch a game by its PriceCharting slug.

    * `nintendo-3ds/super-smash-bros-for-nintendo-3ds` — full id
    * `super-smash-bros-for-nintendo-3ds` — partial id (falls back to search)
    """
    cookies = {}
    if cookie:
        for part in cookie.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
    try:
        data = get_game(game_id, cookies=cookies or None)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return _to_out(data)


@app.get("/search")
def search(
    q: str,
    cookie: Optional[str] = None,
):
    """Search for games by title."""
    from scraper import BASE, HEADERS
    import httpx
    from bs4 import BeautifulSoup

    cookies = {}
    if cookie:
        for part in cookie.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()

    jar = httpx.Cookies()
    if cookies:
        for k, v in cookies.items():
            jar.set(k, v)

    with httpx.Client(headers=HEADERS, cookies=jar, follow_redirects=True, timeout=20) as client:
        r = client.get(f"{BASE}/search-products", params={"type": "prices", "q": q, "go": "Go"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

    results = []
    for tr in soup.select("#search-results tbody tr"):
        title_a = tr.select_one("td.title a")
        console_a = tr.select_one("td.console a")
        used = tr.select_one("td.used_price span.js-price")
        cib = tr.select_one("td.cib_price span.js-price")
        new = tr.select_one("td.new_price span.js-price")
        img = tr.select_one("td.image img")

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
            "url": href,
            "image": img.get("src") if img else None,
            "prices": {
                "loose": used.get_text(strip=True) if used else None,
                "complete": cib.get_text(strip=True) if cib else None,
                "new": new.get_text(strip=True) if new else None,
            },
        })

    return {"query": q, "results": results}
