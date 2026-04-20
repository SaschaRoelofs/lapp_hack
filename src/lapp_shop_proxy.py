"""
Proxy module for the Lapp Shop OCC REST API.

Provides async helper functions and FastAPI router endpoints that query the
SAP Commerce Cloud API at api-shop.lapp.com and return cleaned-up JSON.

No database, no scraping – live data straight from the shop.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE = "https://api-shop.lapp.com/occ/v2/de"
COMMON_PARAMS = {"lang": "de", "curr": "EUR"}

EXTENDED_FIELDS = (
    "name,purchasable,baseOptions(DEFAULT),baseProduct,"
    "variantOptions(DEFAULT),variantType,certificateIcons,"
    "characteristicIcons,articleFilterAttributes,"
    "parentProductCategoryName,parentProductCategoryCode,"
    "basePriceUnit,fromPrice,productReferences,priceOnRequest,"
    "orderable,lappEndOfSales,description,code,url,"
    "price(DEFAULT),priceRange,images(FULL),quantityUnit,"
    "priceUnit,unitPrice(DEFAULT),standardLengths,remainingLengths,"
    "baseArticleListAttributes,documents,productRelatedNotes,"
    "productNotes,ref_benefits,ref_applicationRange,top5String,"
    "cuttable,firstVariantUrl,canonicalUrl,"
    "noCreateSalesOrderPermission,categoryLevelNames,"
    "variantOptionAmount"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
}

# Shared async HTTP client (reused across requests)
_client: httpx.AsyncClient | None = None

async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(headers=HEADERS, timeout=30.0, follow_redirects=True, http2=True)
    return _client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_numeric(text: str | None) -> float | None:
    """Extract numeric value from strings like '35 mm²', '8,8 mm', '122 kg/km'."""
    if not text:
        return None
    text = text.replace(",", ".")
    m = re.search(r"([\d.]+)", text)
    return float(m.group(1)) if m else None


def _clean_html(text: str | None) -> str:
    """Strip HTML tags."""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text)


def _normalize_article_code(article_code: str) -> str:
    """Strip Lapp prefixes and whitespace so shop lookups use the bare number."""
    cleaned = article_code.strip()
    cleaned = re.sub(r"^lapp\.?\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


ATTR_KEYS = [
    "num_cores",
    "protective_conductor",
    "cross_section",
    "outer_diameter",
    "copper_index",
    "weight",
]


def _parse_variant(variant: dict) -> dict:
    """Transform a raw variant into a clean dict."""
    attrs = variant.get("variantArticleListAttributes", [])

    result = {
        "article_number": variant.get("code", ""),
        "name": variant.get("name", ""),
        "url": f"https://www.lapp.com/de/de{variant.get('url', '')}",
        "orderable": variant.get("orderable", False),
        "end_of_sales": variant.get("lappEndOfSales", False),
        "price_on_request": variant.get("priceOnRequest", False),
    }

    for i, val in enumerate(attrs):
        if i < len(ATTR_KEYS):
            key = ATTR_KEYS[i]
            result[key] = val.strip() if isinstance(val, str) else val
            numeric_key = {
                "cross_section": "cross_section_mm2",
                "outer_diameter": "outer_diameter_mm",
                "copper_index": "copper_index_kg_per_km",
                "weight": "weight_kg_per_km",
            }.get(key)
            if numeric_key:
                result[numeric_key] = _parse_numeric(val if isinstance(val, str) else None)

    qualifiers = variant.get("variantOptionQualifiers", [])
    for q in qualifiers:
        if q.get("qualifier") == "top5String":
            result["description"] = _clean_html(q.get("value", ""))

    return result


def _parse_product(ext: dict) -> dict:
    """Transform extended product API response into a clean dict."""
    from_price = ext.get("fromPrice", {})
    images = ext.get("images", [])
    image_url = next(
        (img["url"] for img in images if img.get("format") == "zoom"), ""
    )

    cert_icons = ext.get("certificateIcons", [])
    certs = [c.get("tooltip", c.get("altText", "")) for c in cert_icons]

    char_icons = ext.get("characteristicIcons", [])
    chars = [c.get("tooltip", c.get("altText", "")) for c in char_icons if c.get("tooltip")]

    categories = ext.get("categoryLevelNames", [])

    variants = [_parse_variant(v) for v in ext.get("variantOptions", [])]

    return {
        "base_product_code": ext.get("code", ""),
        "name": ext.get("name", ""),
        "description": ext.get("description", ""),
        "category": " > ".join(categories) if categories else "",
        "from_price_eur": from_price.get("value"),
        "from_price_formatted": from_price.get("formattedValue", ""),
        "price_unit": ext.get("priceUnit"),
        "quantity_unit": ext.get("quantityUnit", ""),
        "benefits": ext.get("ref_benefits", []),
        "applications": ext.get("ref_applicationRange", []),
        "certifications": certs,
        "characteristics": chars,
        "canonical_url": f"https://www.lapp.com/de/de{ext.get('canonicalUrl', '')}",
        "image_url": image_url,
        "variant_count": len(variants),
        "variants": variants,
    }


# ---------------------------------------------------------------------------
# Core API functions
# ---------------------------------------------------------------------------

async def search_lapp(query: str, page: int = 0, page_size: int = 100) -> dict:
    """Search the Lapp shop. Returns raw API response."""
    client = await _get_client()
    resp = await client.get(
        f"{API_BASE}/products/search",
        params={
            **COMMON_PARAMS,
            "fields": "LAPPDEFAULT",
            "query": query,
            "pageSize": page_size,
            "currentPage": page,
        },
    )
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from Lapp API. Status: {resp.status_code}. Response: {resp.text[:200]}")


async def search_all_pages(query: str, page_size: int = 100) -> list[dict]:
    """Search and paginate through all results. Returns list of product hits."""
    all_products = []
    page = 0
    while True:
        data = await search_lapp(query, page=page, page_size=page_size)
        all_products.extend(data.get("products", []))
        pagination = data.get("pagination", {})
        total_pages = pagination.get("totalPages", 1)
        page += 1
        if page >= total_pages:
            break
    return all_products


async def get_product_extended(base_product_code: str) -> dict:
    """Fetch extended product data including all variants."""
    client = await _get_client()
    resp = await client.get(
        f"{API_BASE}/users/anonymous/products/extended/{base_product_code}",
        params={**COMMON_PARAMS, "fields": EXTENDED_FIELDS},
    )
    resp.raise_for_status()
    return resp.json()


async def get_product_clean(base_product_code: str) -> dict:
    """Fetch and return cleaned product data with parsed variants."""
    raw = await get_product_extended(base_product_code)
    return _parse_product(raw)


VARIANT_PRICE_FIELDS = "code,name,price(DEFAULT),unitPrice(DEFAULT),priceUnit,basePriceUnit,fromPrice(DEFAULT),priceOnRequest,volumePrices(DEFAULT)"

VARIANT_DETAIL_FIELDS = (
    "code,name,description,url,canonicalUrl,baseProduct,orderable,lappEndOfSales,"
    "priceOnRequest,price(DEFAULT),unitPrice(DEFAULT),priceUnit,quantityUnit,"
    "images(FULL),variantArticleListAttributes,variantOptionQualifiers"
)


async def get_variant_price(article_code: str) -> dict:
    """Fetch price data for a single variant (article code like '0011180')."""
    article_code = _normalize_article_code(article_code)
    client = await _get_client()
    resp = await client.get(
        f"{API_BASE}/products/{article_code}",
        params={**COMMON_PARAMS, "fields": VARIANT_PRICE_FIELDS},
    )
    resp.raise_for_status()
    data = resp.json()

    price_info = data.get("price", {})
    unit_price = data.get("unitPrice", {})
    price_unit = data.get("priceUnit", 1)

    # price is per priceUnit (typically 100m), calculate per meter using unitPrice
    price_value = price_info.get("value")
    unit_price_value = unit_price.get("value")
    price_per_m = round(unit_price_value / price_unit, 4) if unit_price_value and price_unit else None

    volume_prices = []
    for vp in data.get("volumePrices", []):
        volume_prices.append({
            "min_quantity": vp.get("minQuantity"),
            "max_quantity": vp.get("maxQuantity"),
            "value": vp.get("value"),
            "formatted": vp.get("formattedValue", ""),
            "currency": vp.get("currencyIso", "EUR"),
        })

    return {
        "article_number": data.get("code", article_code),
        "name": data.get("name", ""),
        "price_value": price_value,
        "price_formatted": price_info.get("formattedValue", ""),
        "price_currency": price_info.get("currencyIso", "EUR"),
        "price_unit": price_unit,
        "price_per_meter": price_per_m,
        "unit_price_value": unit_price.get("value"),
        "unit_price_formatted": unit_price.get("formattedValue", ""),
        "price_on_request": data.get("priceOnRequest", False),
        "volume_prices": volume_prices,
    }


async def get_variant_detail(article_code: str) -> dict:
    """Fetch a cleaned exact variant record for a single article number."""
    article_code = _normalize_article_code(article_code)
    client = await _get_client()
    try:
        resp = await client.get(
            f"{API_BASE}/products/{article_code}",
            params={**COMMON_PARAMS, "fields": VARIANT_DETAIL_FIELDS},
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code not in (400, 404, 410):
            raise  # Re-raise non-404 errors (rate limiting, server errors) so callers can retry
        search_data = await search_lapp(article_code, page=0, page_size=20)
        products = search_data.get("products", [])
        for product in products:
            base_code = product.get("baseProduct") or product.get("code") or ""
            if not base_code:
                continue

            try:
                product_clean = await get_product_clean(base_code)
            except httpx.HTTPStatusError:
                continue

            for variant in product_clean.get("variants", []):
                if variant.get("article_number") == article_code:
                    variant_copy = dict(variant)
                    variant_copy.setdefault("base_product_code", base_code)
                    variant_copy.setdefault("description", product_clean.get("description", ""))
                    variant_copy.setdefault("image_url", product_clean.get("image_url", ""))
                    variant_copy.setdefault("canonical_url", f"https://www.lapp.com/de/de{product.get('url', '')}")
                    variant_copy.setdefault("price_on_request", product.get("priceOnRequest", False))

                    try:
                        price_data = await get_variant_price(article_code)
                        variant_copy.update({
                            "price_value": price_data.get("price_value"),
                            "price_formatted": price_data.get("price_formatted", ""),
                            "price_currency": price_data.get("price_currency", "EUR"),
                            "price_unit": price_data.get("price_unit"),
                            "price_per_meter": price_data.get("price_per_meter"),
                            "unit_price_value": price_data.get("unit_price_value"),
                            "unit_price_formatted": price_data.get("unit_price_formatted", ""),
                        })
                    except httpx.HTTPStatusError:
                        variant_copy.setdefault("price_formatted", product.get("fromPrice", {}).get("formattedValue", ""))
                        variant_copy.setdefault("price_value", product.get("fromPrice", {}).get("value"))

                    return variant_copy

        raise HTTPException(status_code=404, detail="Variant not found")

    price_info = data.get("price", {})
    unit_price = data.get("unitPrice", {})
    price_unit = data.get("priceUnit", 1)
    price_value = price_info.get("value")
    unit_price_value = unit_price.get("value")
    price_per_m = round(unit_price_value / price_unit, 4) if unit_price_value and price_unit else None

    images = data.get("images", [])
    image_url = next((img.get("url", "") for img in images if img.get("format") in {"zoom", "product"}), "")

    parsed = _parse_variant(data)
    return {
        "article_number": data.get("code", article_code),
        "name": data.get("name", ""),
        "description": _clean_html(data.get("description", "")),
        "base_product_code": data.get("baseProduct", ""),
        "url": f"https://www.lapp.com/de/de{data.get('url', '')}",
        "canonical_url": f"https://www.lapp.com/de/de{data.get('canonicalUrl', '')}",
        "image_url": image_url,
        "orderable": data.get("orderable", False),
        "end_of_sales": data.get("lappEndOfSales", False),
        "price_on_request": data.get("priceOnRequest", False),
        "price_value": price_value,
        "price_formatted": price_info.get("formattedValue", ""),
        "price_currency": price_info.get("currencyIso", "EUR"),
        "price_unit": price_unit,
        "price_per_meter": price_per_m,
        "unit_price_value": unit_price.get("value"),
        "unit_price_formatted": unit_price.get("formattedValue", ""),
        "quantity_unit": data.get("quantityUnit", ""),
        "cross_section_mm2": parsed.get("cross_section_mm2"),
        "cross_section": parsed.get("cross_section", ""),
        "num_cores": parsed.get("num_cores", ""),
        "protective_conductor": parsed.get("protective_conductor", ""),
        "outer_diameter_mm": parsed.get("outer_diameter_mm"),
        "copper_index_kg_per_km": parsed.get("copper_index_kg_per_km"),
        "weight_kg_per_km": parsed.get("weight_kg_per_km"),
        "variants": [parsed],
    }


async def get_variant_prices(article_codes: list[str]) -> list[dict]:
    """Fetch prices for multiple variants in parallel."""
    tasks = [get_variant_price(code) for code in article_codes]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    prices = []
    for code, result in zip(article_codes, results):
        if isinstance(result, Exception):
            prices.append({
                "article_number": code,
                "error": str(result),
            })
        else:
            prices.append(result)
    return prices


VARIANT_TECH_FIELDS = (
    "code,price(DEFAULT),unitPrice(DEFAULT),priceUnit,priceOnRequest,"
    "volumePrices(DEFAULT),classifications(FULL)"
)


async def get_variant_price_and_tech(article_code: str) -> dict:
    """Fetch price AND technical data (resistance from classifications) in one call."""
    article_code = _normalize_article_code(article_code)
    client = await _get_client()
    resp = await client.get(
        f"{API_BASE}/products/{article_code}",
        params={**COMMON_PARAMS, "fields": VARIANT_TECH_FIELDS},
    )
    resp.raise_for_status()
    data = resp.json()

    # --- Price ---
    price_info = data.get("price", {})
    unit_price = data.get("unitPrice", {})
    price_unit = data.get("priceUnit", 1)
    price_value = price_info.get("value")
    unit_price_value = unit_price.get("value")
    price_per_m = round(unit_price_value / price_unit, 4) if unit_price_value and price_unit else None

    volume_prices = []
    for vp in data.get("volumePrices", []):
        volume_prices.append({
            "min_quantity": vp.get("minQuantity"),
            "max_quantity": vp.get("maxQuantity"),
            "value": vp.get("value"),
            "formatted": vp.get("formattedValue", ""),
            "currency": vp.get("currencyIso", "EUR"),
        })

    # --- Technical data from classifications ---
    resistance_ohm_per_km: float | None = None
    for cl in data.get("classifications", []):
        for feat in cl.get("features", []):
            code = feat.get("code", "").split(".")[-1]
            values = feat.get("featureValues", [])
            if code == "pdm_atr_conductor_res_at_20_max" and values:
                resistance_ohm_per_km = _parse_numeric(values[0].get("value", ""))

    return {
        "article_number": data.get("code", article_code),
        "price_value": price_value,
        "price_formatted": price_info.get("formattedValue", ""),
        "price_currency": price_info.get("currencyIso", "EUR"),
        "price_unit": price_unit,
        "price_per_meter": price_per_m,
        "unit_price_value": unit_price.get("value"),
        "unit_price_formatted": unit_price.get("formattedValue", ""),
        "price_on_request": data.get("priceOnRequest", False),
        "volume_prices": volume_prices,
        "resistance_ohm_per_km": resistance_ohm_per_km,
    }


async def get_variant_prices_and_tech(article_codes: list[str]) -> list[dict]:
    """Fetch price + technical data for multiple variants in parallel."""
    tasks = [get_variant_price_and_tech(code) for code in article_codes]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out = []
    for code, result in zip(article_codes, results):
        if isinstance(result, Exception):
            out.append({"article_number": code, "error": str(result)})
        else:
            out.append(result)
    return out


async def get_cable_options_from_shop(base_product_code: str) -> list[dict]:
    """
    Get optimizer-ready cable options from a Lapp shop product.
    Maps shop variants to the format expected by the optimizer.
    Fetches real resistance values (pdm_atr_conductor_res_at_20_max) from the
    LAPP API classifications, falling back to the DIN EN 60228 standard table.
    """
    product = await get_product_clean(base_product_code)

    # Collect variants with valid cross-section
    valid_variants = [v for v in product["variants"] if (v.get("cross_section_mm2") or 0) > 0]

    # Fetch prices + technical data for all variants in parallel (single call per variant)
    article_codes = [v.get("article_number", "") for v in valid_variants]
    tech_data = await get_variant_prices_and_tech([c for c in article_codes if c])
    tech_map = {d["article_number"]: d for d in tech_data if "error" not in d}

    from src.app import STANDARD_RESISTANCE_OHM_PER_KM, STANDARD_AMPACITY_A

    options = []
    for v in valid_variants:
        cs = v["cross_section_mm2"]
        art_nr = v.get("article_number", "")
        vdata = tech_map.get(art_nr, {})

        # Prefer real resistance from API, fall back to standard table
        resistance = vdata.get("resistance_ohm_per_km")
        resistance_source = "api"
        if resistance is None:
            resistance = STANDARD_RESISTANCE_OHM_PER_KM.get(
                cs, round(17.241 / cs, 3) if cs > 0 else 0
            )
            resistance_source = "standard_table"

        ampacity = STANDARD_AMPACITY_A.get(cs)
        copper = v.get("copper_index_kg_per_km", 0) or 0
        price_per_m = vdata.get("price_per_meter") or 0

        options.append({
            "article_number": art_nr,
            "name": v.get("name", ""),
            "cross_section_mm2": cs,
            "cross_section": v.get("cross_section", ""),
            "resistance_ohm_per_km": resistance,
            "resistance_source": resistance_source,
            "copper_mass_kg_per_km": copper,
            "cable_price_eur_per_m": price_per_m,
            "ampacity_a": ampacity,
            "num_cores": v.get("num_cores", ""),
            "protective_conductor": v.get("protective_conductor", ""),
            "outer_diameter_mm": v.get("outer_diameter_mm"),
            "weight_kg_per_km": v.get("weight_kg_per_km"),
            "url": v.get("url", ""),
            "orderable": v.get("orderable", False),
            "end_of_sales": v.get("end_of_sales", False),
        })

    return options


# ---------------------------------------------------------------------------
# FastAPI Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/shop", tags=["Lapp Shop Proxy"])


class VariantResolveItemIn(BaseModel):
    wizard_key: str = Field(..., description="Frontend wizard key for correlation")
    article_code: str | None = Field(default=None, description="SAP/article code")


class VariantResolveRequest(BaseModel):
    items: list[VariantResolveItemIn] = Field(default_factory=list)


def _variant_code_candidates(raw_code: str | None) -> list[str]:
    """Return lookup candidates for article codes to reduce false negatives."""
    normalized = _normalize_article_code(raw_code or "")
    if not normalized:
        return []

    candidates: list[str] = []

    def add(value: str | None) -> None:
        if not value:
            return
        v = value.strip()
        if v and v not in candidates:
            candidates.append(v)

    add(normalized)

    compact = re.sub(r"[\s\-_./]+", "", normalized)
    add(compact)

    decimal_match = re.fullmatch(r"(\d+)\.0+", normalized)
    if decimal_match:
        add(decimal_match.group(1))

    if compact.isdigit():
        add(compact.lstrip("0") or "0")
        if len(compact) < 7:
            add(compact.zfill(7))
        if len(compact) < 8:
            add(compact.zfill(8))

    return candidates


async def _resolve_variant_with_retry(article_code: str, retries: int = 2) -> dict:
    """
    Resolve one article code to a base product code.
    Returns one of: found | missing | error.
    """
    candidates = _variant_code_candidates(article_code)
    if not candidates:
        return {
            "status": "no_article",
            "reason": "Keine SAP-/Artikelnummer vorhanden.",
        }

    last_error: str = ""

    for candidate in candidates:
        for attempt in range(retries + 1):
            try:
                variant = await get_variant_detail(candidate)
                base_product_code = variant.get("base_product_code", "")
                if base_product_code:
                    return {
                        "status": "found",
                        "article_number": variant.get("article_number", candidate),
                        "base_product_code": base_product_code,
                    }
            except HTTPException as exc:
                if exc.status_code == 404:
                    # Try next candidate for true not-found cases.
                    break
                
                # Fallback on 502/403 or other WAF errors
                return {
                    "status": "found",
                    "article_number": candidate,
                    "base_product_code": "fallback_product",
                    "reason": "Shop API Fallback (Offline-Modus)",
                }
            except httpx.HTTPError as exc:
                return {
                    "status": "found",
                    "article_number": candidate,
                    "base_product_code": "fallback_product",
                    "reason": f"Verbindungsfehler Fallback: {str(exc)}",
                }
            except Exception as exc:  # pragma: no cover - defensive
                last_error = str(exc)

            if attempt < retries:
                await asyncio.sleep(0.5 * (attempt + 1))

    # --- Search-based fallback ---
    # get_variant_detail's internal search requires an exact variant article_number
    # match, which fails when the EPLAN SAP number differs from the shop's article
    # format.  The wizard only needs the base_product_code, so a simple search hit
    # is sufficient.
    for candidate in candidates:
        try:
            search_data = await search_lapp(candidate, page=0, page_size=5)
            products = search_data.get("products", [])
            if products:
                base_code = products[0].get("baseProduct") or products[0].get("code") or ""
                if base_code:
                    return {
                        "status": "found",
                        "article_number": candidate,
                        "base_product_code": base_code,
                        "reason": "Über Shop-Suche gefunden.",
                    }
        except Exception:
            pass  # search failed, continue

    if last_error:
        return {
            "status": "error",
            "reason": f"Shop-Pruefung fehlgeschlagen: {last_error}",
        }

    return {
        "status": "missing",
        "reason": "Nicht im LAPP Shop gefunden.",
    }


@router.get("/search")
async def shop_search(
    q: str = Query(..., description="Search query, e.g. 'ölflex'"),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=100),
):
    """Search the Lapp online shop."""
    try:
        data = await search_lapp(q, page=page, page_size=page_size)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Lapp API error: {exc.response.status_code}")

    products = data.get("products", [])
    pagination = data.get("pagination", {})

    return {
        "query": q,
        "page": pagination.get("currentPage", page),
        "total_pages": pagination.get("totalPages", 0),
        "total_results": pagination.get("totalResults", 0),
        "products": [
            {
                "base_product_code": p.get("baseProduct", p.get("code", "")),
                "code": p.get("code", ""),
                "name": p.get("name", ""),
                "description": p.get("description", ""),
                "from_price": p.get("fromPrice", {}).get("formattedValue", ""),
                "from_price_value": p.get("fromPrice", {}).get("value"),
                "variant_count": p.get("solrApprovedVariantAmount", 0),
                "url": f"https://www.lapp.com/de/de{p.get('url', '')}",
                "image_url": next(
                    (img["url"] for img in p.get("images", []) if img.get("format") == "searchImageLarge"),
                    "",
                ),
            }
            for p in products
        ],
    }


@router.post("/variants/resolve")
async def shop_variants_resolve(payload: VariantResolveRequest):
    """
    Resolve many article codes in one request.
    Designed for wizard preload to avoid per-step false negatives.
    """
    items = payload.items or []
    if not items:
        return {"results": []}

    # Deduplicate by normalized input to avoid redundant upstream calls.
    unique_codes: dict[str, str] = {}
    for item in items:
        normalized = _normalize_article_code(item.article_code or "")
        if normalized and normalized not in unique_codes:
            unique_codes[normalized] = item.article_code or ""

    semaphore = asyncio.Semaphore(3)
    resolved_by_code: dict[str, dict] = {}

    async def _resolve_one(normalized_code: str, original_code: str) -> None:
        async with semaphore:
            resolved_by_code[normalized_code] = await _resolve_variant_with_retry(original_code, retries=2)

    await asyncio.gather(
        *[_resolve_one(norm, original) for norm, original in unique_codes.items()],
        return_exceptions=False,
    )

    results: list[dict] = []
    for item in items:
        normalized = _normalize_article_code(item.article_code or "")
        if not normalized:
            entry = {
                "wizard_key": item.wizard_key,
                "input_article_code": item.article_code or "",
                "normalized_article_code": "",
                "status": "no_article",
                "reason": "Keine SAP-/Artikelnummer vorhanden.",
            }
        else:
            resolved = resolved_by_code.get(normalized, {"status": "error", "reason": "Keine Antwort vom Shop-Resolver."})
            entry = {
                "wizard_key": item.wizard_key,
                "input_article_code": item.article_code or "",
                "normalized_article_code": normalized,
                **resolved,
            }
        results.append(entry)

    return {"results": results}


@router.get("/product/{base_product_code}")
async def shop_product(base_product_code: str):
    """Get full product details with all variants from the Lapp shop."""
    try:
        return await get_product_clean(base_product_code)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Product not found in Lapp shop")
        raise HTTPException(status_code=502, detail=f"Lapp API error: {exc.response.status_code}")


@router.get("/product/{base_product_code}/cable-options")
async def shop_cable_options(base_product_code: str):
    """
    Get optimizer-compatible cable options from a Lapp shop product.
    Streams progress using Server-Sent Events to build the options.
    """
    import json
    
    async def sse_generator():
        try:
            if base_product_code == "fallback_product":
                from src.app import DEFAULT_OPTIONS
                yield f"data: {json.dumps({'progress': 100, 'message': 'Fertig.', 'options': DEFAULT_OPTIONS})}\n\n"
                return
            
            yield f"data: {json.dumps({'progress': 10, 'message': 'Lade Produktdaten aus dem Shop...'})}\n\n"
            product = await get_product_clean(base_product_code)
            
            valid_variants = [v for v in product["variants"] if (v.get("cross_section_mm2") or 0) > 0]
            article_codes = [v.get("article_number", "") for v in valid_variants if v.get("article_number")]
            total = len(article_codes)
            
            if total == 0:
                yield f"data: {json.dumps({'progress': 100, 'message': 'Keine gültigen Varianten gefunden.', 'options': []})}\n\n"
                return
            
            yield f"data: {json.dumps({'progress': 15, 'message': f'{total} Varianten gefunden. Lade technische Details...'})}\n\n"
            
            # Use asyncio.Semaphore for better concurrency management instead of static chunks
            semaphore = asyncio.Semaphore(25)  # 25 simultaneous connections
            tech_data = []
            completed = 0
            
            async def fetch_tech_data(code):
                async with semaphore:
                    res = await get_variant_price_and_tech(code)
                    return code, res

            # We process them as they complete to give a smooth progress bar
            tasks = [asyncio.create_task(fetch_tech_data(c)) for c in article_codes]
            
            for future in asyncio.as_completed(tasks):
                try:
                    code, res = await future
                    tech_data.append(res)
                except Exception as e:
                    # In real-world, we want to know WHICH code failed, but for simplicity:
                    tech_data.append({"article_number": "unknown", "error": str(e)})

                completed += 1
                prog = 15 + int((completed / total) * 80)
                
                # Only yield every few percent to avoid flooding the browser with SSE events
                if completed % 5 == 0 or completed == total:
                    yield f"data: {json.dumps({'progress': prog, 'message': f'Verarbeite Variante {completed} / {total}...'})}\n\n"
                
            yield f"data: {json.dumps({'progress': 95, 'message': 'Erstelle Optimierungs-Modell...'})}\n\n"
            
            tech_map = {d["article_number"]: d for d in tech_data if "error" not in d}
            from src.app import STANDARD_RESISTANCE_OHM_PER_KM, STANDARD_AMPACITY_A

            options = []
            for v in valid_variants:
                cs = v["cross_section_mm2"]
                art_nr = v.get("article_number", "")
                vdata = tech_map.get(art_nr, {})

                resistance = vdata.get("resistance_ohm_per_km")
                resistance_source = "api"
                if resistance is None:
                    resistance = STANDARD_RESISTANCE_OHM_PER_KM.get(cs, round(17.241 / cs, 3) if cs > 0 else 0)
                    resistance_source = "standard_table"

                ampacity = STANDARD_AMPACITY_A.get(cs)
                copper = v.get("copper_index_kg_per_km", 0) or 0
                price_per_m = vdata.get("price_per_meter") or 0

                options.append({
                    "article_number": art_nr,
                    "name": v.get("name", ""),
                    "cross_section_mm2": cs,
                    "cross_section": v.get("cross_section", ""),
                    "resistance_ohm_per_km": resistance,
                    "resistance_source": resistance_source,
                    "copper_mass_kg_per_km": copper,
                    "cable_price_eur_per_m": price_per_m,
                    "ampacity_a": ampacity,
                    "num_cores": v.get("num_cores", ""),
                    "protective_conductor": v.get("protective_conductor", ""),
                    "outer_diameter_mm": v.get("outer_diameter_mm"),
                    "weight_kg_per_km": v.get("weight_kg_per_km"),
                    "url": v.get("url", ""),
                    "orderable": v.get("orderable", False),
                    "end_of_sales": v.get("end_of_sales", False),
                })
            
            yield f"data: {json.dumps({'progress': 100, 'message': 'Laden abgeschlossen.', 'options': options})}\n\n"
            
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                yield f"data: {json.dumps({'error': 'Product not found in Lapp shop'})}\n\n"
            else:
                from src.app import DEFAULT_OPTIONS
                yield f"data: {json.dumps({'progress': 100, 'message': 'API-Limit, benutze Fallback.', 'options': DEFAULT_OPTIONS})}\n\n"
        except Exception as e:
            from src.app import DEFAULT_OPTIONS
            yield f"data: {json.dumps({'progress': 100, 'message': 'Fehler, benutze Fallback.', 'options': DEFAULT_OPTIONS})}\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@router.get("/product/{base_product_code}/cable-options-direct")
async def shop_cable_options_direct(base_product_code: str):
    """
    Get optimizer-compatible cable options (non-streaming JSON response).
    Used by the optimizer page and cable wizard for a simple fetch.
    """
    if base_product_code == "fallback_product":
        from src.app import DEFAULT_OPTIONS
        return {"options": DEFAULT_OPTIONS}

    try:
        options = await get_cable_options_from_shop(base_product_code)
        return {"options": options}
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Product not found in Lapp shop")
        # Fallback on API errors
        from src.app import DEFAULT_OPTIONS
        return {"options": DEFAULT_OPTIONS}
    except Exception:
        from src.app import DEFAULT_OPTIONS
        return {"options": DEFAULT_OPTIONS}


@router.get("/product/{base_product_code}/prices")
async def shop_product_prices(base_product_code: str):
    """
    Get prices for all variants of a product.
    Fetches each variant price from the Lapp API in parallel.
    """
    try:
        product = await get_product_clean(base_product_code)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Product not found in Lapp shop")
        raise HTTPException(status_code=502, detail=f"Lapp API error: {exc.response.status_code}")

    article_codes = [v["article_number"] for v in product["variants"] if v.get("article_number")]
    prices = await get_variant_prices(article_codes)

    return {
        "base_product_code": product["base_product_code"],
        "name": product["name"],
        "variant_count": len(article_codes),
        "prices": prices,
    }


@router.get("/variant/{article_code}/price")
async def shop_variant_price(article_code: str):
    """Get price for a single variant by article code."""
    try:
        return await get_variant_price(article_code)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Variant not found")
        raise HTTPException(status_code=502, detail=f"Lapp API error: {exc.response.status_code}")


@router.get("/variant/{article_code}")
async def shop_variant_detail(article_code: str):
    """Get the exact shop record for a single variant/article number."""
    try:
        return await get_variant_detail(article_code)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        # get_variant_detail 404'd – try a search-based fallback so the wizard
        # can still resolve the base_product_code even when the article number
        # format doesn't match exactly.
        normalized = _normalize_article_code(article_code)
        try:
            search_data = await search_lapp(normalized or article_code, page=0, page_size=5)
            products = search_data.get("products", [])
            if products:
                hit = products[0]
                base_code = hit.get("baseProduct") or hit.get("code") or ""
                if base_code:
                    return {
                        "article_number": normalized or article_code,
                        "name": hit.get("name", ""),
                        "base_product_code": base_code,
                        "url": f"https://www.lapp.com/de/de{hit.get('url', '')}",
                        "image_url": next(
                            (img["url"] for img in hit.get("images", []) if img.get("format") == "searchImageLarge"),
                            "",
                        ),
                        "price_on_request": hit.get("priceOnRequest", False),
                        "orderable": True,
                    }
        except Exception:
            pass
        raise HTTPException(status_code=404, detail="Variant not found")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Variant not found")
        
        # Fallback dummy variant for optimization
        return {
            "article_number": article_code,
            "name": f"LAPP Kabel {article_code} (Offline-Modus)",
            "base_product_code": "fallback_product",
            "cross_section_mm2": 1.5,
            "num_cores": "3",
            "price_value": 0,
            "price_formatted": "Kein Preis",
            "price_unit": 1,
            "price_per_meter": 0,
            "image_url": "",
            "url": ""
        }


@router.get("/product/{base_product_code}/raw")
async def shop_product_raw(base_product_code: str):
    """Get the raw OCC API response (for debugging)."""
    try:
        return await get_product_extended(base_product_code)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Lapp API error: {exc.response.status_code}")
