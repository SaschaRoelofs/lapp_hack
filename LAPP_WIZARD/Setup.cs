using Eplan.EplApi.Scripting;
using Eplan.EplApi.Base;
using Eplan.EplApi.Gui;
using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Reflection;
using System.Text;


public class LappWizardRibbon
{
    // Reiter und Button registrieren
    [DeclareRegister]
    public void RegisterRibbon()
    {
        RibbonBar ribbonBar = new RibbonBar();
        string tabName = "Lapp";
        string groupName = "Lapp Wizard";

        // vorhandene Registerkarte löschen
        var existingTab = ribbonBar.Tabs.FirstOrDefault(t => t.Name == tabName);
        if (existingTab != null) existingTab.Remove();

        // neue Registerkarte und Gruppe anlegen
        var tab = ribbonBar.AddTab(tabName);
        var group = tab.AddCommandGroup(groupName);

        // SVG‑Icon mit Lapp‑Orange (#F39200) erzeugen (32x32 für großen Button)
        string svgIcon =
            "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"32\" height=\"32\" viewBox=\"0 0 32 32\">" +
            "<rect width=\"32\" height=\"32\" rx=\"4\" ry=\"4\" fill=\"#F39200\" />" +
            "<text x=\"16\" y=\"21\" font-family=\"Arial\" font-size=\"14\" font-weight=\"bold\" text-anchor=\"middle\" fill=\"white\">LW</text>" +
            "</svg>";

        // Icon zur RibbonBar hinzufügen und als großen Button darstellen (\n erzwingt Icon oben, Text unten)
        RibbonIcon lappIcon = ribbonBar.AddIcon(svgIcon);
        group.AddCommand("Lapp Wizard", "DataExportAction", lappIcon);
    }

    // Reiter wieder entfernen
    [DeclareUnregister]
    public void UnregisterRibbon()
    {
        RibbonBar ribbonBar = new RibbonBar();
        string tabName = "Lapp Wizard";

        ribbonBar.RemoveCommand("DataExportAction");

        var tab = ribbonBar.Tabs.FirstOrDefault(t => t.Name == tabName);
        if (tab != null) tab.Remove();
    }
}

public class DataExportAction
{
    private static readonly BindingFlags DeclaredPublic = BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly;

    [DeclareAction("DataExportAction")]
    public void Execute()
    {
        try
        {
            Assembly dataModelAsm = null;
            Assembly heServicesAsm = null;
            Assembly eServicesAsm = null;
            foreach (Assembly asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                string name = asm.GetName().Name;
                if (name == "Eplan.EplApi.DataModelu") dataModelAsm = asm;
                if (name == "Eplan.EplApi.HEServicesu") heServicesAsm = asm;
                if (name == "Eplan.EplApi.EServicesu") eServicesAsm = asm;
            }

            if (dataModelAsm == null || heServicesAsm == null)
            {
                new Decider().Decide(EnumDecisionType.eOkDecision,
                    "EPLAN Assemblies nicht gefunden.", "DataExportAction",
                    EnumDecisionReturn.eOK, EnumDecisionReturn.eOK,
                    "", false, EnumDecisionIcon.eFATALERROR);
                return;
            }

            Type projectType = dataModelAsm.GetType("Eplan.EplApi.DataModel.Project");
            Type lockingStepType = dataModelAsm.GetType("Eplan.EplApi.DataModel.LockingStep");
            Type selSetType = heServicesAsm.GetType("Eplan.EplApi.HEServices.SelectionSet");

            IDisposable lockingStep = (IDisposable)Activator.CreateInstance(lockingStepType);

            try
            {
                object selSet = Activator.CreateInstance(selSetType);
                MethodInfo getCurrentProject = selSetType.GetMethod("GetCurrentProject", new Type[] { typeof(bool) });
                object project = getCurrentProject.Invoke(selSet, new object[] { true });

                if (project == null)
                {
                    new Decider().Decide(EnumDecisionType.eOkDecision,
                        "Kein Projekt geöffnet.", "DataExportAction",
                        EnumDecisionReturn.eOK, EnumDecisionReturn.eOK,
                        "", false, EnumDecisionIcon.eEXCLAMATION);
                    return;
                }

                {
                    string timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
                    string baseUrl = GetApiBaseUrl();
                    string token = Guid.NewGuid().ToString("N");
                    StringBuilder log = new StringBuilder();
                    log.AppendLine("=== Datenexport gestartet: " + timestamp + " ===");
                    log.AppendLine("API-Ziel: " + baseUrl + "/api/machine-db");
                    log.AppendLine("Token: " + token);
                    log.AppendLine();


                    // --- Export 2: Vollständiger Projekt-Export ---
                    log.AppendLine("--- 2. Vollständiger Projekt-Export (JSON) ---");
                    try
                    {
                        ExportFullProjectData(project, projectType, dataModelAsm, baseUrl, timestamp, token, log);
                    }
                    catch (Exception ex)
                    {
                        log.AppendLine("FEHLER: " + ex.Message);
                        if (ex.InnerException != null) log.AppendLine("  Inner: " + ex.InnerException.Message);
                    }

                    log.AppendLine();
                    log.AppendLine("=== Export abgeschlossen ===");

                    string machineUrl = baseUrl + "/machine?token=" + token;
                    System.Windows.Forms.Clipboard.SetText(token);

                    EnumDecisionReturn result = new Decider().Decide(
                        EnumDecisionType.eYesNoDecision,
                        "Export erfolgreich!\n\n" +
                        "Token: " + token + "\n" +
                        "(Token wurde in die Zwischenablage kopiert)\n\n" +
                        "Machine-Seite öffnen?",
                        "Export abgeschlossen",
                        EnumDecisionReturn.eYES, EnumDecisionReturn.eYES,
                        "", false, EnumDecisionIcon.eINFORMATION);

                    if (result == EnumDecisionReturn.eYES)
                    {
                        System.Diagnostics.Process.Start(machineUrl);
                    }
                }
            }
            finally
            {
                lockingStep.Dispose();
            }
        }
        catch (Exception ex)
        {
            new Decider().Decide(EnumDecisionType.eOkDecision,
                "Fehler: " + ex.Message + Environment.NewLine +
                (ex.InnerException != null ? ex.InnerException.Message : ""),
                "DataExportAction",
                EnumDecisionReturn.eOK, EnumDecisionReturn.eOK,
                "", false, EnumDecisionIcon.eFATALERROR);
        }
    }


    // =====================================================================
    //  Vollständiger Projekt-Export (Funktionen, Verbindungen, Kabel)
    // =====================================================================
    private void ExportFullProjectData(object project, Type projectType,
        Assembly dataModelAsm, string baseUrl, string timestamp, string token, StringBuilder log)
    {
        Type finderType = dataModelAsm.GetType("Eplan.EplApi.DataModel.DMObjectsFinder");
        Type conFilterType = dataModelAsm.GetType("Eplan.EplApi.DataModel.ConnectionsFilter");
        Type funcFilterType = dataModelAsm.GetType("Eplan.EplApi.DataModel.FunctionsFilter");
        Type cdpPropsEnumType = dataModelAsm.GetType("Eplan.EplApi.DataModel.Properties+ConnectionDefinitionPoint");
        Type funcPropsEnumType = dataModelAsm.GetType("Eplan.EplApi.DataModel.Properties+Function");
        Type cablePropsEnumType = dataModelAsm.GetType("Eplan.EplApi.DataModel.Properties+Cable");
        Type articlePropsEnumType = dataModelAsm.GetType("Eplan.EplApi.DataModel.Properties+Article");

        ConstructorInfo finderCtor = finderType.GetConstructor(new Type[] { projectType });
        object finder = finderCtor.Invoke(new object[] { project });

        // Alle Verbindungen
        object conFilter = Activator.CreateInstance(conFilterType);
        MethodInfo getConns = finderType.GetMethod("GetConnections", new Type[] { conFilterType });
        Array connections = (Array)getConns.Invoke(finder, new object[] { conFilter });

        // Alle Funktionen
        object funcFilter = Activator.CreateInstance(funcFilterType);
        MethodInfo getFuncs = finderType.GetMethod("GetFunctions", new Type[] { funcFilterType });
        Array functions = (Array)getFuncs.Invoke(finder, new object[] { funcFilter });

        log.AppendLine("Verbindungen: " + (connections != null ? connections.Length.ToString() : "0"));
        log.AppendLine("Funktionen: " + (functions != null ? functions.Length.ToString() : "0"));

        // CDP Property-Enum-Werte
        object propCrossSection = SafeEnumParse(cdpPropsEnumType, "CONNECTION_WIRECROSSSECTION", "CDP_CON_WIRECROSSSECTION");
        object propLength = SafeEnumParse(cdpPropsEnumType, "CONNECTION_WIRELENGTH_VALUE", "CDP_CON_WIRELENGTH");
        object propWireNumber = SafeEnumParse(cdpPropsEnumType, "CONNECTION_WIRENUMBER", "CDP_CON_WIRENUMBER");
        object propColorDesignation = SafeEnumParse(cdpPropsEnumType, "CONNECTION_COLORDESIGNATION", "CDP_CON_COLORDESIGNATION");
        object propColorNumber = SafeEnumParse(cdpPropsEnumType, "CONNECTION_COLORNUMBER", "CDP_CON_COLORNUMBER");
        object propPotential = SafeEnumParse(cdpPropsEnumType, "CONNECTION_POTENTIAL", "CDP_CON_POTENTIAL");
        object propSignalName = SafeEnumParse(cdpPropsEnumType, "CONNECTION_SIGNALNAME", "CDP_CON_SIGNALNAME");
        object propConnectionType = SafeEnumParse(cdpPropsEnumType, "CONNECTION_TYPE", "CDP_CON_TYPE");

        // Kabel-Funktions-Properties
        object propCableWireCrossSection = SafeEnumParse(funcPropsEnumType, "FUNC_CABLEWIRECROSSSECTION", "FUNC_CABLEWIRECROSSSECTION");
        object propCableWireCountAndCrossSection = SafeEnumParse(funcPropsEnumType, "FUNC_CABLEWIRECOUNTANDCROSSSECTION", "FUNC_CABLEWIRECOUNTANDCROSSSECTION");
        object propCableLength = SafeEnumParse(funcPropsEnumType, "FUNC_CABLELENGTH", "FUNC_CABLELENGTH");

        // Kabel-Properties
        object propCableCountOfUsedWires = SafeEnumParse(cablePropsEnumType, "CABLE_COUNTOFUSEDWIRES", "CABLE_COUNTOFUSEDWIRES");

        // Artikel-Properties
        object propArticleCurrentCapacity = SafeEnumParse(articlePropsEnumType, "ARTICLE_CURRENT_CARRYING_CAPACITY", "ARTICLE_CURRENT_CARRYING_CAPACITY");
        object propArticleRatedVoltage = SafeEnumParse(articlePropsEnumType, "ARTICLE_RATED_VOLTAGE", "ARTICLE_RATED_VOLTAGE");
        object propArticleDescr1 = SafeEnumParse(articlePropsEnumType, "ARTICLE_DESCR1", "ARTICLE_DESCR1");
        object propArticlePartNr = SafeEnumParse(articlePropsEnumType, "ARTICLE_PARTNR", "ARTICLE_PARTNR");

        // Projekt-Info
        string projectPath = SafeGetPropertyString(project, "ProjectLinkFilePath");
        if (string.IsNullOrEmpty(projectPath)) projectPath = SafeGetPropertyString(project, "ProjectDirectoryPath");
        string projectName = SafeGetPropertyString(project, "ProjectName");

        // Kabel-Map fuer gruppierten Export
        Dictionary<string, List<string[]>> cableMap = new Dictionary<string, List<string[]>>();
        Dictionary<string, string[]> cableInfo = new Dictionary<string, string[]>();

        StringBuilder json = new StringBuilder();
        json.AppendLine("{");
        json.AppendLine("  \"exportType\": \"FullProjectExport\",");
        json.AppendLine("  \"timestamp\": \"" + timestamp + "\",");
        json.AppendLine("  \"projectPath\": " + JsonEscape(projectPath) + ",");
        json.AppendLine("  \"projectName\": " + JsonEscape(projectName) + ",");

        // =================================================================
        //  FUNKTIONEN
        // =================================================================
        json.AppendLine("  \"functionCount\": " + (functions != null ? functions.Length : 0) + ",");
        json.AppendLine("  \"functions\": [");
        if (functions != null)
        {
            bool first = true;
            foreach (object func in functions)
            {
                if (!first) json.AppendLine(",");
                first = false;

                json.AppendLine("    {");
                json.AppendLine("      \"name\": " + JsonEscape(SafeGetPropertyString(func, "Name")) + ",");
                json.AppendLine("      \"identifyingName\": " + JsonEscape(SafeGetPropertyString(func, "IdentifyingName")) + ",");
                json.AppendLine("      \"functionDefinition\": " + JsonEscape(SafeGetPropertyString(func, "FunctionDefinition")) + ",");
                json.AppendLine("      \"functionType\": " + JsonEscape(SafeGetPropertyString(func, "FunctionType")) + ",");
                json.AppendLine("      \"category\": " + JsonEscape(SafeGetPropertyString(func, "Category")) + ",");
                json.AppendLine("      \"isMainFunction\": " + JsonEscape(SafeGetPropertyString(func, "IsMainFunction")) + ",");
                json.AppendLine("      \"location\": " + JsonEscape(SafeGetPropertyString(func, "Location")) + ",");
                json.AppendLine("      \"mountingLocation\": " + JsonEscape(SafeGetPropertyString(func, "MountingLocation")) + ",");
                json.AppendLine("      \"mountingSite\": " + JsonEscape(SafeGetPropertyString(func, "MountingSite")) + ",");
                json.AppendLine("      \"installationSpace\": " + JsonEscape(SafeGetPropertyString(func, "InstallationSpace")) + ",");
                json.AppendLine("      \"partNr\": " + JsonEscape(SafeGetPropertyString(func, "PartNr")) + ",");
                json.AppendLine("      \"description\": " + JsonEscape(SafeGetPropertyString(func, "Description")) + ",");
                json.AppendLine("      \"visibleName\": " + JsonEscape(SafeGetPropertyString(func, "VisibleName")) + ",");
                json.AppendLine("      \"pageName\": " + JsonEscape(SafeGetPropertyString(func, "PageName")) + ",");
                json.AppendLine("      \"pageFullName\": " + JsonEscape(SafeGetPropertyString(func, "Page")) + ",");
                json.AppendLine("      \"functionText\": " + JsonEscape(SafeGetPropertyString(func, "FunctionText")) + ",");
                json.AppendLine("      \"supplementaryField1\": " + JsonEscape(SafeGetPropertyString(func, "SupplementaryField1")) + ",");
                json.AppendLine("      \"supplementaryField2\": " + JsonEscape(SafeGetPropertyString(func, "SupplementaryField2")));
                json.Append("    }");
            }
        }
        json.AppendLine();
        json.AppendLine("  ],");

        // =================================================================
        //  VERBINDUNGEN
        // =================================================================
        json.AppendLine("  \"connectionCount\": " + (connections != null ? connections.Length : 0) + ",");
        json.AppendLine("  \"connections\": [");
        if (connections != null)
        {
            bool first = true;
            foreach (object conn in connections)
            {
                if (!first) json.AppendLine(",");
                first = false;

                Type connType = conn.GetType();
                string connName = SafeGetPropertyString(conn, "Name");
                string connIdName = SafeGetPropertyString(conn, "IdentifyingName");

                // --- Kabel-Daten ---
                string cableName = "";
                string cableTypeName = "";
                string kabelQuerschnitt = "";
                string kabelQuerschnittMitAnzahl = "";
                string kabelLänge = "";
                string belasteteAdern = "";
                string betriebsstrom = "";
                string systemspannung = "";
                string articleDescr = "";
                string articlePartNr = "";

                try
                {
                    PropertyInfo cableProp = connType.GetProperty("CableDefinitionLine", DeclaredPublic)
                        ?? connType.GetProperty("CableDefinitionLine");
                    if (cableProp != null)
                    {
                        object cable = cableProp.GetValue(conn, null);
                        if (cable != null)
                        {
                            cableName = SafeGetPropertyString(cable, "Name");
                            cableTypeName = SafeGetPropertyString(cable, "PartNr");

                            // Kabel-Properties ueber Funktions-Enum
                            try
                            {
                                PropertyInfo cablePropsProp = cable.GetType().GetProperty("Properties", DeclaredPublic)
                                    ?? cable.GetType().GetProperty("Properties");
                                if (cablePropsProp != null)
                                {
                                    object cableProps = cablePropsProp.GetValue(cable, null);
                                    if (cableProps != null)
                                    {
                                        PropertyInfo funcIndexer = FindIndexer(cableProps, funcPropsEnumType);
                                        if (funcIndexer != null)
                                        {
                                            kabelQuerschnitt = SafeReadProp(funcIndexer, cableProps, propCableWireCrossSection, true);
                                            kabelQuerschnittMitAnzahl = SafeReadProp(funcIndexer, cableProps, propCableWireCountAndCrossSection, false);
                                            kabelLänge = SafeReadProp(funcIndexer, cableProps, propCableLength, false);
                                        }

                                        PropertyInfo cblIndexer = FindIndexer(cableProps, cablePropsEnumType);
                                        if (cblIndexer != null)
                                            belasteteAdern = SafeReadProp(cblIndexer, cableProps, propCableCountOfUsedWires, false);
                                    }
                                }
                            }
                            catch { }

                            // Artikel-Daten
                            SafeReadArticleProperties(cable, articlePropsEnumType,
                                propArticleCurrentCapacity, propArticleRatedVoltage,
                                propArticleDescr1, propArticlePartNr,
                                out betriebsstrom, out systemspannung, out articleDescr, out articlePartNr);
                        }
                    }
                }
                catch { }

                // --- CDPs auslesen ---
                PropertyInfo cdpPropInfo = connType.GetProperty("ConnectionDefPoints", DeclaredPublic)
                    ?? connType.GetProperty("ConnectionDefPoints");
                Array cdpArr = null;
                if (cdpPropInfo != null)
                    cdpArr = cdpPropInfo.GetValue(conn, null) as Array;

                string source = "";
                string target = "";
                if (cdpArr != null && cdpArr.Length > 0)
                {
                    source = SafeGetFunctionName(cdpArr.GetValue(0));
                    target = cdpArr.Length > 1
                        ? SafeGetFunctionName(cdpArr.GetValue(cdpArr.Length - 1))
                        : source;
                }

                // Verbindungsdaten aus erstem CDP
                string wireNumber = "";
                string crossSection = "";
                string wireLength = "";
                string wireColor = "";
                string colorNumber = "";
                string potential = "";
                string signalName = "";
                string connectionType = "";

                if (cdpArr != null && cdpArr.Length > 0)
                {
                    object firstCdp = cdpArr.GetValue(0);
                    PropertyInfo propsProp = firstCdp.GetType().GetProperty("Properties", DeclaredPublic)
                        ?? firstCdp.GetType().GetProperty("Properties");
                    if (propsProp != null)
                    {
                        object props = propsProp.GetValue(firstCdp, null);
                        if (props != null)
                        {
                            PropertyInfo indexer = FindIndexer(props, cdpPropsEnumType);
                            if (indexer != null)
                            {
                                crossSection = SafeReadProp(indexer, props, propCrossSection, true);
                                wireLength = SafeReadProp(indexer, props, propLength, true);
                                wireNumber = SafeReadProp(indexer, props, propWireNumber, false);
                                wireColor = SafeReadProp(indexer, props, propColorDesignation, false);
                                colorNumber = SafeReadProp(indexer, props, propColorNumber, false);
                                potential = SafeReadProp(indexer, props, propPotential, false);
                                signalName = SafeReadProp(indexer, props, propSignalName, false);
                                connectionType = SafeReadProp(indexer, props, propConnectionType, false);
                            }
                        }
                    }
                }

                // Kabel-Map befuellen
                if (!string.IsNullOrEmpty(cableName))
                {
                    if (!cableMap.ContainsKey(cableName))
                    {
                        cableMap[cableName] = new List<string[]>();
                        cableInfo[cableName] = new string[] {
                                cableTypeName, kabelQuerschnitt, kabelQuerschnittMitAnzahl,
                                kabelLänge, belasteteAdern, betriebsstrom, systemspannung,
                                articleDescr, articlePartNr
                            };
                    }
                    cableMap[cableName].Add(new string[] {
                            wireNumber, crossSection, wireLength, source, target,
                            wireColor, colorNumber, potential, signalName
                        });
                }

                // --- JSON fuer diese Verbindung ---
                json.AppendLine("    {");
                json.AppendLine("      \"name\": " + JsonEscape(connName) + ",");
                json.AppendLine("      \"identifyingName\": " + JsonEscape(connIdName) + ",");
                json.AppendLine("      \"from\": " + JsonEscape(source) + ",");
                json.AppendLine("      \"to\": " + JsonEscape(target) + ",");
                json.AppendLine("      \"wireNumber\": " + JsonEscape(wireNumber) + ",");
                json.AppendLine("      \"crossSection\": " + JsonEscape(crossSection) + ",");
                json.AppendLine("      \"wireLength\": " + JsonEscape(wireLength) + ",");
                json.AppendLine("      \"wireColor\": " + JsonEscape(wireColor) + ",");
                json.AppendLine("      \"colorNumber\": " + JsonEscape(colorNumber) + ",");
                json.AppendLine("      \"potential\": " + JsonEscape(potential) + ",");
                json.AppendLine("      \"signalName\": " + JsonEscape(signalName) + ",");
                json.AppendLine("      \"connectionType\": " + JsonEscape(connectionType) + ",");
                json.AppendLine("      \"cable\": " + JsonEscape(cableName) + ",");
                json.AppendLine("      \"cableType\": " + JsonEscape(cableTypeName) + ",");

                // Alle CDPs einzeln
                json.AppendLine("      \"connectionDefPoints\": [");
                if (cdpArr != null)
                {
                    for (int ci = 0; ci < cdpArr.Length; ci++)
                    {
                        if (ci > 0) json.AppendLine(",");
                        object cdp = cdpArr.GetValue(ci);
                        string cdpIdName = SafeGetPropertyString(cdp, "IdentifyingName");
                        if (string.IsNullOrEmpty(cdpIdName)) cdpIdName = SafeGetPropertyString(cdp, "Name");

                        string cdpWireNum = "";
                        string cdpCS = "";
                        string cdpLen = "";
                        string cdpColor = "";
                        string cdpColorNum = "";
                        string cdpPot = "";
                        string cdpSignal = "";

                        PropertyInfo cdpPropsProp = cdp.GetType().GetProperty("Properties", DeclaredPublic)
                            ?? cdp.GetType().GetProperty("Properties");
                        if (cdpPropsProp != null)
                        {
                            object cdpProps = cdpPropsProp.GetValue(cdp, null);
                            if (cdpProps != null)
                            {
                                PropertyInfo cdpIndexer = FindIndexer(cdpProps, cdpPropsEnumType);
                                if (cdpIndexer != null)
                                {
                                    cdpWireNum = SafeReadProp(cdpIndexer, cdpProps, propWireNumber, false);
                                    cdpCS = SafeReadProp(cdpIndexer, cdpProps, propCrossSection, true);
                                    cdpLen = SafeReadProp(cdpIndexer, cdpProps, propLength, true);
                                    cdpColor = SafeReadProp(cdpIndexer, cdpProps, propColorDesignation, false);
                                    cdpColorNum = SafeReadProp(cdpIndexer, cdpProps, propColorNumber, false);
                                    cdpPot = SafeReadProp(cdpIndexer, cdpProps, propPotential, false);
                                    cdpSignal = SafeReadProp(cdpIndexer, cdpProps, propSignalName, false);
                                }
                            }
                        }

                        json.AppendLine("        {");
                        json.AppendLine("          \"identifyingName\": " + JsonEscape(cdpIdName) + ",");
                        json.AppendLine("          \"wireNumber\": " + JsonEscape(cdpWireNum) + ",");
                        json.AppendLine("          \"crossSection\": " + JsonEscape(cdpCS) + ",");
                        json.AppendLine("          \"wireLength\": " + JsonEscape(cdpLen) + ",");
                        json.AppendLine("          \"wireColor\": " + JsonEscape(cdpColor) + ",");
                        json.AppendLine("          \"colorNumber\": " + JsonEscape(cdpColorNum) + ",");
                        json.AppendLine("          \"potential\": " + JsonEscape(cdpPot) + ",");
                        json.AppendLine("          \"signalName\": " + JsonEscape(cdpSignal));
                        json.Append("        }");
                    }
                }
                json.AppendLine();
                json.AppendLine("      ]");
                json.Append("    }");
            }
        }
        json.AppendLine();
        json.AppendLine("  ],");

        // =================================================================
        //  KABEL (gruppiert)
        // =================================================================
        json.AppendLine("  \"cableCount\": " + cableMap.Count + ",");
        json.AppendLine("  \"cables\": [");
        {
            bool firstCable = true;
            foreach (KeyValuePair<string, List<string[]>> kvp in cableMap)
            {
                if (!firstCable) json.AppendLine(",");
                firstCable = false;

                string cn = kvp.Key;
                string[] ci = cableInfo.ContainsKey(cn) ? cableInfo[cn] : new string[0];

                json.AppendLine("    {");
                json.AppendLine("      \"name\": " + JsonEscape(cn) + ",");
                json.AppendLine("      \"type\": " + JsonEscape(SafeIdx(ci, 0)) + ",");
                json.AppendLine("      \"crossSection\": " + JsonEscape(SafeIdx(ci, 1)) + ",");
                json.AppendLine("      \"wiresAndCrossSection\": " + JsonEscape(SafeIdx(ci, 2)) + ",");
                json.AppendLine("      \"length\": " + JsonEscape(SafeIdx(ci, 3)) + ",");
                json.AppendLine("      \"usedWires\": " + JsonEscape(SafeIdx(ci, 4)) + ",");
                json.AppendLine("      \"currentCapacity\": " + JsonEscape(SafeIdx(ci, 5)) + ",");
                json.AppendLine("      \"ratedVoltage\": " + JsonEscape(SafeIdx(ci, 6)) + ",");
                json.AppendLine("      \"articleDescription\": " + JsonEscape(SafeIdx(ci, 7)) + ",");
                json.AppendLine("      \"articlePartNr\": " + JsonEscape(SafeIdx(ci, 8)) + ",");
                json.AppendLine("      \"wireCount\": " + kvp.Value.Count + ",");
                json.AppendLine("      \"wires\": [");

                bool firstWire = true;
                foreach (string[] w in kvp.Value)
                {
                    if (!firstWire) json.AppendLine(",");
                    firstWire = false;

                    json.AppendLine("        {");
                    json.AppendLine("          \"wireNumber\": " + JsonEscape(SafeIdx(w, 0)) + ",");
                    json.AppendLine("          \"crossSection\": " + JsonEscape(SafeIdx(w, 1)) + ",");
                    json.AppendLine("          \"wireLength\": " + JsonEscape(SafeIdx(w, 2)) + ",");
                    json.AppendLine("          \"from\": " + JsonEscape(SafeIdx(w, 3)) + ",");
                    json.AppendLine("          \"to\": " + JsonEscape(SafeIdx(w, 4)) + ",");
                    json.AppendLine("          \"wireColor\": " + JsonEscape(SafeIdx(w, 5)) + ",");
                    json.AppendLine("          \"colorNumber\": " + JsonEscape(SafeIdx(w, 6)) + ",");
                    json.AppendLine("          \"potential\": " + JsonEscape(SafeIdx(w, 7)) + ",");
                    json.AppendLine("          \"signalName\": " + JsonEscape(SafeIdx(w, 8)));
                    json.Append("        }");
                }

                json.AppendLine();
                json.AppendLine("      ]");
                json.Append("    }");
            }
        }
        json.AppendLine();
        json.AppendLine("  ]");
        json.AppendLine("}");

        PostJson(baseUrl, json.ToString(), token, log);
    }

    // =====================================================================
    //  Hilfsmethoden
    // =====================================================================

    private static void WriteAllProperties(StringBuilder json, object obj, string indent)
    {
        bool first = true;
        try
        {
            foreach (PropertyInfo pi in obj.GetType().GetProperties(DeclaredPublic))
            {
                if (pi.GetIndexParameters().Length > 0) continue;
                if (pi.Name == "Properties") continue;
                try
                {
                    object val = pi.GetValue(obj, null);
                    if (!first) json.AppendLine(",");
                    first = false;
                    json.Append(indent + JsonEscape(pi.Name) + ": " + JsonEscape(val != null ? val.ToString() : ""));
                }
                catch { }
            }
        }
        catch { }
        if (!first) json.AppendLine();
    }

    private static string SafeReadProp(PropertyInfo indexer, object props, object enumVal, bool asDouble)
    {
        if (enumVal == null) return "";
        try
        {
            object pv = indexer.GetValue(props, new object[] { enumVal });
            return asDouble ? SafeToDouble(pv) : SafeToString(pv);
        }
        catch { return ""; }
    }

    private static void SafeReadArticleProperties(object cable, Type articlePropsEnumType,
        object propCurrentCapacity, object propRatedVoltage,
        object propDescr1, object propPartNr,
        out string currentCapacity, out string ratedVoltage,
        out string description, out string partNr)
    {
        currentCapacity = "";
        ratedVoltage = "";
        description = "";
        partNr = "";
        try
        {
            if (articlePropsEnumType == null) return;

            PropertyInfo artRefsProp = cable.GetType().GetProperty("ArticleReferences", DeclaredPublic)
                ?? cable.GetType().GetProperty("ArticleReferences");
            if (artRefsProp == null) return;

            Array artArr = artRefsProp.GetValue(cable, null) as Array;
            if (artArr == null || artArr.Length == 0) return;

            object firstArtRef = artArr.GetValue(0);
            if (firstArtRef == null) return;

            PropertyInfo articleProp = firstArtRef.GetType().GetProperty("Article", DeclaredPublic)
                ?? firstArtRef.GetType().GetProperty("Article");
            if (articleProp == null) return;

            object article = articleProp.GetValue(firstArtRef, null);
            if (article == null) return;

            PropertyInfo artPropsProp = article.GetType().GetProperty("Properties", DeclaredPublic)
                ?? article.GetType().GetProperty("Properties");
            if (artPropsProp == null) return;

            object artProps = artPropsProp.GetValue(article, null);
            if (artProps == null) return;

            PropertyInfo artIndexer = FindIndexer(artProps, articlePropsEnumType);
            if (artIndexer == null) return;

            currentCapacity = SafeReadProp(artIndexer, artProps, propCurrentCapacity, true);
            ratedVoltage = SafeReadProp(artIndexer, artProps, propRatedVoltage, false);
            description = SafeReadProp(artIndexer, artProps, propDescr1, false);
            partNr = SafeReadProp(artIndexer, artProps, propPartNr, false);
        }
        catch { }
    }

    private static Type FindTypeByName(Assembly[] assemblies, string typeName)
    {
        foreach (Assembly asm in assemblies)
        {
            if (asm == null) continue;
            try
            {
                foreach (Type t in asm.GetExportedTypes())
                {
                    if (t.Name == typeName) return t;
                }
            }
            catch { }
        }
        return null;
    }

    private static void ListRelevantTypes(StringBuilder log, params string[] keywords)
    {
        foreach (Assembly asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            string asmName = asm.GetName().Name;
            if (!asmName.StartsWith("Eplan")) continue;
            try
            {
                foreach (Type t in asm.GetExportedTypes())
                {
                    foreach (string kw in keywords)
                    {
                        if (t.Name.Contains(kw))
                        {
                            log.AppendLine("  " + t.FullName + " [" + asmName + "]");
                            break;
                        }
                    }
                }
            }
            catch { }
        }
    }

    private static PropertyInfo FindIndexer(object propsObj, Type enumType)
    {
        if (propsObj == null || enumType == null) return null;
        foreach (PropertyInfo pi in propsObj.GetType().GetProperties())
        {
            ParameterInfo[] idxParams = pi.GetIndexParameters();
            if (idxParams.Length == 1 && idxParams[0].ParameterType == enumType)
                return pi;
        }
        return null;
    }

    private static string SafeGetPropertyString(object obj, string propertyName)
    {
        if (obj == null) return "";
        try
        {
            PropertyInfo prop = obj.GetType().GetProperty(propertyName, DeclaredPublic)
                ?? obj.GetType().GetProperty(propertyName);
            if (prop != null && prop.GetIndexParameters().Length == 0)
            {
                object val = prop.GetValue(obj, null);
                if (val != null) return val.ToString().Trim();
            }
        }
        catch { }
        return "";
    }

    private static string SafeGetFunctionName(object cdp)
    {
        try
        {
            PropertyInfo idProp = cdp.GetType().GetProperty("IdentifyingName", DeclaredPublic)
                ?? cdp.GetType().GetProperty("IdentifyingName");
            if (idProp != null)
            {
                object val = idProp.GetValue(cdp, null);
                if (val != null)
                {
                    string s = val.ToString().Trim();
                    if (!string.IsNullOrEmpty(s)) return s;
                }
            }
            PropertyInfo nameProp = cdp.GetType().GetProperty("Name", DeclaredPublic)
                ?? cdp.GetType().GetProperty("Name");
            if (nameProp != null)
            {
                object val = nameProp.GetValue(cdp, null);
                if (val != null)
                {
                    string s = val.ToString().Trim();
                    if (!string.IsNullOrEmpty(s)) return s;
                }
            }
            return cdp.ToString();
        }
        catch { return ""; }
    }

    private static string SafeToDouble(object pv)
    {
        try
        {
            object val = pv.GetType().GetMethod("ToDouble", Type.EmptyTypes).Invoke(pv, null);
            double d = Convert.ToDouble(val);
            if (d == 0) return "";
            return d.ToString("0.##");
        }
        catch { return ""; }
    }

    private static string SafeToString(object pv)
    {
        try { return pv.ToString().Trim(); }
        catch { return ""; }
    }

    private static object SafeEnumParse(Type enumType, string primary, string fallback)
    {
        if (enumType == null) return null;
        try { return Enum.Parse(enumType, primary); }
        catch
        {
            try { return Enum.Parse(enumType, fallback); }
            catch { return null; }
        }
    }

    private static string SafeIdx(string[] arr, int idx)
    {
        return arr != null && idx < arr.Length ? (arr[idx] ?? "") : "";
    }

    private static string JsonEscape(string s)
    {
        if (s == null) return "\"\"";
        return "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "\\r").Replace("\t", "\\t") + "\"";
    }

    private static string GetApiBaseUrl()
    {
        try
        {
            var request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:8000/health");
            request.Timeout = 2000;
            request.Method = "HEAD";
            using (request.GetResponse()) { }
            return "http://127.0.0.1:8000";
        }
        catch
        {
            return "https://lapp-hack.de";
        }
    }

    private static void PostJson(string baseUrl, string json, string token, StringBuilder log)
    {
        string url = baseUrl + "/api/machine-db";
        try
        {
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = "POST";
            request.ContentType = "application/json; charset=utf-8";
            request.Headers["Authorization"] = "Bearer " + token;
            byte[] data = Encoding.UTF8.GetBytes(json);
            request.ContentLength = data.Length;
            using (Stream stream = request.GetRequestStream())
            {
                stream.Write(data, 0, data.Length);
            }
            using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
            {
                log.AppendLine("Daten gesendet an: " + url + " (Status: " + (int)response.StatusCode + " " + response.StatusCode + ")");
            }
        }
        catch (WebException wex)
        {
            string msg = wex.Message;
            HttpWebResponse errResp = wex.Response as HttpWebResponse;
            if (errResp != null)
                msg += " (Status: " + (int)errResp.StatusCode + ")";
            log.AppendLine("FEHLER beim Senden an " + url + ": " + msg);
        }
        catch (Exception ex)
        {
            log.AppendLine("FEHLER beim Senden an " + url + ": " + ex.Message);
        }
    }
}