# LAPP Leitungsquerschnitt-Optimierer

**LAPP Hackathon 2026** · TCO-, CO₂- und Engineering-Workflow für bessere Kabelentscheidungen

---

## Team

| <img src="static/team/sascha.jpg" width="150"> | <img src="static/team/morelle.jpeg" width="150"> | <img src="static/team/tobias.jpg" width="150"> |
|:---:|:---:|:---:|
| **Sascha Roelofs** | **Morelle Fopa Mamene** | **Tobias Eglseder** |
| Informatik | Computer Engineering | Management |
| Hochschule Aalen | VDI / Universität Duisburg-Essen | JBT |

---

## Challenge

Maschinen- und Anlagenbauer wählen bei der Planung oft den **kleinstmöglichen Kabelquerschnitt** nach Norm, um Anschaffungskosten zu minimieren. Diese rein CAPEX-getriebene Sicht blendet jedoch die **Betriebsverluste über 10 bis 30 Jahre** weitgehend aus. Genau dort entstehen vermeidbare Energie- und CO₂-Kosten.

**Die Leitfrage:** Wie können finanzielle und ökologische Vorteile optimierter Leitungsquerschnitte transparent dargestellt werden, sodass Einkaufs-, Engineering- und Nachhaltigkeitsentscheidungen auf derselben Datengrundlage getroffen werden?

Dieses Projekt ist unser Prototyp als Antwort auf diese Challenge.

---

## Überblick

Die Anwendung kombiniert **fünf produktive Module** in einem durchgängigen Workflow:

- **Leitungsquerschnitt-Optimierer** für TCO-, CO₂-, Spannungsfall- und Amortisationsanalysen
- **LAPP Shop Suche** für Live-Produktdaten, Varianten und Preise
- **Maschinenvisualisierung** für EPLAN-Exporte als interaktiven Graph
- **Cable Wizard** für geführte Kabelbewertung direkt aus dem Maschinengraphen
- **Cable Copilot** als KI-gestützter LAPP Kabelberater mit Live-Shop-Recherche

Ergänzt wird das Ganze durch **lokal speicherbare Einstellungen**, einen **desktop-orientierten eKanban-Modus** und Exportfunktionen für **PDF-Reports** und **CSV-Ergebnisse**.

---

## End-to-End Workflow

1. **Produkt recherchieren**: Im LAPP Shop nach Kabeln oder Artikelnummern suchen.
2. **Kabel bewerten**: Varianten in den Optimierer übernehmen und wirtschaftlich wie ökologisch vergleichen.
3. **Maschine analysieren**: EPLAN-Export laden oder per Token wieder aufrufen.
4. **Verbindungen optimieren**: Im Cable Wizard einzelne Kabelstrecken mit realen Maschinenkontexten prüfen.
5. **Ergebnisse sichern**: PDF-Report, CSV-Export und gespeicherte Ersatzvorschläge weiterverwenden.

---

## Features

### Leitungsquerschnitt-Optimierer
- Berechnung von **TCO** (Total Cost of Ownership) und **CO₂-Gesamtemissionen** für alle verfügbaren Querschnitte
- Berücksichtigung von Materialkosten, Betriebsverlusten, Energiekosten und Kupfer-Emissionen
- Automatische Ermittlung von **TCO-Optimum**, **CO₂-Optimum** und **kleinstem zulässigen Querschnitt**
- **Amortisationsrechnung** gegenüber dem minimal zulässigen Querschnitt
- Filterung unzulässiger Varianten anhand von **Strombelastbarkeit** und **maximalem Spannungsfall**
- Interaktive Diagramme für TCO, CO₂, Spannungsfall und Payback-Verlauf
- **Vier vorkonfigurierte Anwendungsszenarien** aus realistischen Kundenkontexten
- **PDF-Report-Export** inklusive Management Summary und Diagrammen

### Maschinenvisualisierung
- Import von **EPLAN-Projektexporten** per JSON-Upload
- Alternativ Wiederaufruf vorhandener Daten über **Token-basierte Graph-Speicherung**
- Interaktiver Schaltplan-Graph mit **Dagre-Layout**, Zoom, Pan und Detailpanel
- Darstellung von **Subsystemen, Komponenten, Kabeln und Verbindungen**
- Typbasierte Farbcodierung für Motor, Sensor, Schutz, Steuerung, Schalter, Transformator und weitere Komponenten
- Kabel-Detailansicht mit Länge, Aderzahl, Querschnitt, Artikelnummer und Routinginformationen

### Cable Wizard
- Geführter Workflow zur Bewertung einzelner Kabelverbindungen aus dem Maschinengraphen
- Vorbelegung technischer Parameter aus dem importierten EPLAN-Datensatz
- Shop-Abgleich für erkannte Kabeltypen und Artikelnummern
- Speicherung von **Ersatz- und Optimierungsvorschlägen pro Token**
- **CSV-Export** der Wizard-Ergebnisse für weitere Auswertung

### LAPP Shop Integration
- Volltextsuche über LAPP-Produkte wie **ÖLFLEX**, **UNITRONIC**, **ETHERLINE** und weitere Familien
- Produktdetailseite mit Varianten, Zertifizierungen, Merkmalen, Nutzen und Einsatzbereichen
- **Live-Preise on demand** für Varianten
- Sortierung und Filterung nach Querschnitt, Preis, Gewicht und anderen Produktattributen
- Aufbereitung von Shop-Daten zu **optimizer-fähigen Kabeloptionen**
- Direkter Zugriff auf Varianteninformationen per Artikelnummer

### Cable Copilot
- KI-gestützter Kabelberater mit **Streaming-Antworten**
- Nutzt den LAPP Shop aktiv über **Function Calling** statt nur generischer Textantworten
- Kann Produkte suchen, Produktdetails laden und einzelne Varianten analysieren
- Speichert Chat-Verläufe lokal im Browser
- Unterstützt auch einen **embedded Modus** für Einbettung in andere Ansichten

### Einstellungen und UI
- Konfigurierbare Werte für **Strompreis**, **maximalen Spannungsfall** sowie **CO₂-Faktoren** von Strom und Kupfer
- Speicherung dieser Werte in **localStorage**
- Optionaler **eKanban UI Modus** für Desktop-Ansichten mit alternativer Navigation und Layoutstruktur
- Verstecktes **Snake-Easter-Egg** im eKanban-Layout

---

## Mathematisches Modell

Die Verlustleistung pro Kabel:

$$P_{loss} = I^2 \cdot R_{total} \cdot n_{cores}$$

mit

$$R_{total} = \frac{R_{km}}{1000} \cdot L$$

Energieverluste über die Nutzungsdauer:

$$E_{loss} = P_{loss} \cdot h_{day} \cdot d_{year} \cdot y \cdot \frac{1}{1000}\ [\text{kWh}]$$

Total Cost of Ownership:

$$TCO = C_{cable} + C_{loss} = C_{cable} + E_{loss} \cdot p_{energy}$$

CO₂-Gesamtemissionen:

$$CO_{2,total} = m_{Cu} \cdot f_{Cu} + E_{loss} \cdot f_{el}$$

Spannungsfall für 3-phasige AC-Systeme:

$$\Delta U = \sqrt{3} \cdot I \cdot R_{total}$$

Vereinfachtes Modell für DC bzw. 1-phasige Strecken:

$$\Delta U = 2 \cdot I \cdot R_{total}$$

---

## Technologie-Stack

| Schicht | Technologie |
|---|---|
| Backend | Python · FastAPI |
| Frontend | HTML · Tailwind CSS · Alpine.js |
| Visualisierung | Chart.js · Dagre |
| Dokumente | jsPDF · jsPDF-AutoTable · Markdown · KaTeX |
| Datenquellen | LAPP OCC REST API · EPLAN JSON Export |
| KI | OpenRouter / OpenAI-kompatibles API für Cable Copilot |

---

## Installation und Start

```bash
# Virtuelle Umgebung anlegen (optional, aber empfohlen)
python -m venv .venv

# Windows
.venv\Scripts\activate

# Abhängigkeiten installieren
pip install -r src/requirements.txt

# Server starten
python -m uvicorn src.app:app --reload
```

Danach ist die Anwendung unter **http://localhost:8000** erreichbar.

### Optional für den Cable Copilot

Für die Seite `/copilot` muss ein gültiger **OPENROUTER_API_KEY** als Umgebungsvariable oder in einer `.env` Datei gesetzt sein.

---

## Seiten

| Pfad | Beschreibung |
|---|---|
| `/` | Startseite mit Hero, Schnellzugriffen und gerendertem README |
| `/optimizer` | Leitungsquerschnitt-Optimierer mit Szenarien, Charts und PDF-Report |
| `/machine` | Maschinenvisualisierung mit EPLAN-Import, Detailpanel und Cable Wizard |
| `/search` | LAPP Shop Suche mit Produktdetails, Varianten und Live-Preisen |
| `/copilot` | KI-gestützter Cable Copilot mit Streaming-Chat |
| `/settings` | Einstellungen für Energie-, Spannungsfall- und CO₂-Parameter |
| `/snake` | Verstecktes Snake-Easter-Egg aus dem eKanban-Modus |

---

## API-Endpunkte

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` / `HEAD` | `/health` | Liveness-Check |
| `POST` | `/api/calculate` | TCO- und CO₂-Berechnung für Kabeloptionen |
| `GET` | `/api/machine-db` | Standard-Maschinengraph aus Beispiel-Export laden |
| `POST` | `/api/machine-db` | EPLAN-Export hochladen und Token erzeugen |
| `GET` | `/api/machine-db/{token}` | Gespeicherten Graph per Token laden |
| `POST` | `/api/machine-db/{token}/replacements` | Ersatzvorschläge für Kabel speichern |
| `GET` | `/api/machine-db/{token}/replacements` | Gespeicherte Ersatzvorschläge abrufen |
| `DELETE` | `/api/machine-db/{token}/replacements` | Gespeicherte Ersatzvorschläge löschen |
| `GET` | `/api/shop/search` | Produktsuche im LAPP Shop |
| `POST` | `/api/shop/variants/resolve` | Varianten-/Artikelnummern auflösen |
| `GET` | `/api/shop/product/{code}` | Produktdetails inklusive Varianten |
| `GET` | `/api/shop/product/{code}/cable-options` | Optimierer-kompatible Kabeloptionen aus Shopdaten ableiten |
| `GET` | `/api/shop/product/{code}/cable-options-direct` | Direkte Ableitung von Kabeloptionen aus Shopdaten |
| `GET` | `/api/shop/product/{code}/prices` | Preise aller Varianten eines Produkts laden |
| `GET` | `/api/shop/product/{code}/raw` | Rohdaten des OCC-Endpunkts abrufen |
| `GET` | `/api/shop/variant/{article_code}` | Detaildaten einer einzelnen Variante |
| `GET` | `/api/shop/variant/{article_code}/price` | Preis einer einzelnen Variante |
| `POST` | `/api/copilot/chat` | Streaming-Chat für den Cable Copilot |

---

## Daten und Persistenz

| Speicherort | Inhalt |
|---|---|
| `localStorage` | Einstellungen, eKanban-Modus, Copilot-Chatverläufe |
| `graph_store/{token}.json` | Aufbereiteter Maschinengraph |
| `graph_store/{token}_raw.json` | Ursprünglicher hochgeladener EPLAN-Export |
| `graph_store/{token}_replacements.json` | Gespeicherte Ersatz- und Optimierungsvorschläge |
| `README.md` | Single Source of Truth für den Inhalt der Startseite |

---

## Projektstruktur

```text
src/
  app.py                     # FastAPI-App, HTML-Seiten und Kernendpunkte
  optimizer.py               # TCO-, CO₂-, Spannungsfall- und Payback-Logik
  machine_db.py              # EPLAN-Parser und Graphaufbereitung
  lapp_shop_proxy.py         # Proxy und Datenaufbereitung für den LAPP Shop
  copilot.py                 # Streaming-Chat und Tool-Calling für Cable Copilot
  application_scenarios.csv  # Vorgefertigte Anwendungsszenarien
  requirements.txt           # Python-Abhängigkeiten
templates/
  index.html                 # Landingpage
  optimizer.html             # Optimierer
  machine.html               # Maschinenvisualisierung + Cable Wizard
  search.html                # Shop-Suche
  copilot.html               # Cable Copilot
  settings.html              # Einstellungen
  snake.html                 # Easter Egg
  _header.html               # Hauptnavigation
  _footer.html               # Footer
  _ekanban_skin.html         # Alternativer eKanban-Look
graph_store/                 # Persistierte Graphen, Upload-Rohdaten und Wizard-Ergebnisse
static/                      # Favicon, Team-Bilder und statische Assets
docs/                        # Projektdokumentation
LAPP_WIZARD/                 # Zusatzprojekt im EPLAN-/Wizard-Kontext
```

---

## Hinweis

Diese Website ist **kein offizielles Angebot der U.I. Lapp GmbH**, sondern ein Hackathon-Prototyp. Empfehlungen des Cable Copilot und des Optimierers ersetzen **keine Fachplanung nach VDE/IEC**.
