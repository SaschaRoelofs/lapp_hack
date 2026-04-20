"""FastAPI backend for the Leitungsquerschnitt-Optimierer web application."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import markdown
import uvicorn
from fastapi import FastAPI, Header, Request, Body
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Any

from src.optimizer import (
    CableOption,
    InputParams,
    evaluate_all,
    find_optimum,
    payback_years,
)
from src.machine_db import build_machine_graph_from_json, build_machine_graph_from_data
from src.lapp_shop_proxy import router as shop_router
from src.copilot import router as copilot_router

from typing import Any

class CableReplacement(BaseModel):
    cable_name: str
    original_mm2: Optional[Any] = None
    recommended_mm2: Optional[Any] = None
    recommended_article_nr: Optional[str] = None
    reason: Optional[str] = None

app = FastAPI(title="Leitungsquerschnitt-Optimierer")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "../static"), name="static")
app.include_router(shop_router)
app.include_router(copilot_router)
templates = Jinja2Templates(directory=Path(__file__).parent / "../templates")

# ---------------------------------------------------------------------------
# README → HTML (single source of truth for the homepage)
# ---------------------------------------------------------------------------
_README_PATH = Path(__file__).parent / "../README.md"


def _render_readme() -> str:
    md_text = _README_PATH.read_text(encoding="utf-8")
    return markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "codehilite"],
    )

# ---------------------------------------------------------------------------
# Default cable options (from the original main() example configuration)
# ---------------------------------------------------------------------------
DEFAULT_OPTIONS = [
    {"cross_section_mm2": 1.5, "resistance_ohm_per_km": 13.3, "copper_mass_kg_per_km": 43.0, "cable_price_eur_per_m": 1.70, "ampacity_a": 16},
    {"cross_section_mm2": 2.5, "resistance_ohm_per_km": 7.98, "copper_mass_kg_per_km": 96.0, "cable_price_eur_per_m": 2.49, "ampacity_a": 25},
    {"cross_section_mm2": 4.0, "resistance_ohm_per_km": 4.95, "copper_mass_kg_per_km": 150.0, "cable_price_eur_per_m": 3.15, "ampacity_a": 34},
    {"cross_section_mm2": 6.0, "resistance_ohm_per_km": 3.30, "copper_mass_kg_per_km": 230.0, "cable_price_eur_per_m": 4.40, "ampacity_a": 44},
    {"cross_section_mm2": 10.0, "resistance_ohm_per_km": 1.91, "copper_mass_kg_per_km": 360.0, "cable_price_eur_per_m": 6.90, "ampacity_a": 61},
    {"cross_section_mm2": 16.0, "resistance_ohm_per_km": 1.21, "copper_mass_kg_per_km": 565.0, "cable_price_eur_per_m": 10.20, "ampacity_a": 82},
    {"cross_section_mm2": 25.0, "resistance_ohm_per_km": 0.780, "copper_mass_kg_per_km": 860.0, "cable_price_eur_per_m": 15.90, "ampacity_a": 108},
    {"cross_section_mm2": 35.0, "resistance_ohm_per_km": 0.554, "copper_mass_kg_per_km": 1200.0, "cable_price_eur_per_m": 21.80, "ampacity_a": 135},
    {"cross_section_mm2": 50.0, "resistance_ohm_per_km": 0.386, "copper_mass_kg_per_km": 1700.0, "cable_price_eur_per_m": 30.00, "ampacity_a": 168},
]

DEFAULT_PARAMS = {
    "length_m": 50.0,
    "current_a": 16.0,
    "total_cores": 4,
    "loaded_cores": 3,
    "years": 10.0,
    "days_per_year": 220.0,
    "hours_per_day": 16.0,
    "energy_price_eur_per_kwh": 0.35,
    "electricity_emission_factor_kg_per_kwh": 0.368,
    "copper_emission_factor_kg_per_kg": 3.965,
    "max_voltage_drop_percent": 3.0,
    "system_voltage_v": 400.0,
    "ac_3phase": True,
}

# ---------------------------------------------------------------------------
# Pydantic models (API boundary)
# ---------------------------------------------------------------------------

class CableOptionIn(BaseModel):
    cross_section_mm2: float
    resistance_ohm_per_km: float
    copper_mass_kg_per_km: float
    cable_price_eur_per_m: float
    ampacity_a: Optional[float] = None


class ParamsIn(BaseModel):
    length_m: float
    current_a: float
    total_cores: int
    loaded_cores: int
    years: float
    days_per_year: float
    hours_per_day: float
    energy_price_eur_per_kwh: float
    electricity_emission_factor_kg_per_kwh: float
    copper_emission_factor_kg_per_kg: float
    max_voltage_drop_percent: Optional[float] = None
    system_voltage_v: Optional[float] = None
    ac_3phase: bool = True


class CalculateRequest(BaseModel):
    params: ParamsIn
    options: list[CableOptionIn]


class ResultRowOut(BaseModel):
    cross_section_mm2: float
    admissible: bool
    rejection_reason: str
    r_total_ohm_per_core: float
    p_loss_w: float
    energy_loss_kwh: float
    cable_price_eur: float
    loss_cost_eur: float
    tco_eur: float
    copper_mass_total_kg: float
    co2_initial_kg: float
    co2_loss_kg: float
    co2_total_kg: float
    voltage_drop_v: Optional[float]
    voltage_drop_percent: Optional[float]


class OptimumInfo(BaseModel):
    tco: Optional[ResultRowOut] = None
    co2: Optional[ResultRowOut] = None
    smallest_admissible: Optional[ResultRowOut] = None
    payback_tco_years: Optional[float] = None


class CalculateResponse(BaseModel):
    rows: list[ResultRowOut]
    optimum: OptimumInfo


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.api_route("/health", methods=["GET", "HEAD"], tags=["Health"])
async def health():
    """Liveness check – returns 200 as long as the API process is running."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"readme_html": _render_readme()},
    )


import csv

def _load_scenarios() -> list[dict[str, Any]]:
    scenarios = []
    csv_path = Path(__file__).parent / "application_scenarios.csv"
    if csv_path.exists():
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                scenarios.append(row)
    return scenarios

@app.get("/optimizer", response_class=HTMLResponse)
async def optimizer_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="optimizer.html",
        context={
            "default_params": DEFAULT_PARAMS,
            "scenarios": _load_scenarios(),
        },
    )


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    return templates.TemplateResponse(request=request, name="search.html")


@app.get("/copilot", response_class=HTMLResponse)
async def copilot_page(request: Request):
    embedded = request.query_params.get("embedded") == "true"
    return templates.TemplateResponse(request=request, name="copilot.html", context={"embedded": embedded})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "defaults": {
                "energy_price_eur_per_kwh": DEFAULT_PARAMS["energy_price_eur_per_kwh"],
                "max_voltage_drop_percent": DEFAULT_PARAMS["max_voltage_drop_percent"],
                "electricity_emission_factor_kg_per_kwh": DEFAULT_PARAMS["electricity_emission_factor_kg_per_kwh"],
                "copper_emission_factor_kg_per_kg": DEFAULT_PARAMS["copper_emission_factor_kg_per_kg"],
            },
        },
    )


@app.get("/snake", response_class=HTMLResponse)
async def snake_page(request: Request):
    return templates.TemplateResponse(request=request, name="snake.html")


@app.post("/api/calculate", response_model=CalculateResponse)
async def calculate(req: CalculateRequest):
    options = [CableOption(**o.model_dump()) for o in req.options]
    params = InputParams(**req.params.model_dump())

    rows = evaluate_all(options, params)
    row_dicts = [ResultRowOut(**asdict(r)) for r in rows]

    optimum = OptimumInfo()
    try:
        best_tco = find_optimum(rows, "tco")
        optimum.tco = ResultRowOut(**asdict(best_tco))
    except ValueError:
        pass

    try:
        best_co2 = find_optimum(rows, "co2")
        optimum.co2 = ResultRowOut(**asdict(best_co2))
    except ValueError:
        pass

    admissible = [r for r in rows if r.admissible]
    if admissible:
        smallest = min(admissible, key=lambda r: r.cross_section_mm2)
        optimum.smallest_admissible = ResultRowOut(**asdict(smallest))

        if optimum.tco:
            pb = payback_years(smallest, best_tco, params)
            optimum.payback_tco_years = pb

    return CalculateResponse(rows=row_dicts, optimum=optimum)





# ---------------------------------------------------------------------------
# Standard lookup tables for cable properties (IEC 60228 Class 2)
# ---------------------------------------------------------------------------

STANDARD_RESISTANCE_OHM_PER_KM: dict[float, float] = {
    0.5: 36.0, 0.75: 24.5, 1.0: 18.1, 1.5: 13.3, 2.5: 7.98,
    4.0: 4.95, 6.0: 3.30, 10.0: 1.91, 16.0: 1.21, 25.0: 0.780,
    35.0: 0.554, 50.0: 0.386, 70.0: 0.272, 95.0: 0.206,
    120.0: 0.161, 150.0: 0.129, 185.0: 0.106, 240.0: 0.0801,
    300.0: 0.0641,
}

STANDARD_AMPACITY_A: dict[float, int] = {
    0.5: 3, 0.75: 8, 1.0: 11, 1.5: 15, 2.5: 21, 4.0: 28, 6.0: 36,
    10.0: 50, 16.0: 68, 25.0: 89, 35.0: 110, 50.0: 134, 70.0: 171,
    95.0: 207, 120.0: 240, 150.0: 272, 185.0: 310, 240.0: 364,
}





@app.get("/machine", response_class=HTMLResponse)
async def machine_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="machine.html",
        context={
            "default_params": DEFAULT_PARAMS,
            "default_options": DEFAULT_OPTIONS,
        },
    )


@app.get("/api/machine-db")
async def api_machine_db():
    from fastapi import HTTPException

    try:
        return build_machine_graph_from_json()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Token store – graphs are persisted as <token>.json on disk
# ---------------------------------------------------------------------------
_GRAPH_STORE_DIR = Path(__file__).parent / "../graph_store"
_GRAPH_STORE_DIR.mkdir(exist_ok=True)


@app.post("/api/machine-db")
async def api_machine_db_upload(
    data: dict[str, Any],
    authorization: Optional[str] = Header(default=None),
):
    from fastapi import HTTPException

    # Accept client-provided token from "Authorization: Bearer <token>" header
    token: Optional[str] = None
    if authorization and authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()
        if candidate.isalnum() and len(candidate) <= 64:
            token = candidate
    if not token:
        token = uuid.uuid4().hex

    # Rohdaten vor der Verarbeitung speichern
    (_GRAPH_STORE_DIR / f"{token}_raw.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )

    try:
        graph = build_machine_graph_from_data(data, source_label=data.get("projectName", "upload"))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    (_GRAPH_STORE_DIR / f"{token}.json").write_text(
        json.dumps(graph, ensure_ascii=False), encoding="utf-8"
    )
    return {"token": token}


@app.get("/api/machine-db/{token}")
async def api_machine_db_by_token(token: str):
    from fastapi import HTTPException

    # Restrict token to hex characters to prevent path traversal
    if not token.isalnum():
        raise HTTPException(status_code=400, detail="Ungültiger Token.")

    path = _GRAPH_STORE_DIR / f"{token}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Token nicht gefunden.")
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/machine-db/{token}/replacements")
async def api_machine_db_save_replacements(token: str, request: Request):
    from fastapi import HTTPException
    
    if not token.isalnum():
        raise HTTPException(status_code=400, detail="Ungültiger Token.")
    
    raw = await request.json()
    if not isinstance(raw, list):
        raw = [raw]
        
    path = _GRAPH_STORE_DIR / f"{token}_replacements.json"
    
    # Bestehende Replacements laden und mergen (by cable_name)
    existing = []
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
    
    existing_map = {r["cable_name"]: r for r in existing}
    for item in raw:
        if "cable_name" in item:
            existing_map[item["cable_name"]] = item
    
    data = list(existing_map.values())
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    return {"status": "success", "count": len(data)}

@app.get("/api/machine-db/{token}/replacements")
async def api_machine_db_get_replacements(token: str):
    from fastapi import HTTPException
    
    if not token.isalnum():
        raise HTTPException(status_code=400, detail="Ungültiger Token.")
        
    path = _GRAPH_STORE_DIR / f"{token}_replacements.json"
    if not path.exists():
        return []
        
    return json.loads(path.read_text(encoding="utf-8"))

@app.delete("/api/machine-db/{token}/replacements")
async def api_machine_db_delete_replacements(token: str):
    from fastapi import HTTPException
    
    if not token.isalnum():
        raise HTTPException(status_code=400, detail="Ungültiger Token.")
        
    path = _GRAPH_STORE_DIR / f"{token}_replacements.json"
    if path.exists():
        path.unlink()
    return {"status": "success"}


if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
