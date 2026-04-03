"""FastAPI backend for the Leitungsquerschnitt-Optimierer web application."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from optimizer import (
    CableOption,
    InputParams,
    evaluate_all,
    find_optimum,
    payback_years,
)
from machine_db import build_machine_graph_from_json
from lapp_shop_proxy import router as shop_router

app = FastAPI(title="Leitungsquerschnitt-Optimierer")
app.include_router(shop_router)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

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

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "default_params": DEFAULT_PARAMS,
        },
    )


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    return templates.TemplateResponse(request=request, name="search.html")


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
# Database helpers
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent / "lapp_cables.db"


def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/api/products")
async def api_products():
    conn = _get_db()
    rows = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/products/{product_id}")
async def api_product_detail(product_id: int):
    conn = _get_db()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        conn.close()
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Product not found")
    cables = conn.execute(
        "SELECT * FROM cables WHERE product_id = ? ORDER BY product_variant, cross_section_mm2, num_cores",
        (product_id,),
    ).fetchall()
    conn.close()
    return {"product": dict(product), "cables": [dict(c) for c in cables]}


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
    1.5: 16, 2.5: 25, 4.0: 34, 6.0: 44, 10.0: 61, 16.0: 82,
    25.0: 108, 35.0: 135, 50.0: 168, 70.0: 207, 95.0: 250,
    120.0: 292, 150.0: 335, 185.0: 382, 240.0: 453,
}


@app.get("/api/product-cable-options/{product_id}")
async def api_product_cable_options(product_id: int):
    """Derive optimizer-ready cable options from DB data for a given product."""
    conn = _get_db()
    rows = conn.execute(
        """
        SELECT cross_section_mm2,
               AVG(copper_index_kg_km) as avg_copper
        FROM cables
        WHERE product_id = ? AND cross_section_mm2 IS NOT NULL AND cross_section_mm2 > 0
        GROUP BY cross_section_mm2
        ORDER BY cross_section_mm2
        """,
        (product_id,),
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        cs = r["cross_section_mm2"]
        copper = r["avg_copper"]
        resistance = STANDARD_RESISTANCE_OHM_PER_KM.get(
            cs, round(17.241 / cs, 3) if cs > 0 else 0
        )
        ampacity = STANDARD_AMPACITY_A.get(cs)
        default = next(
            (d for d in DEFAULT_OPTIONS if d["cross_section_mm2"] == cs), None
        )
        price = default["cable_price_eur_per_m"] if default else 0
        copper_val = (
            round(copper, 1)
            if copper
            else (default["copper_mass_kg_per_km"] if default else 0)
        )
        result.append(
            {
                "cross_section_mm2": cs,
                "resistance_ohm_per_km": resistance,
                "copper_mass_kg_per_km": copper_val,
                "cable_price_eur_per_m": price,
                "ampacity_a": ampacity,
            }
        )
    return result


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


if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
