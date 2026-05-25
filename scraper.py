import re
import json
from dataclasses import dataclass
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

BASE = "https://www.pricecharting.com"


def _headers() -> dict:
    return {
        "User-Agent": UserAgent().random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }


@dataclass
class Sale:
    date: str
    title: str
    price: float
    url: Optional[str] = None


@dataclass
class PricePoint:
    price: float
    change: Optional[float] = None
    volume: Optional[str] = None


@dataclass
class GameData:
    product_id: int
    name: str
    console: str
    console_slug: str
    slug: str
    image: Optional[str] = None
    loose: Optional[PricePoint] = None
    complete: Optional[PricePoint] = None
    new: Optional[PricePoint] = None
    graded: Optional[PricePoint] = None
    box_only: Optional[PricePoint] = None
    manual_only: Optional[PricePoint] = None
    chart_data: dict = None
    recent_sales: dict = None


def _parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"[\d,]+\.\d{2}", text.replace(",", ""))
    if m:
        return float(m.group().replace(",", ""))
    return None


def _parse_change(elem) -> Optional[float]:
    span = elem.select_one("span.change")
    if not span:
        return None
    text = span.get_text(strip=True)
    val = _parse_price(text)
    if val is None:
        return None
    if text.startswith("-"):
        return -val
    return val


def _parse_volume(elem) -> Optional[str]:
    a = elem.select_one("a")
    if a:
        return a.get_text(strip=True)
    return None


def _fetch(url: str, cookies: Optional[dict] = None) -> BeautifulSoup:
    jar = httpx.Cookies()
    if cookies:
        for k, v in cookies.items():
            jar.set(k, v)
    with httpx.Client(headers=_headers(), cookies=jar, follow_redirects=True, timeout=20) as client:
        r = client.get(url)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")


def _extract_chart_data(soup: BeautifulSoup) -> Optional[dict]:
    script = soup.find("script", string=re.compile(r"VGPC\.chart_data"))
    if not script:
        # try any script tag
        for s in soup.find_all("script"):
            if s.string and "VGPC.chart_data" in s.string:
                script = s
                break
    if not script or not script.string:
        return None
    m = re.search(r"VGPC\.chart_data\s*=\s*({.*?});", script.string, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _extract_product_meta(soup: BeautifulSoup) -> dict:
    meta = {"product_id": None, "name": "", "console": "", "console_slug": "", "slug": "", "image": None}

    h1 = soup.select_one("h1#product_name")
    if h1:
        meta["name"] = h1.contents[0].strip() if h1.contents else ""
        console_a = h1.select_one("a")
        if console_a:
            meta["console"] = console_a.get_text(strip=True)
            href = console_a.get("href", "")
            meta["console_slug"] = href.replace("/console/", "") if href.startswith("/console/") else ""

    # product id from h1 title attr or VGPC.product
    if h1 and h1.get("title"):
        try:
            meta["product_id"] = int(h1["title"])
        except ValueError:
            pass

    for script in soup.find_all("script"):
        if script.string and "VGPC.product" in script.string:
            m = re.search(r"id:\s*(\d+)", script.string)
            if m:
                meta["product_id"] = int(m.group(1))
            break

    img = soup.select_one("#product_details .cover img")
    if img:
        meta["image"] = img.get("src") or img.get("data-src")

    # slug from canonical or og:url
    canonical = soup.select_one("link[rel='canonical']")
    if canonical:
        href = canonical.get("href", "")
        if "/game/" in href:
            parts = href.split("/game/", 1)[1].split("/")
            if len(parts) >= 2:
                meta["console_slug"] = parts[0]
                meta["slug"] = parts[1]

    return meta


def _extract_prices(soup: BeautifulSoup) -> dict:
    prices = {}
    table = soup.select_one("table#price_data")
    if not table:
        return prices

    # Map cell ids to condition names
    mapping = {
        "used_price": "loose",
        "complete_price": "complete",
        "new_price": "new",
        "graded_price": "graded",
        "box_only_price": "box_only",
        "manual_only_price": "manual_only",
    }

    for cell_id, key in mapping.items():
        cell = table.select_one(f"td#{cell_id}")
        if not cell:
            continue
        price_span = cell.select_one("span.price") or cell.select_one("span.js-price")
        price = _parse_price(price_span.get_text(strip=True) if price_span else "")
        change = _parse_change(cell)
        prices[key] = PricePoint(price=price, change=change)

    # volumes are in a separate row
    volume_row = table.select_one("tr.sales_volume")
    if volume_row:
        cells = volume_row.find_all("td", recursive=False)
        headers = ["loose", "complete", "new", "graded", "box_only", "manual_only"]
        for i, key in enumerate(headers):
            if i < len(cells) and key in prices:
                prices[key].volume = _parse_volume(cells[i])

    return prices


def _extract_recent_sales(soup: BeautifulSoup) -> dict:
    sales = {}
    condition_map = {
        "completed-auctions-used": "loose",
        "completed-auctions-cib": "complete",
        "completed-auctions-new": "new",
        "completed-auctions-graded": "graded",
        "completed-auctions-box-only": "box_only",
        "completed-auctions-manual-only": "manual_only",
    }

    for css_class, key in condition_map.items():
        # there may be tab buttons with the same class; pick the div that has a table
        divs = soup.find_all("div", class_=css_class)
        div = None
        for d in divs:
            if d.select_one("table"):
                div = d
                break
        if not div:
            continue
        rows = []
        for tr in div.select("table tbody tr"):
            date_cell = tr.select_one("td.date")
            title_cell = tr.select_one("td.title a")
            price_cell = tr.select_one("td.numeric span.js-price")
            if not date_cell or not price_cell:
                continue
            rows.append(Sale(
                date=date_cell.get_text(strip=True),
                title=title_cell.get_text(strip=True) if title_cell else "",
                price=_parse_price(price_cell.get_text(strip=True)),
                url=title_cell.get("href") if title_cell else None,
            ))
        if rows:
            sales[key] = rows

    return sales


def get_game(game_id: str, cookies: Optional[dict] = None) -> GameData:
    """Fetch game by partial or full id.

    game_id can be:
      - "nintendo-3ds/super-smash-bros-for-nintendo-3ds"
      - "super-smash-bros-for-nintendo-3ds" (will try search fallback)
    """
    # Try direct URL first
    if "/" in game_id:
        url = f"{BASE}/game/{game_id}"
    else:
        url = f"{BASE}/game/{game_id}"

    try:
        soup = _fetch(url, cookies)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404 and "/" not in game_id:
            # search fallback
            soup = _search_and_fetch(game_id, cookies)
        else:
            raise

    meta = _extract_product_meta(soup)
    prices = _extract_prices(soup)
    chart = _extract_chart_data(soup)
    sales = _extract_recent_sales(soup)

    return GameData(
        product_id=meta.get("product_id"),
        name=meta.get("name", ""),
        console=meta.get("console", ""),
        console_slug=meta.get("console_slug", ""),
        slug=meta.get("slug", ""),
        image=meta.get("image"),
        loose=prices.get("loose"),
        complete=prices.get("complete"),
        new=prices.get("new"),
        graded=prices.get("graded"),
        box_only=prices.get("box_only"),
        manual_only=prices.get("manual_only"),
        chart_data=chart,
        recent_sales=sales,
    )


def _search_and_fetch(query: str, cookies: Optional[dict] = None) -> BeautifulSoup:
    """Search for a game and return the first result's page soup."""
    jar = httpx.Cookies()
    if cookies:
        for k, v in cookies.items():
            jar.set(k, v)
    with httpx.Client(headers=_headers(), cookies=jar, follow_redirects=True, timeout=20) as client:
        r = client.get(
            f"{BASE}/search-products",
            params={"type": "prices", "q": query, "go": "Go"},
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

    # grab first result link
    first = soup.select_one("#search-results tbody tr td.title a")
    if not first:
        raise ValueError(f"no search results for: {query}")
    href = first.get("href", "")
    if not href:
        raise ValueError("search result missing href")

    with httpx.Client(headers=_headers(), cookies=jar, follow_redirects=True, timeout=20) as client:
        r = client.get(href)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
