"""
Optimierung des Leitungsquerschnitts nach dem im Whitepaper beschriebenen Ansatz.

Das Skript berechnet für eine Menge möglicher Querschnitte:
- Verlustleistung
- Energieverluste über die Nutzungsdauer
- Verlustkosten
- initiale Kupfer-CO2-Emissionen
- CO2-Emissionen aus den Verlusten
- TCO
- optimales Ergebnis für TCO und CO2

Wichtige Modellannahmen entsprechend Whitepaper:
- konstantes Lastprofil
- konstante Temperatur
- 2 oder 3 belastete Adern
- Fokus auf Kupferanteil + Betriebsverluste
- diskrete Querschnittsklassen

Hinweise:
- Widerstand wird als Leiterwiderstand pro km pro Ader eingegeben.
- Preise und Kupfermassen müssen kabelspezifisch gepflegt werden.
- Normprüfung ist optional und bewusst vereinfacht.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional
import math


@dataclass(frozen=True)
class CableOption:
    cross_section_mm2: float
    resistance_ohm_per_km: float
    copper_mass_kg_per_km: float
    cable_price_eur_per_m: float
    ampacity_a: Optional[float] = None


@dataclass
class InputParams:
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


@dataclass
class ResultRow:
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


def calc_voltage_drop_v(
    current_a: float,
    r_total_ohm_per_core: float,
    loaded_cores: int,
    system_voltage_v: Optional[float],
    ac_3phase: bool,
) -> tuple[Optional[float], Optional[float]]:
    if system_voltage_v is None:
        return None, None

    # Vereinfachtes Modell ohne Reaktanz:
    # DC / 1-ph / 2 belastete Adern: DeltaU = 2 * I * R
    # 3-ph symmetrisch: DeltaU = sqrt(3) * I * R
    if ac_3phase and loaded_cores == 3:
        delta_u = math.sqrt(3) * current_a * r_total_ohm_per_core
    else:
        delta_u = 2.0 * current_a * r_total_ohm_per_core

    delta_u_percent = delta_u / system_voltage_v * 100.0
    return delta_u, delta_u_percent


def evaluate_option(option: CableOption, params: InputParams) -> ResultRow:
    r_total_ohm_per_core = option.resistance_ohm_per_km * (params.length_m / 1000.0)

    # Whitepaper: P_loss = n * R_L * I^2
    p_loss_w = params.loaded_cores * r_total_ohm_per_core * (params.current_a ** 2)

    operating_hours = params.years * params.days_per_year * params.hours_per_day
    energy_loss_kwh = (p_loss_w / 1000.0) * operating_hours

    cable_price_eur = option.cable_price_eur_per_m * params.length_m
    loss_cost_eur = energy_loss_kwh * params.energy_price_eur_per_kwh
    tco_eur = cable_price_eur + loss_cost_eur

    copper_mass_total_kg = option.copper_mass_kg_per_km * (params.length_m / 1000.0)
    co2_initial_kg = copper_mass_total_kg * params.copper_emission_factor_kg_per_kg
    co2_loss_kg = energy_loss_kwh * params.electricity_emission_factor_kg_per_kwh
    co2_total_kg = co2_initial_kg + co2_loss_kg

    voltage_drop_v, voltage_drop_percent = calc_voltage_drop_v(
        current_a=params.current_a,
        r_total_ohm_per_core=r_total_ohm_per_core,
        loaded_cores=params.loaded_cores,
        system_voltage_v=params.system_voltage_v,
        ac_3phase=params.ac_3phase,
    )

    admissible = True
    reasons: List[str] = []

    if option.ampacity_a is not None and params.current_a > option.ampacity_a:
        admissible = False
        reasons.append(
            f"Strombelastbarkeit überschritten ({params.current_a:.1f} A > {option.ampacity_a:.1f} A)"
        )

    if (
        params.max_voltage_drop_percent is not None
        and voltage_drop_percent is not None
        and voltage_drop_percent > params.max_voltage_drop_percent
    ):
        admissible = False
        reasons.append(
            f"Spannungsfall überschritten ({voltage_drop_percent:.2f} % > {params.max_voltage_drop_percent:.2f} %)"
        )

    return ResultRow(
        cross_section_mm2=option.cross_section_mm2,
        admissible=admissible,
        rejection_reason="; ".join(reasons),
        r_total_ohm_per_core=r_total_ohm_per_core,
        p_loss_w=p_loss_w,
        energy_loss_kwh=energy_loss_kwh,
        cable_price_eur=cable_price_eur,
        loss_cost_eur=loss_cost_eur,
        tco_eur=tco_eur,
        copper_mass_total_kg=copper_mass_total_kg,
        co2_initial_kg=co2_initial_kg,
        co2_loss_kg=co2_loss_kg,
        co2_total_kg=co2_total_kg,
        voltage_drop_v=voltage_drop_v,
        voltage_drop_percent=voltage_drop_percent,
    )


def evaluate_all(options: Iterable[CableOption], params: InputParams) -> List[ResultRow]:
    rows = [evaluate_option(opt, params) for opt in options]
    rows.sort(key=lambda r: r.cross_section_mm2)
    return rows


def find_optimum(rows: List[ResultRow], target: str) -> ResultRow:
    valid_rows = [r for r in rows if r.admissible]
    if not valid_rows:
        raise ValueError("Kein zulässiger Querschnitt gefunden.")
    if target == "tco":
        return min(valid_rows, key=lambda r: r.tco_eur)
    if target == "co2":
        return min(valid_rows, key=lambda r: r.co2_total_kg)
    raise ValueError("target muss 'tco' oder 'co2' sein")


def payback_years(reference: ResultRow, candidate: ResultRow, params: InputParams) -> Optional[float]:
    additional_invest = candidate.cable_price_eur - reference.cable_price_eur
    annual_saving = (reference.loss_cost_eur - candidate.loss_cost_eur) / max(params.years, 1e-12)

    if additional_invest <= 0:
        return 0.0
    if annual_saving <= 0:
        return None
    return additional_invest / annual_saving


def print_table(rows: List[ResultRow]) -> None:
    header = (
        f"{'mm²':>6} {'zul.':>5} {'P_loss W':>12} {'E_loss kWh':>12} "
        f"{'Preis €':>10} {'Verlust €':>12} {'TCO €':>12} "
        f"{'CO2 init':>10} {'CO2 loss':>10} {'CO2 total':>11} {'dU %':>8}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        du = f"{r.voltage_drop_percent:.2f}" if r.voltage_drop_percent is not None else "-"
        print(
            f"{r.cross_section_mm2:>6.1f} "
            f"{('ja' if r.admissible else 'nein'):>5} "
            f"{r.p_loss_w:>12.1f} "
            f"{r.energy_loss_kwh:>12.1f} "
            f"{r.cable_price_eur:>10.2f} "
            f"{r.loss_cost_eur:>12.2f} "
            f"{r.tco_eur:>12.2f} "
            f"{r.co2_initial_kg:>10.1f} "
            f"{r.co2_loss_kg:>10.1f} "
            f"{r.co2_total_kg:>11.1f} "
            f"{du:>8}"
        )
        if not r.admissible and r.rejection_reason:
            print(f"      -> {r.rejection_reason}")


def main() -> None:
    # Beispielkonfiguration
    # Diese Daten bitte auf dein tatsächliches Kabel/Datenblatt anpassen.
    options = [
        CableOption(1.5, resistance_ohm_per_km=13.3, copper_mass_kg_per_km=43.0, cable_price_eur_per_m=1.70, ampacity_a=16),
        CableOption(2.5, resistance_ohm_per_km=7.98, copper_mass_kg_per_km=96.0, cable_price_eur_per_m=2.49, ampacity_a=25),
        CableOption(4.0, resistance_ohm_per_km=4.95, copper_mass_kg_per_km=150.0, cable_price_eur_per_m=3.15, ampacity_a=34),
        CableOption(6.0, resistance_ohm_per_km=3.30, copper_mass_kg_per_km=230.0, cable_price_eur_per_m=4.40, ampacity_a=44),
        CableOption(10.0, resistance_ohm_per_km=1.91, copper_mass_kg_per_km=360.0, cable_price_eur_per_m=6.90, ampacity_a=61),
        CableOption(16.0, resistance_ohm_per_km=1.21, copper_mass_kg_per_km=565.0, cable_price_eur_per_m=10.20, ampacity_a=82),
        CableOption(25.0, resistance_ohm_per_km=0.780, copper_mass_kg_per_km=860.0, cable_price_eur_per_m=15.90, ampacity_a=108),
        CableOption(35.0, resistance_ohm_per_km=0.554, copper_mass_kg_per_km=1200.0, cable_price_eur_per_m=21.80, ampacity_a=135),
        CableOption(50.0, resistance_ohm_per_km=0.386, copper_mass_kg_per_km=1700.0, cable_price_eur_per_m=30.00, ampacity_a=168),
    ]

    params = InputParams(
        length_m=50.0,
        current_a=16.0,
        total_cores=4,
        loaded_cores=3,
        years=10.0,
        days_per_year=220.0,
        hours_per_day=16.0,
        energy_price_eur_per_kwh=0.35,
        electricity_emission_factor_kg_per_kwh=0.368,
        copper_emission_factor_kg_per_kg=3.956,
        max_voltage_drop_percent=3.0,
        system_voltage_v=400.0,
        ac_3phase=True,
    )

    rows = evaluate_all(options, params)
    print_table(rows)

    best_tco = find_optimum(rows, "tco")
    best_co2 = find_optimum(rows, "co2")

    admissible_rows = [r for r in rows if r.admissible]
    smallest_admissible = min(admissible_rows, key=lambda r: r.cross_section_mm2)

    print("\nErgebnis")
    print("--------")
    print(
        f"Minimal zulässiger Querschnitt: {smallest_admissible.cross_section_mm2:.1f} mm² "
        f"(TCO {smallest_admissible.tco_eur:.2f} €, CO2 {smallest_admissible.co2_total_kg:.1f} kg)"
    )
    print(
        f"TCO-optimaler Querschnitt:      {best_tco.cross_section_mm2:.1f} mm² "
        f"(TCO {best_tco.tco_eur:.2f} €, CO2 {best_tco.co2_total_kg:.1f} kg)"
    )
    print(
        f"CO2-optimaler Querschnitt:      {best_co2.cross_section_mm2:.1f} mm² "
        f"(TCO {best_co2.tco_eur:.2f} €, CO2 {best_co2.co2_total_kg:.1f} kg)"
    )

    pb_tco = payback_years(smallest_admissible, best_tco, params)
    if pb_tco is None:
        print("Amortisation TCO-Optimum gegenüber Mindestquerschnitt: keine")
    else:
        print(f"Amortisation TCO-Optimum gegenüber Mindestquerschnitt: {pb_tco:.2f} Jahre")


if __name__ == "__main__":
    main()

