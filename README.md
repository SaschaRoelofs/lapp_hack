# LAPP Leitungsquerschnitt-Optimierer

**LAPP Hackathon 2026** · TCO- & CO₂-Optimierung von Kupferleitungen

---

## Team

| <img src="static/team/sascha.jpg" width="150"> | <img src="static/team/morelle.jpeg" width="150"> | <img src="static/team/tobias.jpg" width="150"> |
|:---:|:---:|:---:|
| **Sascha Roelofs** | **Morelle Fopa Mamene** | **Tobias Eglseder** |
| Informatik | Computer Engineering | Management |
| Hochschule Aalen | VDI / Universität Duisburg-Essen | JBT |

---

## Challenge

Maschinen- und Anlagenbauer wählen bei der Planung oft den **kleinstmöglichen Kabelquerschnitt** nach Norm, um Anschaffungskosten zu minimieren – die sogenannte **CAPEX-Falle**. Über die Lebensdauer einer Anlage (10–30 Jahre) übersteigen die vermeidbaren Energieverluste durch den höheren Widerstand jedoch den Einkaufspreis um ein Vielfaches. Gleichzeitig steigen die CO₂-Emissionen durch die dauerhaften Stromverluste massiv an.

**Die Leitfrage:** Wie können die finanziellen und ökologischen Vorteile optimierter Kabelquerschnitte auf Basis von Kabelparametern, Anlagendaten und Marktwerten transparent dargestellt werden – und so die rein einkaufsorientierte Entscheidungslogik durchbrochen werden?

Dieses Tool ist unser Prototyp als Antwort auf diese Challenge.

---

## Überblick

Dieses Tool hilft Maschinen- und Anlagenbauern, den wirtschaftlich und ökologisch optimalen Leitungsquerschnitt für Kupferkabel zu bestimmen. Es kombiniert Live-Produktdaten aus dem LAPP Online Shop, eine EPLAN-basierte Maschinenvisualisierung und eine präzise TCO/CO₂-Kalkulation.

---

## Features

### Leitungsquerschnitt-Optimierer
- Berechnung von **TCO** (Total Cost of Ownership) und **CO₂-Gesamtemissionen** für alle verfügbaren Querschnitte
- Berücksichtigt Kupferinitialkostenanteil, Betriebsverluste und Energiekosten über die gesamte Nutzungsdauer
- **Amortisationsrechnung**: Wann lohnt sich ein größerer Querschnitt gegenüber dem minimal zulässigen?
- Interaktive Diagramme: TCO-Aufschlüsselung, CO₂-Aufschlüsselung, Spannungsfall und Amortisationsverlauf
- Live-Kabeldaten direkt vom LAPP Shop (Querschnitte, Widerstände, Gewichte, Preise)
- Filtert automatisch unzulässige Varianten (Strombelastbarkeit, Spannungsfall)

### Maschinenvisualisierung
- Import von **EPLAN-Projektexporten** (JSON) per Token oder Datei-Upload
- Interaktiver Schaltplan-Graph mit Dagre-Layout, Pan & Zoom
- Darstellung von Subsystemen, Funktionsgruppen und Kabelverbindungen
- Klick auf ein Kabel öffnet eine Detailansicht inkl. integriertem Optimierer
- Typbasierte Farbkodierung (Motor, Sensor, Schutz, Steuerung, …)

### LAPP Shop Integration
- Volltextsuche über alle LAPP-Produkte (ÖLFLEX, UNITRONIC, H07V-K, …)
- Produktdetailseite mit Varianten, Zertifizierungen, Eigenschaften, Vorteilen
- Preisladen on demand, Sortierfunktion nach Querschnitt, Preis, Gewicht u.a.

### Einstellungen
- Strompreis [€/kWh]
- Maximaler Spannungsfall [%]
- CO₂-Emissionsfaktor Strom [kg CO₂/kWh]
- CO₂-Emissionsfaktor Kupfer [kg CO₂/kg]
- Alle Werte werden im Browser (localStorage) gespeichert

---

## Mathematisches Modell

Die Verlustleistung pro Kabel:

$$P_{loss} = I^2 \cdot R_{total} \cdot n_{cores}$$

mit $R_{total} = \frac{R_{km}}{1000} \cdot L$

Energieverluste über die Nutzungsdauer:

$$E_{loss} = P_{loss} \cdot h_{day} \cdot d_{year} \cdot y \cdot \frac{1}{1000}\ [\text{kWh}]$$

Total Cost of Ownership:

$$TCO = C_{cable} + C_{loss} = C_{cable} + E_{loss} \cdot p_{energy}$$

CO₂-Gesamtemissionen:

$$CO_{2,total} = m_{Cu} \cdot f_{Cu} + E_{loss} \cdot f_{el}$$

Spannungsfall (3-phasig AC):

$$\Delta U = \sqrt{3} \cdot I \cdot R_{total}$$

---

## Technologie-Stack

| Schicht | Technologie |
|---|---|
| Backend | Python · FastAPI |
| Frontend | HTML · Tailwind CSS · Alpine.js · Chart.js · Dagre |
| Daten | LAPP OCC REST API · EPLAN JSON Export |

---

## Installation & Start

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt

# Server starten
python -m uvicorn app:app --reload
```

Danach ist die Anwendung unter **http://localhost:8000** erreichbar.

---

## Seiten

| Pfad | Beschreibung |
|---|---|
| `/` | Diese Startseite |
| `/optimizer` | Leitungsquerschnitt-Optimierer |
| `/machine` | Maschinenvisualisierung (EPLAN-Import) |
| `/search` | LAPP Online Shop Suche |
| `/settings` | Einstellungen (Strom- & CO₂-Preise) |

---

## API-Endpunkte

| Methode | Pfad | Beschreibung |
|---|---|---|
| `POST` | `/api/calculate` | TCO/CO₂-Berechnung für Kabeloptionen |
| `GET` | `/api/shop/search` | Produktsuche im LAPP Shop |
| `GET` | `/api/shop/product/{code}` | Produktdetails & Varianten |
| `GET` | `/api/shop/product/{code}/prices` | Live-Preise für alle Varianten |
| `GET` | `/api/shop/product/{code}/cable-options` | Kabeloptionen für Optimierer |
| `GET` | `/api/machine-db` | Maschinengraph aus EPLAN-Export |
| `GET` | `/health` | Liveness-Check |

---

## Projektstruktur

```
app.py                  # FastAPI-Anwendung & API-Endpunkte
optimizer.py            # Berechnungslogik (TCO, CO₂, Amortisation)
machine_db.py           # EPLAN-JSON-Parser & Graphaufbau
lapp_shop_proxy.py      # LAPP Shop OCC REST API Proxy
templates/
  index.html            # Startseite (diese Seite)
  optimizer.html        # Leitungsquerschnitt-Optimierer
  machine.html          # Maschinenvisualisierung
  search.html           # Shop-Suche
  settings.html         # Einstellungen
graph_store/            # Gespeicherte Maschinengraphen (JSON)
```

---

*LAPP Hackathon 2026 · Leitungsquerschnitt-Optimierer*
