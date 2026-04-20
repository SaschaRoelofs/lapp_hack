"""
Cable Copilot – AI chat backend for cable recommendation.

Uses OpenRouter (openai/gpt-4.1-mini) with function calling to query the
Lapp shop API and recommend cables based on user requirements.
"""

from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from src.lapp_shop_proxy import (
    search_lapp,
    get_product_clean,
    get_variant_detail,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "openai/gpt-4.1-mini"

_ai_client: AsyncOpenAI | None = None


def _get_ai_client() -> AsyncOpenAI:
    global _ai_client
    if _ai_client is None:
        if not OPENROUTER_API_KEY:
            raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not configured")
        _ai_client = AsyncOpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
        )
    return _ai_client


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
Du bist der **LAPP Cable Copilot** – ein freundlicher, kompetenter Kabelberater.
Du hilfst Anwendern, das optimale LAPP-Kabel für ihre Anwendung zu finden.

Antworte immer in der Sprache, in der der User schreibt.

## Dein Vorgehen
1. Stelle gezielte Rückfragen, um die Anforderungen zu verstehen:
   - **Anwendungstyp**: Steuerleitung, Energiekabel, Datenleitung, Bus-/Netzwerkkabel?
   - **Strom & Spannung**: Nennstrom (A), Nennspannung (V), AC/DC, 1-/3-phasig?
   - **Leitungslänge**: Wie lang ist die Verlegung?
   - **Aderanzahl**: Wie viele Leiter werden benötigt?
   - **Umgebung**: Innen-/Außenbereich? Öl, Chemikalien, UV-Strahlung?
   - **Bewegung**: Feste Verlegung, gelegentliche Bewegung, Schleppkette, Roboter?
   - **Temperatur**: Besonderer Temperaturbereich?
   - **Zertifizierungen**: UL/CSA, ATEX, Bahntechnik, Schiffbau?
2. Wenn du genug Informationen hast, suche mit `search_cables` nach passenden Produkten.
3. Schaue dir die Ergebnisse an und lade bei Bedarf Details mit `get_product_details` oder `get_variant_info`.
4. Empfehle 1-3 passende Kabel mit Begründung.

## LAPP Produktfamilien
- **ÖLFLEX®**: Steuer- und Anschlussleitungen (Industrie-Standard). Flexibel, ölbeständig.
  - CLASSIC: Standard-Industrieleitung
  - CHAIN: Für Schleppketten / Energieketten
  - ROBOT: Torsionsbeständig für Robotik
  - SERVO: Für Servoantriebe / Frequenzumrichter
  - HEAT: Hochtemperatur-Anwendungen
  - CRANE: Reeling-/Kransysteme
  - CONNECT: Konfektionierte Leitungen
- **UNITRONIC®**: Daten- und Signalleitungen (geschirmt, EMV-gerecht)
- **ETHERLINE®**: Industrial-Ethernet-Leitungen (Cat.5e bis Cat.8)
- **HITRONIC®**: Glasfaserkabel (LWL)
- **EPIC®**: Steckverbinder / Industriestecker
- **SKINTOP®**: Kabelverschraubungen

## Suchstrategie
- Für Standardanwendungen suche nach der passenden ÖLFLEX-Unterfamilie
- Verwende Suchbegriffe wie "ÖLFLEX CLASSIC 110", "ÖLFLEX CHAIN 809", "UNITRONIC LiYCY" etc.
- Wenn der User eine Artikelnummer hat, nutze `get_variant_info` direkt
- Suche IMMER bevor du eine Empfehlung gibst – empfehle NIE ein Kabel ohne vorher im Shop zu suchen

## Antwortformat
- Halte Antworten kurz und strukturiert
- Nutze Markdown: **fett** für Produktnamen, Aufzählungen für Spezifikationen
- Wenn du Produkte empfiehlst, nenne immer: Name, Artikelnummer, Querschnitt, Aderanzahl und Preis (wenn verfügbar)
- Verlinke nie direkt auf URLs, die Produktkarten werden automatisch vom Frontend gerendert

## Wichtig
- Du bist KEIN Ersatz für eine professionelle Leitungsberechnung nach VDE/IEC
- Weise bei sicherheitsrelevanten Fragen (Brandschutz, ATEX) darauf hin, dass eine Fachplanung nötig ist
- Wenn du unsicher bist, sage es ehrlich und empfehle Rücksprache mit dem LAPP Vertrieb
"""

# ---------------------------------------------------------------------------
# Function calling tools
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_cables",
            "description": (
                "Sucht im LAPP Online-Shop nach Kabeln/Leitungen. "
                "Gibt eine Liste von Produkten mit Name, Artikelnummer, Preis und Variantenanzahl zurück. "
                "Suchbegriffe können Produktnamen (z.B. 'ÖLFLEX CLASSIC 110'), "
                "Eigenschaften (z.B. '5G1.5') oder Artikelnummern sein."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Suchbegriff, z.B. 'ÖLFLEX CLASSIC 110 5G1.5' oder '0011180'",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_details",
            "description": (
                "Lädt vollständige Produktdetails inkl. aller Varianten eines LAPP-Produkts. "
                "Verwende den base_product_code aus den Suchergebnissen. "
                "Gibt Beschreibung, Zertifizierungen, Eigenschaften und alle verfügbaren Querschnitte/Varianten zurück."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "base_product_code": {
                        "type": "string",
                        "description": "Basis-Produktcode, z.B. 'ölflex-classic-110-3g1-5-1119203'",
                    },
                },
                "required": ["base_product_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_variant_info",
            "description": (
                "Lädt detaillierte Informationen zu einer einzelnen Kabelvariante anhand der Artikelnummer. "
                "Gibt technische Daten (Querschnitt, Außendurchmesser, Gewicht), Preis und Verfügbarkeit zurück."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "article_code": {
                        "type": "string",
                        "description": "SAP-Artikelnummer, z.B. '0011180' oder '1119203'",
                    },
                },
                "required": ["article_code"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

async def _execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """Execute a function call and return JSON string result."""
    try:
        if name == "search_cables":
            raw = await search_lapp(arguments["query"], page=0, page_size=20)
            products = raw.get("products", [])
            results = []
            for p in products[:15]:
                results.append({
                    "base_product_code": p.get("baseProduct", p.get("code", "")),
                    "code": p.get("code", ""),
                    "name": p.get("name", ""),
                    "description": (p.get("description", "") or "")[:200],
                    "from_price": p.get("fromPrice", {}).get("formattedValue", ""),
                    "from_price_value": p.get("fromPrice", {}).get("value"),
                    "variant_count": p.get("solrApprovedVariantAmount", 0),
                    "url": f"https://www.lapp.com/de/de{p.get('url', '')}",
                    "image_url": next(
                        (img["url"] for img in p.get("images", []) if img.get("format") == "searchImageLarge"),
                        "",
                    ),
                })
            total = raw.get("pagination", {}).get("totalResults", 0)
            return json.dumps({"total_results": total, "products": results}, ensure_ascii=False)

        elif name == "get_product_details":
            product = await get_product_clean(arguments["base_product_code"])
            # Trim variants to avoid token explosion
            variants = product.get("variants", [])
            if len(variants) > 20:
                product["variants"] = variants[:20]
                product["variants_truncated"] = True
                product["total_variants"] = len(variants)
            return json.dumps(product, ensure_ascii=False, default=str)

        elif name == "get_variant_info":
            variant = await get_variant_detail(arguments["article_code"])
            return json.dumps(variant, ensure_ascii=False, default=str)

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except HTTPException as exc:
        return json.dumps({"error": exc.detail})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# FastAPI Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/copilot", tags=["Cable Copilot"])


class ChatMessage(BaseModel):
    role: str = Field(..., pattern=r"^(user|assistant|system)$")
    content: str = Field(..., max_length=10000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., max_length=50)


@router.post("/chat")
async def copilot_chat(req: ChatRequest):
    """
    AI chat endpoint with streaming. Accepts conversation history,
    returns SSE stream of token chunks and product data.

    SSE event types:
    - token: {"token": "..."} — incremental text
    - products: {"products": [...]} — product cards to render
    - done: {} — stream complete
    - error: {"error": "..."} — error occurred
    """
    client = _get_ai_client()

    # Build messages: system + last 20 user messages
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in req.messages[-20:]:
        messages.append({"role": msg.role, "content": msg.content})

    async def sse_stream():
        nonlocal messages
        collected_products: list[dict] = []

        try:
            # Tool-calling loop (max 5 rounds to prevent infinite loops)
            for _round in range(5):
                response = await client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=TOOLS,
                    stream=True,
                    temperature=0.3,
                    max_tokens=2048,
                )

                tool_calls_in_progress: dict[int, dict] = {}
                has_tool_calls = False
                full_content = ""

                async for chunk in response:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if not delta:
                        continue

                    # Stream text content
                    if delta.content:
                        full_content += delta.content
                        yield f"event: token\ndata: {json.dumps({'token': delta.content}, ensure_ascii=False)}\n\n"

                    # Accumulate tool calls
                    if delta.tool_calls:
                        has_tool_calls = True
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_calls_in_progress:
                                tool_calls_in_progress[idx] = {
                                    "id": tc.id or "",
                                    "name": "",
                                    "arguments": "",
                                }
                            if tc.id:
                                tool_calls_in_progress[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_calls_in_progress[idx]["name"] = tc.function.name
                                if tc.function.arguments:
                                    tool_calls_in_progress[idx]["arguments"] += tc.function.arguments

                    # Check for finish
                    finish = chunk.choices[0].finish_reason if chunk.choices else None
                    if finish == "stop":
                        break

                if not has_tool_calls:
                    break  # No tool calls — final text response, we're done

                # Execute all tool calls
                # First, add the assistant message with tool_calls to history
                assistant_msg: dict[str, Any] = {"role": "assistant"}
                if full_content:
                    assistant_msg["content"] = full_content
                else:
                    assistant_msg["content"] = None

                tc_list = []
                for idx in sorted(tool_calls_in_progress.keys()):
                    tc_data = tool_calls_in_progress[idx]
                    tc_list.append({
                        "id": tc_data["id"],
                        "type": "function",
                        "function": {
                            "name": tc_data["name"],
                            "arguments": tc_data["arguments"],
                        },
                    })
                assistant_msg["tool_calls"] = tc_list
                messages.append(assistant_msg)

                # Execute each tool call and add results
                for tc_data in tc_list:
                    fn_name = tc_data["function"]["name"]
                    try:
                        fn_args = json.loads(tc_data["function"]["arguments"])
                    except json.JSONDecodeError:
                        fn_args = {}

                    # Signal to frontend that we're calling a tool
                    yield f"event: tool_call\ndata: {json.dumps({'tool': fn_name, 'args': fn_args}, ensure_ascii=False)}\n\n"

                    result_str = await _execute_tool(fn_name, fn_args)

                    # Collect products for frontend rendering
                    try:
                        result_data = json.loads(result_str)
                        if fn_name == "search_cables" and "products" in result_data:
                            collected_products.extend(result_data["products"][:8])
                        elif fn_name == "get_product_details" and "variants" in result_data:
                            collected_products.append({
                                "base_product_code": result_data.get("base_product_code", ""),
                                "name": result_data.get("name", ""),
                                "description": (result_data.get("description", "") or "")[:200],
                                "from_price": result_data.get("from_price_formatted", ""),
                                "from_price_value": result_data.get("from_price_eur"),
                                "variant_count": result_data.get("variant_count", 0),
                                "url": result_data.get("canonical_url", ""),
                                "image_url": result_data.get("image_url", ""),
                            })
                        elif fn_name == "get_variant_info" and "article_number" in result_data:
                            collected_products.append({
                                "base_product_code": result_data.get("base_product_code", ""),
                                "code": result_data.get("article_number", ""),
                                "name": result_data.get("name", ""),
                                "description": "",
                                "from_price": result_data.get("price_formatted", ""),
                                "from_price_value": result_data.get("price_value"),
                                "variant_count": 1,
                                "url": result_data.get("url", ""),
                                "image_url": result_data.get("image_url", ""),
                                "cross_section": result_data.get("cross_section", ""),
                                "num_cores": result_data.get("num_cores", ""),
                                "price_per_meter": result_data.get("price_per_meter"),
                            })
                    except (json.JSONDecodeError, TypeError):
                        pass

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_data["id"],
                        "content": result_str,
                    })

                # Continue loop — AI will generate a new response based on tool results

            # Send collected products for card rendering
            if collected_products:
                # Deduplicate by name
                seen = set()
                unique = []
                for p in collected_products:
                    key = p.get("name", "") or p.get("code", "")
                    if key and key not in seen:
                        seen.add(key)
                        unique.append(p)
                yield f"event: products\ndata: {json.dumps({'products': unique[:10]}, ensure_ascii=False)}\n\n"

            yield f"event: done\ndata: {{}}\n\n"

        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(sse_stream(), media_type="text/event-stream")
