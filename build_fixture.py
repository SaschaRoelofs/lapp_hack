"""
Build a golden test fixture for the KKT cBoxX 100 schematic (81707601.Kd).

This manually constructs the expected MachineGraph from reading the full 55-page PDF,
so we can:
1. Test the frontend without needing the actual PDF
2. Compare against parser output to identify extraction gaps
3. Serve as regression test fixture
"""

import json
from machine_analyzer import (
    MachineGraph, Component, MachineConnection, Subsystem,
    TechnicalData, IOAssignment,
)


def build_golden_fixture() -> MachineGraph:
    graph = MachineGraph()
    graph.pages_analyzed = 55

    # ---------------------------------------------------------------
    # Technical data (from cover page, page 1)
    # ---------------------------------------------------------------
    graph.technical_data = TechnicalData(
        rated_voltage="460Y/265 V +10%, 3 phase",
        frequency="60Hz",
        control_voltage="24V DC",
        connected_load="ca. 46kW",
        full_load_current="ca. 66A",
        max_pre_fuse="Class J, 600V AC, 100A",
        enclosure_type="IP 54",
        sccr="10kA",
        model="cBoxX 100",
        project="909100-00468",
        article_no="6186220X",
        doc_no="81707601.Kd",
    )

    # ---------------------------------------------------------------
    # Components (from parts list pages 37-39 + field devices page 12)
    # ---------------------------------------------------------------
    components = [
        # --- Switches / Contactors ---
        Component(id="+SS1-Q1", designation="Q1", component_type="switch",
                  description_de="Lasttrennschalter", description_en="Switch-disconnector",
                  manufacturer="Sontheimer", order_number="HLT125/3V/Z44/Z33/X72/F803/X83",
                  technical_specs="125A", sap_number="61057701", location="+SS1",
                  subsystem="Einspeisung", page_ref="&EFS=MA1+SS1/1"),

        Component(id="+SS1-Q151", designation="Q151", component_type="switch",
                  description_de="Leistungsschütz", description_en="Power contactor",
                  manufacturer="Siemens", order_number="3RT2028-1BB40",
                  technical_specs="3p 50A AC-1/38A AC-3", sap_number="60936601", location="+SS1",
                  subsystem="Verdichter", page_ref="&EFS=MA1+SS1/18"),

        Component(id="+SS1-Q152", designation="Q152", component_type="switch",
                  description_de="Leistungsschütz", description_en="Power contactor",
                  manufacturer="Siemens", order_number="3RT2028-1BB40",
                  technical_specs="3p 50A AC-1/38A AC-3", sap_number="60936601", location="+SS1",
                  subsystem="Verdichter", page_ref="&EFS=MA1+SS1/18"),

        # --- Protection devices ---
        Component(id="+SS1-F21", designation="F21", component_type="protection",
                  description_de="Sicherungshalter", description_en="Fuse holder",
                  manufacturer="Siemens", order_number="3NW7533-0HG",
                  technical_specs="3p 30A 600V Class CC", sap_number="61123301", location="+SS1",
                  subsystem="Steuerspannung", page_ref="&EFS=MA1+SS1/2"),

        Component(id="+SS1-F22", designation="F22", component_type="protection",
                  description_de="Leitungsschutzschalter", description_en="Miniature circuit-breaker",
                  manufacturer="Siemens", order_number="5SL6104-7",
                  technical_specs="C4A", sap_number="61058401", location="+SS1",
                  subsystem="Steuerspannung", page_ref="&EFS=MA1+SS1/2"),

        Component(id="+SS1-F101", designation="F101", component_type="protection",
                  description_de="Motorschutzschalter", description_en="Motor overload switch",
                  manufacturer="Siemens", order_number="3RV2011-1KA10",
                  technical_specs="9,0...12,5 A", sap_number="60912801", location="+SS1",
                  subsystem="Kondensatorlüfter", page_ref="&EFS=MA1+SS1/15"),

        Component(id="+SS1-F151", designation="F151", component_type="protection",
                  description_de="Motorschutzschalter", description_en="Motor overload switch",
                  manufacturer="Siemens", order_number="3RV2021-4EA10",
                  technical_specs="27...32A", sap_number="67115701", location="+SS1",
                  subsystem="Verdichter", page_ref="&EFS=MA1+SS1/14"),

        Component(id="+SS1-F152", designation="F152", component_type="protection",
                  description_de="Motorschutzschalter", description_en="Motor overload switch",
                  manufacturer="Siemens", order_number="3RV2021-4EA10",
                  technical_specs="27...32A", sap_number="67115701", location="+SS1",
                  subsystem="Verdichter", page_ref="&EFS=MA1+SS1/14"),

        Component(id="+SS1-F201", designation="F201", component_type="protection",
                  description_de="Direktstarter", description_en="Direct starter",
                  manufacturer="Siemens", order_number="3RA6120-1DB32",
                  technical_specs="3...12A", sap_number="61499101", location="+SS1",
                  subsystem="Pumpe 1", page_ref="&EFS=MA1+SS1/12"),

        Component(id="+SS1-F202", designation="F202", component_type="protection",
                  description_de="Direktstarter", description_en="Direct starter",
                  manufacturer="Siemens", order_number="3RA6120-1DB32",
                  technical_specs="3...12A", sap_number="61499101", location="+SS1",
                  subsystem="Pumpe 2", page_ref="&EFS=MA1+SS1/13"),

        # --- Controllers / Relays ---
        Component(id="+SS1-K801", designation="K801", component_type="controller",
                  description_de="Steuerung", description_en="Control",
                  manufacturer="ait-deutschland GmbH", order_number="60986901",
                  technical_specs="PCB3 HIGH", sap_number="60986901", location="+SS1",
                  subsystem="Steuerung Übersicht", page_ref="&EFS=MA1+SS1/23"),

        Component(id="+SS1-K451", designation="K451", component_type="controller",
                  description_de="Relais", description_en="Relay",
                  manufacturer="Finder", order_number="38.61.0.024.0062",
                  technical_specs="1CO 6A DC-1", sap_number="65583801", location="+SS1",
                  subsystem="Steuerung DO", page_ref="&EFS=MA1+SS1/18"),

        Component(id="+SS1-A51", designation="A51", component_type="assembly",
                  description_de="Phasenausfallrelais", description_en="Phase failure relay",
                  manufacturer="Siemens", order_number="3UG4513-1BR20",
                  technical_specs="160-690V AC", sap_number="61057801", location="+SS1",
                  subsystem="Phasenüberwachung", page_ref="&EFS=MA1+SS1/4"),

        Component(id="+SS1-A801", designation="A801", component_type="assembly",
                  description_de="Bedienpanel", description_en="Control panel",
                  manufacturer="ait-deutschland GmbH", order_number="60711701",
                  technical_specs="LUX 2.0", sap_number="60711701", location="+SS1",
                  subsystem="Bedienpanel", page_ref="&EFS=MA1+SS1/16"),

        # --- Transformers / Power supplies ---
        Component(id="+SS1-T21", designation="T21", component_type="transformer",
                  description_de="Netzteil", description_en="Power supply unit",
                  manufacturer="Phoenix Contact", order_number="2904371",
                  technical_specs="24V 3,75A DC", sap_number="61360001", location="+SS1",
                  subsystem="Steuerspannung", page_ref="&EFS=MA1+SS1/2"),

        Component(id="+SS1-T42", designation="T42", component_type="transformer",
                  description_de="Netzteil", description_en="Power supply unit",
                  manufacturer="Phoenix Contact", order_number="2904371",
                  technical_specs="24V 3,75A DC", sap_number="61360001", location="+SS1",
                  subsystem="Schaltschrankheizung", page_ref="&EFS=MA1+SS1/5"),

        Component(id="+SS1-T801", designation="T801", component_type="transformer",
                  description_de="DC/DC-Wandler", description_en="DC/DC-converter",
                  manufacturer="WAGO", order_number="859-805",
                  technical_specs="24/12V 0,5A DC", sap_number="60949401", location="+SS1",
                  subsystem="Bedienpanel", page_ref="&EFS=MA1+SS1/16"),

        # --- Sensors (field devices in +MR1) ---
        Component(id="+MR1-B201", designation="B201", component_type="sensor",
                  description_de="Drucksensor Austritt Pumpe 1", description_en="Pressure sensor outlet pump 1",
                  technical_specs="0-10bar", location="+MR1",
                  subsystem="Pumpe 1", page_ref="&EFS=MA1+SS1/12"),

        Component(id="+MR1-B402", designation="B402", component_type="sensor",
                  description_de="Temperatursensor Kaltwasser Austritt", description_en="Temperature sensor cold water outlet",
                  technical_specs="PT1000", location="+MR1",
                  subsystem="Steuerung AI", page_ref="&EFS=MA1+SS1/19"),

        Component(id="+MR1-B403", designation="B403", component_type="sensor",
                  description_de="Temperatursensor Sauggas", description_en="Temperature sensor suction gas",
                  technical_specs="PT1000", location="+MR1",
                  subsystem="Steuerung AI", page_ref="&EFS=MA1+SS1/19"),

        Component(id="+MR1-B451", designation="B451", component_type="sensor",
                  description_de="Hochdruckschalter", description_en="High pressure switch",
                  technical_specs="28V / 2A DC", location="+MR1",
                  subsystem="Steuerung DO", page_ref="&EFS=MA1+SS1/18"),

        Component(id="+MR1-B452", designation="B452", component_type="sensor",
                  description_de="Drucksensor Kaltwasser Eintritt", description_en="Pressure sensor cold water inlet",
                  technical_specs="0-10bar", location="+MR1",
                  subsystem="Steuerung AI", page_ref="&EFS=MA1+SS1/19"),

        Component(id="+MR1-B453", designation="B453", component_type="sensor",
                  description_de="Drucksensor Hochdruck", description_en="Pressure sensor high pressure",
                  technical_specs="0-60bar", location="+MR1",
                  subsystem="Steuerung AI", page_ref="&EFS=MA1+SS1/19"),

        Component(id="+MR1-B454", designation="B454", component_type="sensor",
                  description_de="Drucksensor Niederdruck", description_en="Pressure sensor low pressure",
                  technical_specs="0-40bar", location="+MR1",
                  subsystem="Steuerung AI", page_ref="&EFS=MA1+SS1/19"),

        Component(id="+SS1-B42", designation="B42", component_type="sensor",
                  description_de="Schaltschrankthermostat", description_en="Control cabinet thermal switch",
                  manufacturer="STEGO Elektrotechnik GmbH", order_number="01146.9-00",
                  technical_specs="NC, 0-60°C", sap_number="66589501", location="+SS1",
                  subsystem="Schaltschrankheizung", page_ref="&EFS=MA1+SS1/5"),

        # --- Heaters ---
        Component(id="+SS1-E42", designation="E42", component_type="heater",
                  description_de="Schaltschrankheizung", description_en="Control cabinet heating",
                  manufacturer="STEGO Elektrotechnik GmbH", order_number="14012.0-00",
                  technical_specs="12-30V 45W", sap_number="60987501", location="+SS1",
                  subsystem="Schaltschrankheizung", page_ref="&EFS=MA1+SS1/5"),

        Component(id="+MR1-E251", designation="E251", component_type="heater",
                  description_de="Gehäuseheizung 1", description_en="Crank case heater 1",
                  technical_specs="480V/80W", location="+MR1",
                  subsystem="Steuerspannung", page_ref="&EFS=MA1+SS1/2"),

        Component(id="+MR1-E252", designation="E252", component_type="heater",
                  description_de="Gehäuseheizung 2", description_en="Crank case heater 2",
                  technical_specs="480V/80W", location="+MR1",
                  subsystem="Steuerspannung", page_ref="&EFS=MA1+SS1/2"),

        # --- Motors / Actuators (field devices) ---
        Component(id="+MR1-M101", designation="M101", component_type="motor",
                  description_de="Kondensatorlüfter 1", description_en="Condenser fan 1",
                  technical_specs="3,7kW 380-480V 6,0-4,7A 50/60Hz", location="+MR1",
                  subsystem="Kondensatorlüfter", page_ref="&EFS=MA1+SS1/15"),

        Component(id="+MR1-M102", designation="M102", component_type="motor",
                  description_de="Kondensatorlüfter 2", description_en="Condenser fan 2",
                  technical_specs="3,7kW 380-480V 6,0-4,7A 50/60Hz", location="+MR1",
                  subsystem="Kondensatorlüfter", page_ref="&EFS=MA1+SS1/15"),

        Component(id="+MR1-M151", designation="M151", component_type="motor",
                  description_de="Verdichter 1", description_en="Compressor 1",
                  technical_specs="380-400/460V 35A 50/60Hz", location="+MR1",
                  subsystem="Verdichter", page_ref="&EFS=MA1+SS1/14"),

        Component(id="+MR1-M152", designation="M152", component_type="motor",
                  description_de="Verdichter 2", description_en="Compressor 2",
                  technical_specs="380-400/460V 35A 50/60Hz", location="+MR1",
                  subsystem="Verdichter", page_ref="&EFS=MA1+SS1/14"),

        Component(id="+MR1-M201", designation="M201", component_type="motor",
                  description_de="Pumpe 1", description_en="Pump 1",
                  technical_specs="2,3/4kW 380-415/440-480V 5,2/6,95A 50/60Hz", location="+MR1",
                  subsystem="Pumpe 1", page_ref="&EFS=MA1+SS1/12"),

        Component(id="+MR1-M202", designation="M202", component_type="motor",
                  description_de="Pumpe 2", description_en="Pump 2",
                  technical_specs="2,3/4kW 380-415/440-480V 5,2/6,95A 50/60Hz", location="+MR1",
                  subsystem="Pumpe 2", page_ref="&EFS=MA1+SS1/13"),

        Component(id="+MR1-M352", designation="M352", component_type="motor",
                  description_de="Regelventil Heißgas Bypass", description_en="Regulating valve hot gas bypass",
                  technical_specs="24VDC", location="+MR1",
                  subsystem="Heißgas Bypass", page_ref="&EFS=MA1+SS1/7"),

        Component(id="+MR1-M354", designation="M354", component_type="motor",
                  description_de="Expansionsventil", description_en="Expansion valve",
                  technical_specs="24VDC", location="+MR1",
                  subsystem="Steuerung AO", page_ref="&EFS=MA1+SS1/20"),

        # --- Switch ---
        Component(id="+SS1-S801", designation="S801", component_type="switch",
                  description_de="Umschaltung Fernbedienung", description_en="Changeover remote control panel",
                  manufacturer="Eaton Electric GmbH", order_number="248346",
                  technical_specs="230V 16A", sap_number="61539201", location="+SS1",
                  subsystem="Bedienpanel", page_ref="&EFS=MA1+SS1/16"),
    ]
    graph.components = components

    # ---------------------------------------------------------------
    # Cable connections (from cable overview, page 52 + cable diagram pages 53-54)
    # ---------------------------------------------------------------
    connections = [
        MachineConnection(cable_name="+SS1-WA801-1", cable_type="UC900 BK", cable_spec="4x2x27/7 AWG",
                          num_cores=8, function_de="Bedienpanel", function_en="Control panel",
                          sap_number="61416001", length_m=2.25, from_component="+SS1-T801", to_component="+SS1-A801",
                          page_ref="&EFS+SS1/16.5"),

        MachineConnection(cable_name="+MR1-WB201", cable_type="UNITRONIC LiYY A", cable_spec="2x20/7 AWG",
                          num_cores=2, function_de="Drucksensor Austritt Pumpe 1", function_en="Pressure sensor outlet pump 1",
                          sap_number="61841401", from_component="+MR1-B201", to_component="+SS1-K801",
                          page_ref="&EFS+SS1/12.2"),

        MachineConnection(cable_name="+MR1-WB452", cable_type="UNITRONIC LiYY A", cable_spec="2x20/7 AWG",
                          num_cores=2, function_de="Drucksensor Kaltwasser Eintritt", function_en="Pressure sensor cold water inlet",
                          sap_number="61841401", from_component="+MR1-B452", to_component="+SS1-K801",
                          page_ref="&EFS+SS1/19.1"),

        MachineConnection(cable_name="+MR1-WB453", cable_type="UNITRONIC LiYY A", cable_spec="2x20/7 AWG",
                          num_cores=2, function_de="Drucksensor Hochdruck", function_en="Pressure sensor high pressure",
                          sap_number="61841401", from_component="+MR1-B453", to_component="+SS1-K801",
                          page_ref="&EFS+SS1/19.2"),

        MachineConnection(cable_name="+MR1-WB454", cable_type="UNITRONIC LiYY A", cable_spec="2x20/7 AWG",
                          num_cores=2, function_de="Drucksensor Niederdruck", function_en="Pressure sensor low pressure",
                          sap_number="61841401", from_component="+MR1-B454", to_component="+SS1-K801",
                          page_ref="&EFS+SS1/19.3"),

        MachineConnection(cable_name="+MR1-WE251", cable_type="ÖLFLEX 150", cable_spec="3G1,5 mm²",
                          cross_section_mm2=1.5, num_cores=3,
                          function_de="Gehäuseheizung 1", function_en="Crank case heater 1",
                          sap_number="65723901", from_component="+SS1-F21", to_component="+MR1-E251",
                          page_ref="&EFS+SS1/2.0"),

        MachineConnection(cable_name="+MR1-WE252", cable_type="ÖLFLEX 150", cable_spec="3G1,5 mm²",
                          cross_section_mm2=1.5, num_cores=3,
                          function_de="Gehäuseheizung 2", function_en="Crank case heater 2",
                          sap_number="65723901", from_component="+SS1-F21", to_component="+MR1-E252",
                          page_ref="&EFS+SS1/2.1"),

        MachineConnection(cable_name="+MR1-WM101-1", cable_type="ÖLFLEX 191", cable_spec="4G2,5 mm²",
                          cross_section_mm2=2.5, num_cores=4,
                          function_de="Kondensatorlüfter 1", function_en="Condenser fan 1",
                          sap_number="65725901", from_component="+SS1-F101", to_component="+MR1-M101",
                          page_ref="&EFS+SS1/15.1"),

        MachineConnection(cable_name="+MR1-WM101-2", cable_type="UNITRONIC LiYCY A", cable_spec="7x18/19 AWG",
                          num_cores=7,
                          function_de="Kondensatorlüfter 1 Steuerung", function_en="Condenser fan 1 control",
                          sap_number="61841501", from_component="+SS1-K801", to_component="+MR1-M101",
                          page_ref="&EFS+SS1/15.2"),

        MachineConnection(cable_name="+MR1-WM102-1", cable_type="ÖLFLEX 191", cable_spec="4G2,5 mm²",
                          cross_section_mm2=2.5, num_cores=4,
                          function_de="Kondensatorlüfter 2", function_en="Condenser fan 2",
                          sap_number="65725901", from_component="+SS1-F101", to_component="+MR1-M102",
                          page_ref="&EFS+SS1/15.6"),

        MachineConnection(cable_name="+MR1-WM102-2", cable_type="UNITRONIC LiYCY A", cable_spec="7x18/19 AWG",
                          num_cores=7,
                          function_de="Kondensatorlüfter 2 Steuerung", function_en="Condenser fan 2 control",
                          sap_number="61841501", from_component="+SS1-K801", to_component="+MR1-M102",
                          page_ref="&EFS+SS1/15.7"),

        MachineConnection(cable_name="+MR1-WM151", cable_type="ÖLFLEX 191", cable_spec="4G6 mm²",
                          cross_section_mm2=6.0, num_cores=4,
                          function_de="Verdichter 1", function_en="Compressor 1",
                          sap_number="65726501", from_component="+SS1-Q151", to_component="+MR1-M151",
                          page_ref="&EFS+SS1/14.1"),

        MachineConnection(cable_name="+MR1-WM152", cable_type="ÖLFLEX 191", cable_spec="4G6 mm²",
                          cross_section_mm2=6.0, num_cores=4,
                          function_de="Verdichter 2", function_en="Compressor 2",
                          sap_number="65726501", from_component="+SS1-Q152", to_component="+MR1-M152",
                          page_ref="&EFS+SS1/14.4"),

        MachineConnection(cable_name="+MR1-WM201", cable_type="ÖLFLEX 191", cable_spec="4G2,5 mm²",
                          cross_section_mm2=2.5, num_cores=4,
                          function_de="Pumpe 1", function_en="Pump 1",
                          sap_number="65725901", from_component="+SS1-F201", to_component="+MR1-M201",
                          page_ref="&EFS+SS1/12.6"),

        MachineConnection(cable_name="+MR1-WM202", cable_type="ÖLFLEX 191", cable_spec="4G2,5 mm²",
                          cross_section_mm2=2.5, num_cores=4,
                          function_de="Pumpe 2", function_en="Pump 2",
                          sap_number="65725901", from_component="+SS1-F202", to_component="+MR1-M202",
                          page_ref="&EFS+SS1/13.6"),

        MachineConnection(cable_name="+MR1-WM352", cable_type="ÖLFLEX 150", cable_spec="5G1 mm²",
                          cross_section_mm2=1.0, num_cores=5,
                          function_de="Regelventil Heißgas Bypass", function_en="Regulating valve hot gas bypass",
                          sap_number="65724401", from_component="+SS1-K801", to_component="+MR1-M352",
                          page_ref="&EFS+SS1/7.5"),

        MachineConnection(cable_name="+MR1-WM354", cable_type="ÖLFLEX 150", cable_spec="5G1 mm²",
                          cross_section_mm2=1.0, num_cores=5,
                          function_de="Expansionsventil", function_en="Expansion valve",
                          sap_number="65724401", from_component="+SS1-K801", to_component="+MR1-M354",
                          page_ref="&EFS+SS1/20.4"),

        # --- Internal wiring (within cabinet, no external cable) ---
        # These are wire connections between components on the same mounting panel

        # Power supply chain: Q1 → F21 → T21 (24V DC power supply)
        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="10 AWG BK",
                          function_de="Einspeisung → Sicherung", function_en="Power supply → Fuse",
                          from_component="+SS1-Q1", to_component="+SS1-F21", page_ref="&EFS=MA1+SS1/2"),

        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="16 AWG BK",
                          function_de="Sicherung → Netzteil 24V", function_en="Fuse → PSU 24V",
                          from_component="+SS1-F21", to_component="+SS1-T21", page_ref="&EFS=MA1+SS1/2"),

        # T21 → F22 → XDS1 (24V distribution)
        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="18 AWG DKBU",
                          function_de="Netzteil → Sicherung 24V", function_en="PSU → 24V fuse",
                          from_component="+SS1-T21", to_component="+SS1-F22", page_ref="&EFS=MA1+SS1/2"),

        # Phase monitoring: Q1 → A51 (phase failure relay)
        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="16 AWG BK",
                          function_de="Phasenüberwachung", function_en="Phase monitoring",
                          from_component="+SS1-Q1", to_component="+SS1-A51", page_ref="&EFS=MA1+SS1/4"),

        # A51 → K801:DI1 (phase monitoring signal)
        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="18 AWG DKBU",
                          function_de="Phasenrelais → Steuerung", function_en="Phase relay → Controller",
                          from_component="+SS1-A51", to_component="+SS1-K801", page_ref="&EFS=MA1+SS1/4"),

        # Cabinet heating: T42 → B42 → E42
        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="16 AWG BK",
                          function_de="Netzteil Heizung", function_en="Heater PSU",
                          from_component="+SS1-F21", to_component="+SS1-T42", page_ref="&EFS=MA1+SS1/5"),

        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="18 AWG DKBU",
                          function_de="Thermostat → Heizung", function_en="Thermostat → Heater",
                          from_component="+SS1-B42", to_component="+SS1-E42", page_ref="&EFS=MA1+SS1/5"),

        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="18 AWG DKBU",
                          function_de="Netzteil → Thermostat", function_en="PSU → Thermostat",
                          from_component="+SS1-T42", to_component="+SS1-B42", page_ref="&EFS=MA1+SS1/5"),

        # Compressor protection chain: F151 → Q151, F152 → Q152
        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="Sammelschiene",
                          function_de="Motorschutz → Schütz Verdichter 1", function_en="Overload → Contactor compressor 1",
                          from_component="+SS1-F151", to_component="+SS1-Q151", page_ref="&EFS=MA1+SS1/14"),

        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="Sammelschiene",
                          function_de="Motorschutz → Schütz Verdichter 2", function_en="Overload → Contactor compressor 2",
                          from_component="+SS1-F152", to_component="+SS1-Q152", page_ref="&EFS=MA1+SS1/14"),

        # K801 → K451 (relay for high pressure)
        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="18 AWG DKBU",
                          function_de="Steuerung → Hochdruckrelais", function_en="Controller → HP relay",
                          from_component="+SS1-K801", to_component="+SS1-K451", page_ref="&EFS=MA1+SS1/18"),

        # K451 → Q151/Q152 (relay enables compressor contactors)
        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="18 AWG DKBU",
                          function_de="Hochdruckrelais → Schütz V1", function_en="HP relay → Contactor C1",
                          from_component="+SS1-K451", to_component="+SS1-Q151", page_ref="&EFS=MA1+SS1/18"),

        # B451 high pressure switch → K801:ES1 (via terminal XD2)
        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="18 AWG DKBU",
                          function_de="Hochdruckschalter → Steuerung", function_en="HP switch → Controller",
                          from_component="+MR1-B451", to_component="+SS1-K801", page_ref="&EFS=MA1+SS1/18"),

        # Temperature sensors → K801 (via terminal XD2)
        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="18 AWG WH",
                          function_de="Temp.sensor KW Austritt → Steuerung", function_en="Temp sensor CW outlet → Controller",
                          from_component="+MR1-B402", to_component="+SS1-K801", page_ref="&EFS=MA1+SS1/19"),

        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="18 AWG WH",
                          function_de="Temp.sensor Sauggas → Steuerung", function_en="Temp sensor suction gas → Controller",
                          from_component="+MR1-B403", to_component="+SS1-K801", page_ref="&EFS=MA1+SS1/19"),

        # S801 remote switch → A801 panel
        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="18 AWG DKBU",
                          function_de="Umschalter → Bedienpanel", function_en="Switch → Control panel",
                          from_component="+SS1-S801", to_component="+SS1-A801", page_ref="&EFS=MA1+SS1/16"),

        # F151/F152 status → K801:DI5
        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="18 AWG DKBU",
                          function_de="Motorschutz V1 → Steuerung", function_en="Overload C1 → Controller",
                          from_component="+SS1-F151", to_component="+SS1-K801", page_ref="&EFS=MA1+SS1/14"),

        MachineConnection(cable_name="intern", cable_type="Verdrahtung", cable_spec="18 AWG DKBU",
                          function_de="Motorschutz V2 → Steuerung", function_en="Overload C2 → Controller",
                          from_component="+SS1-F152", to_component="+SS1-K801", page_ref="&EFS=MA1+SS1/14"),
    ]
    graph.connections = connections

    # ---------------------------------------------------------------
    # Subsystems (from TOC pages 4-6)
    # ---------------------------------------------------------------
    subsystems = [
        Subsystem(name="Einspeisung", name_en="Power supply", page_ref=1,
                  component_ids=["+SS1-Q1"]),
        Subsystem(name="Steuerspannung", name_en="Control voltage", page_ref=2,
                  component_ids=["+SS1-F21", "+SS1-F22", "+SS1-T21", "+MR1-E251", "+MR1-E252"]),
        Subsystem(name="Verteilung PE", name_en="Distribution PE", page_ref=3,
                  component_ids=[]),
        Subsystem(name="Phasenüberwachung", name_en="Phase monitoring", page_ref=4,
                  component_ids=["+SS1-A51"]),
        Subsystem(name="Schaltschrankheizung", name_en="Control cabinet heating", page_ref=5,
                  component_ids=["+SS1-T42", "+SS1-B42", "+SS1-E42"]),
        Subsystem(name="Tankheizung", name_en="Tank heater", page_ref=6,
                  component_ids=[]),
        Subsystem(name="Heißgas Bypass", name_en="Hot gas bypass", page_ref=7,
                  component_ids=["+MR1-M352"]),
        Subsystem(name="Automatische Nachspeisung", name_en="Automatic feeding", page_ref=8,
                  component_ids=[]),
        Subsystem(name="Energiesparsystem", name_en="Energy-saving system", page_ref=9,
                  component_ids=[]),
        Subsystem(name="Leitfähigkeit", name_en="Conductivity", page_ref=10,
                  component_ids=[]),
        Subsystem(name="Motorklappe", name_en="Motor flap", page_ref=11,
                  component_ids=[]),
        Subsystem(name="Pumpe 1", name_en="Pump 1", page_ref=12,
                  component_ids=["+SS1-F201", "+MR1-M201", "+MR1-B201"]),
        Subsystem(name="Pumpe 2", name_en="Pump 2", page_ref=13,
                  component_ids=["+SS1-F202", "+MR1-M202"]),
        Subsystem(name="Verdichter", name_en="Compressor", page_ref=14,
                  component_ids=["+SS1-F151", "+SS1-F152", "+SS1-Q151", "+SS1-Q152", "+MR1-M151", "+MR1-M152"]),
        Subsystem(name="Kondensatorlüfter", name_en="Condenser fan", page_ref=15,
                  component_ids=["+SS1-F101", "+MR1-M101", "+MR1-M102"]),
        Subsystem(name="Bedienpanel", name_en="Control panel", page_ref=16,
                  component_ids=["+SS1-A801", "+SS1-S801", "+SS1-T801"]),
        Subsystem(name="Steuerung Ub", name_en="Control Ub", page_ref=17,
                  component_ids=["+SS1-K801"]),
        Subsystem(name="Steuerung DO", name_en="Control DO", page_ref=18,
                  component_ids=["+SS1-K451", "+MR1-B451"]),
        Subsystem(name="Steuerung AI", name_en="Control AI", page_ref=19,
                  component_ids=["+MR1-B452", "+MR1-B453", "+MR1-B454", "+MR1-B402", "+MR1-B403"]),
        Subsystem(name="Steuerung AO", name_en="Control AO", page_ref=20,
                  component_ids=["+MR1-M354"]),
        Subsystem(name="Interface", name_en="Interface", page_ref=21,
                  component_ids=[]),
        Subsystem(name="Steuerung Übersicht", name_en="Control overview", page_ref=23,
                  component_ids=["+SS1-K801"]),
    ]
    graph.subsystems = subsystems

    # ---------------------------------------------------------------
    # I/O assignments for K801 (from control overview pages 35-36)
    # ---------------------------------------------------------------
    io_assignments = [
        # DI1
        IOAssignment(controller_id="K801", connector="DI1", pin="1", signal_type="DI",
                     function_de="Fernstart 1", function_en="Remote start 1",
                     target_component="Interface", page_ref="/21.4"),
        IOAssignment(controller_id="K801", connector="DI1", pin="2", signal_type="DI",
                     function_de="Fernstart 1", function_en="Remote start 1", page_ref="/21.4"),
        IOAssignment(controller_id="K801", connector="DI1", pin="5", signal_type="DI",
                     function_de="Tankheizung", function_en="Tank heater", page_ref="/6.2"),
        IOAssignment(controller_id="K801", connector="DI1", pin="7", signal_type="DI",
                     function_de="Tankheizung", function_en="Tank heater", page_ref="/6.3"),
        IOAssignment(controller_id="K801", connector="DI1", pin="9", signal_type="DI",
                     function_de="Phasenüberwachung", function_en="Phase monitoring",
                     target_component="A51", page_ref="/4.5"),

        # DI2
        IOAssignment(controller_id="K801", connector="DI2", pin="1", signal_type="DI",
                     function_de="Direktstarter Pumpe 1", function_en="Direct starter pump 1",
                     target_component="F201", page_ref="/12.4"),
        IOAssignment(controller_id="K801", connector="DI2", pin="3", signal_type="DI",
                     function_de="Direktstarter Pumpe 1", function_en="Direct starter pump 1",
                     target_component="F201", page_ref="/12.3"),
        IOAssignment(controller_id="K801", connector="DI2", pin="5", signal_type="DI",
                     function_de="Fernstart 2", function_en="Remote start 2", page_ref="/21.5"),

        # DI3
        IOAssignment(controller_id="K801", connector="DI3", pin="1", signal_type="DI",
                     function_de="Direktstarter Pumpe 2", function_en="Direct starter pump 2",
                     target_component="F202", page_ref="/13.4"),
        IOAssignment(controller_id="K801", connector="DI3", pin="3", signal_type="DI",
                     function_de="Direktstarter Pumpe 2", function_en="Direct starter pump 2",
                     target_component="F202", page_ref="/13.3"),

        # DI4
        IOAssignment(controller_id="K801", connector="DI4", pin="1", signal_type="DI",
                     function_de="Motorschutzschalter Kondensatorlüfter 1", function_en="Motor overload switch condenser fan 1",
                     target_component="F101", page_ref="/15.0"),
        IOAssignment(controller_id="K801", connector="DI4", pin="3", signal_type="DI",
                     function_de="Störung Kondensatorlüfter 1", function_en="Fault condenser fan 1",
                     target_component="M101", page_ref="/15.3"),
        IOAssignment(controller_id="K801", connector="DI4", pin="5", signal_type="DI",
                     function_de="Motorschutzschalter Kondensatorlüfter 2", function_en="Motor overload switch condenser fan 2",
                     target_component="F101", page_ref="/15.5"),
        IOAssignment(controller_id="K801", connector="DI4", pin="7", signal_type="DI",
                     function_de="Störung Kondensatorlüfter 2", function_en="Fault condenser fan 2",
                     target_component="M102", page_ref="/15.8"),

        # DI5
        IOAssignment(controller_id="K801", connector="DI5", pin="1", signal_type="DI",
                     function_de="Motorschutzschalter Verdichter 1", function_en="Motor overload switch compressor 1",
                     target_component="F151", page_ref="/14.0"),
        IOAssignment(controller_id="K801", connector="DI5", pin="3", signal_type="DI",
                     function_de="Motorschutzschalter Verdichter 2", function_en="Motor overload switch compressor 2",
                     target_component="F152", page_ref="/14.2"),

        # DO1
        IOAssignment(controller_id="K801", connector="DO1", pin="1", signal_type="DO",
                     function_de="Pumpe 1", function_en="Pump 1",
                     target_component="F201", page_ref="/12.8"),
        IOAssignment(controller_id="K801", connector="DO1", pin="3", signal_type="DO",
                     function_de="Pumpe 2", function_en="Pump 2",
                     target_component="F202", page_ref="/13.8"),
        IOAssignment(controller_id="K801", connector="DO1", pin="5", signal_type="DO",
                     function_de="Freigabe Kondensatorlüfter 1", function_en="Release condenser fan 1",
                     target_component="M101", page_ref="/15.2"),
        IOAssignment(controller_id="K801", connector="DO1", pin="7", signal_type="DO",
                     function_de="Freigabe Kondensatorlüfter 2", function_en="Release condenser fan 2",
                     target_component="M102", page_ref="/15.7"),

        # DO2
        IOAssignment(controller_id="K801", connector="DO2", pin="1", signal_type="DO",
                     function_de="Warnmeldung", function_en="Warning message", page_ref="/22.6"),

        # DO4
        IOAssignment(controller_id="K801", connector="DO4", pin="1", signal_type="DO",
                     function_de="Multifunktionsausgang", function_en="Multi-functional outlet", page_ref="/22.3"),
        IOAssignment(controller_id="K801", connector="DO4", pin="3", signal_type="DO",
                     function_de="Heißgas Bypass", function_en="Hot gas bypass",
                     target_component="M352", page_ref="/7.4"),
        IOAssignment(controller_id="K801", connector="DO4", pin="7", signal_type="DO",
                     function_de="Automatische Nachspeisung", function_en="Automatic feeding", page_ref="/8.5"),

        # DO5
        IOAssignment(controller_id="K801", connector="DO5", pin="1", signal_type="DO",
                     function_de="Sammelstörung", function_en="Collective fault", page_ref="/22.5"),

        # ES1 (external switch)
        IOAssignment(controller_id="K801", connector="ES1", pin="1", signal_type="DO",
                     function_de="Verdichter 1", function_en="Compressor 1",
                     target_component="Q151", page_ref="/18.4"),
        IOAssignment(controller_id="K801", connector="ES1", pin="3", signal_type="DO",
                     function_de="Verdichter 2", function_en="Compressor 2",
                     target_component="Q152", page_ref="/18.5"),
        IOAssignment(controller_id="K801", connector="ES1", pin="9", signal_type="DI",
                     function_de="Freigabe Hochdruck", function_en="Release high pressure",
                     target_component="B451", page_ref="/18.8"),

        # AI2
        IOAssignment(controller_id="K801", connector="AI2", pin="1", signal_type="AI",
                     function_de="Drucksensor Kaltwasser Eintritt", function_en="Pressure sensor cold water inlet",
                     target_component="B452", page_ref="/19.1"),
        IOAssignment(controller_id="K801", connector="AI2", pin="3", signal_type="AI",
                     function_de="Drucksensor Hochdruck", function_en="Pressure sensor high pressure",
                     target_component="B453", page_ref="/19.2"),
        IOAssignment(controller_id="K801", connector="AI2", pin="5", signal_type="AI",
                     function_de="Drucksensor Niederdruck", function_en="Pressure sensor low pressure",
                     target_component="B454", page_ref="/19.3"),

        # AI3
        IOAssignment(controller_id="K801", connector="AI3", pin="1", signal_type="AI",
                     function_de="Temperatursensor Kaltwasser Austritt", function_en="Temperature sensor cold water outlet",
                     target_component="B402", page_ref="/19.6"),
        IOAssignment(controller_id="K801", connector="AI3", pin="3", signal_type="AI",
                     function_de="Temperatursensor Kaltwasser Austritt", function_en="Temperature sensor cold water outlet",
                     target_component="B402", page_ref="/19.7"),
        IOAssignment(controller_id="K801", connector="AI3", pin="5", signal_type="AI",
                     function_de="Temperatursensor Sauggas", function_en="Temperature sensor suction gas",
                     target_component="B403", page_ref="/19.8"),

        # IFP AI1
        IOAssignment(controller_id="K801", connector="IFP AI1", pin="3", signal_type="AI",
                     function_de="Drucksensor Austritt Pumpe 1", function_en="Pressure sensor outlet pump 1",
                     target_component="B201", page_ref="/12.2"),

        # AO1
        IOAssignment(controller_id="K801", connector="AO1", pin="3", signal_type="AO",
                     function_de="Expansionsventil", function_en="Expansion valve",
                     target_component="M354", page_ref="/20.4"),
        IOAssignment(controller_id="K801", connector="AO1", pin="5", signal_type="AO",
                     function_de="Sollwert Kondensatorlüfter", function_en="Setpoint condenser fan",
                     target_component="M101", page_ref="/15.3"),

        # AIO1
        IOAssignment(controller_id="K801", connector="AIO1", pin="1", signal_type="AI",
                     function_de="Pumpe 2 Druck", function_en="Pump 2 pressure", page_ref="/13.2"),
        IOAssignment(controller_id="K801", connector="AIO1", pin="3", signal_type="AO",
                     function_de="Leitfähigkeit", function_en="Conductivity", page_ref="/10.7"),

        # AIO2
        IOAssignment(controller_id="K801", connector="AIO2", pin="1", signal_type="AI",
                     function_de="Energiesparsystem", function_en="Energy-saving system", page_ref="/9.5"),
        IOAssignment(controller_id="K801", connector="AIO2", pin="3", signal_type="AO",
                     function_de="Regelventil Heißgas Bypass", function_en="Regulating valve hot gas bypass",
                     target_component="M352", page_ref="/7.5"),
        IOAssignment(controller_id="K801", connector="AIO2", pin="5", signal_type="AI",
                     function_de="Energiesparsystem", function_en="Energy-saving system", page_ref="/9.6"),

        # RS-485 Modbus
        IOAssignment(controller_id="K801", connector="RS-485-3", pin="1", signal_type="RS485",
                     function_de="Modbus Bedienpanel", function_en="Modbus control panel",
                     target_component="A801", page_ref="/16.3"),

        # CON15 Power
        IOAssignment(controller_id="K801", connector="CON15", pin="1", signal_type="PWR",
                     function_de="Spannungsversorgung +24V", function_en="Power supply +24V",
                     target_component="T21", page_ref="/17.4"),
    ]
    graph.io_assignments = io_assignments

    return graph


def analyze_fixture(graph: MachineGraph):
    """Print analysis summary of the golden fixture."""
    print("=" * 70)
    print(f"  KKT cBoxX 100 — Machine Graph Analysis")
    print(f"  {graph.technical_data.model} | {graph.technical_data.article_no}")
    print("=" * 70)

    print(f"\n📊 Technische Daten:")
    td = graph.technical_data
    for field in ["rated_voltage", "frequency", "control_voltage", "connected_load",
                  "full_load_current", "max_pre_fuse", "enclosure_type", "sccr"]:
        val = getattr(td, field)
        if val:
            print(f"   {field:35s} = {val}")

    print(f"\n📦 Komponenten: {len(graph.components)}")
    type_counts = {}
    location_counts = {}
    for c in graph.components:
        type_counts[c.component_type] = type_counts.get(c.component_type, 0) + 1
        loc = c.location or "?"
        location_counts[loc] = location_counts.get(loc, 0) + 1
    print(f"   Nach Typ:")
    for t, n in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"     {t:20s}: {n}")
    print(f"   Nach Ort:")
    for loc, n in sorted(location_counts.items()):
        label = {"SS1": "Schaltschrank", "+SS1": "Schaltschrank", "+MR1": "Maschinenraum"}.get(loc, loc)
        print(f"     {label:20s}: {n}")

    print(f"\n🔌 Kabelverbindungen: {len(graph.connections)}")
    cables_with_cs = [c for c in graph.connections if c.cross_section_mm2]
    print(f"   Mit Querschnitt:   {len(cables_with_cs)}")
    print(f"   Ohne Querschnitt:  {len(graph.connections) - len(cables_with_cs)}")
    print(f"   Kabeltypen:")
    type_set = {}
    for c in graph.connections:
        type_set[c.cable_type] = type_set.get(c.cable_type, 0) + 1
    for t, n in sorted(type_set.items(), key=lambda x: -x[1]):
        print(f"     {t:25s}: {n}x")

    print(f"\n   Querschnitte:")
    cs_counts = {}
    for c in graph.connections:
        if c.cross_section_mm2:
            cs_counts[c.cross_section_mm2] = cs_counts.get(c.cross_section_mm2, 0) + 1
    for cs, n in sorted(cs_counts.items()):
        print(f"     {cs:6.1f} mm²: {n}x")

    print(f"\n🔧 Subsysteme: {len(graph.subsystems)}")
    for sub in graph.subsystems:
        n_comp = len(sub.component_ids)
        related_cables = [c for c in graph.connections if c.function_de and sub.name.lower().split()[0] in c.function_de.lower()]
        print(f"   {sub.name:35s} [{sub.name_en:25s}] → {n_comp:2d} Komp., ~{len(related_cables)} Kabel")

    print(f"\n🎛️  I/O-Zuordnung K801: {len(graph.io_assignments)} Signale")
    sig_counts = {}
    for io in graph.io_assignments:
        sig_counts[io.signal_type] = sig_counts.get(io.signal_type, 0) + 1
    for st, n in sorted(sig_counts.items()):
        print(f"     {st:6s}: {n}")

    # Connectivity analysis
    print(f"\n🔗 Verbindungsanalyse:")
    connected_comps = set()
    for c in graph.connections:
        if c.from_component:
            connected_comps.add(c.from_component)
        if c.to_component:
            connected_comps.add(c.to_component)
    unconnected = [c for c in graph.components if c.id not in connected_comps]
    print(f"   Verbundene Komponenten:    {len(connected_comps)}")
    print(f"   Unverbundene Komponenten:  {len(unconnected)}")
    if unconnected:
        for c in unconnected:
            print(f"     ⚠ {c.id:20s} ({c.description_de})")

    # Subsystem coverage
    print(f"\n📋 Subsystem-Abdeckung:")
    assigned = sum(1 for c in graph.components if c.subsystem)
    print(f"   Mit Subsystem:    {assigned}/{len(graph.components)}")
    unassigned = [c for c in graph.components if not c.subsystem]
    if unassigned:
        for c in unassigned:
            print(f"     ⚠ {c.id:20s} ({c.description_de})")

    print(f"\n✅ Analyse abgeschlossen.")
    print(f"   Bereit für Frontend-Visualisierung unter /machine")


if __name__ == "__main__":
    graph = build_golden_fixture()

    # Save as JSON
    data = graph.to_dict()
    out_path = "machine_graph_kkt_cboxx100.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"💾 Gespeichert: {out_path} ({len(json.dumps(data))//1024} KB)\n")

    # Run analysis
    analyze_fixture(graph)
