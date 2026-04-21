using Eplan.EplApi.Gui;
using Decider = Eplan.EplApi.Base.Decider;
using EnumDecisionIcon = Eplan.EplApi.Base.EnumDecisionIcon;
using EnumDecisionReturn = Eplan.EplApi.Base.EnumDecisionReturn;
using EnumDecisionType = Eplan.EplApi.Base.EnumDecisionType;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Net;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;


public class LappWizardRibbon
{
    // Register tab and button
    [Eplan.EplApi.Scripting.DeclareRegister]
    public void RegisterRibbon()
    {
        RibbonBar ribbonBar = new RibbonBar();
        string tabName = "Lapp";
        string groupName = "Lapp Wizard";

        // Delete existing tab if present
        var existingTab = ribbonBar.Tabs.FirstOrDefault(t => t.Name == tabName);
        if (existingTab != null) existingTab.Remove();

        // Create new tab and group
        var tab = ribbonBar.AddTab(tabName);
        var group = tab.AddCommandGroup(groupName);

        // Create SVG icon with Lapp orange (#F39200) (32x32 for large button)
        string svgIcon =
            "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"32\" height=\"32\" viewBox=\"0 0 32 32\">" +
            "<rect width=\"32\" height=\"32\" rx=\"4\" ry=\"4\" fill=\"#F39200\" />" +
            "<text x=\"16\" y=\"21\" font-family=\"Arial\" font-size=\"14\" font-weight=\"bold\" text-anchor=\"middle\" fill=\"white\">LW</text>" +
            "</svg>";

        string svgCopilotIcon =
            "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"32\" height=\"32\" viewBox=\"0 0 32 32\">" +
            "<rect width=\"32\" height=\"32\" rx=\"4\" ry=\"4\" fill=\"#333333\" />" +
            "<text x=\"16\" y=\"21\" font-family=\"Arial\" font-size=\"14\" font-weight=\"bold\" text-anchor=\"middle\" fill=\"#F39200\">AI</text>" +
            "</svg>";

        string svgSyncIcon =
            "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"32\" height=\"32\" viewBox=\"0 0 32 32\">" +
            "<rect width=\"32\" height=\"32\" rx=\"4\" ry=\"4\" fill=\"#1E90FF\" />" +
            "<text x=\"16\" y=\"21\" font-family=\"Arial\" font-size=\"14\" font-weight=\"bold\" text-anchor=\"middle\" fill=\"white\">SYNC</text>" +
            "</svg>";

        // Add icon to RibbonBar and render as large button (\n forces icon on top, text below)
        RibbonIcon lappIcon = ribbonBar.AddIcon(svgIcon);
        group.AddCommand("Lapp Wizard", "DataExportAction", lappIcon);

        RibbonIcon aiIcon = ribbonBar.AddIcon(svgCopilotIcon);
        group.AddCommand("Copilot", "CopilotAction", aiIcon);

        RibbonIcon syncIcon = ribbonBar.AddIcon(svgSyncIcon);
        group.AddCommand("Replace Sync", "ReplaceSyncAction", syncIcon);
    }

    // Remove tab
    [Eplan.EplApi.Scripting.DeclareUnregister]
    public void UnregisterRibbon()
    {
        RibbonBar ribbonBar = new RibbonBar();
        string tabName = "Lapp Wizard";

        ribbonBar.RemoveCommand("DataExportAction");
        ribbonBar.RemoveCommand("CopilotAction");
        ribbonBar.RemoveCommand("ReplaceSyncAction");

        var tab = ribbonBar.Tabs.FirstOrDefault(t => t.Name == tabName);
        if (tab != null) tab.Remove();
    }
}

public class DataExportAction
{
    private static readonly BindingFlags DeclaredPublic = BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly;

    [Eplan.EplApi.Scripting.DeclareAction("DataExportAction")]
    public void Execute()
    {
        Eplan.EplApi.Base.Progress progress = null;
        try
        {
            progress = new Eplan.EplApi.Base.Progress("SimpleProgress");
            progress.ShowImmediately();
            progress.SetAllowCancel(false);
            progress.SetAskOnCancel(false);
            progress.SetNeededSteps(3);
            progress.SetTitle("Lapp Wizard");
            progress.SetActionText("Projekt wird exportiert... Bitte warten!");
            progress.Step(1);

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


                    // --- Export 2: Full project export ---
                    log.AppendLine("--- 2. Vollständiger Projekt-Export (JSON) ---");
                    string jsonPayload = "";

                    // Run export on background thread to prevent EPLAN from freezing
                    progress.SetActionText("Projektdaten werden gesammelt...");
                    Exception bgError = null;
                    var exportTask = System.Threading.Tasks.Task.Run(() =>
                    {
                        return ExportFullProjectData(project, projectType, dataModelAsm, baseUrl, timestamp, token, log);
                    });
                    while (!exportTask.IsCompleted)
                    {
                        System.Threading.Thread.Sleep(100);
                        System.Windows.Forms.Application.DoEvents();
                    }
                    if (exportTask.IsFaulted)
                    {
                        bgError = exportTask.Exception.InnerException ?? exportTask.Exception;
                        log.AppendLine("FEHLER: " + bgError.Message);
                        if (bgError.InnerException != null) log.AppendLine("  Inner: " + bgError.InnerException.Message);
                    }
                    else
                    {
                        jsonPayload = exportTask.Result;
                    }

                    log.AppendLine();
                    log.AppendLine("=== Export abgeschlossen ===");

                    string machineUrl = baseUrl + "/machine?token=" + token;
                    System.Windows.Forms.Clipboard.SetText(token);

                    if (!string.IsNullOrEmpty(jsonPayload))
                    {
                        // Upload on background thread
                        progress.SetActionText("Daten werden zum Server hochgeladen...");
                        var uploadTask = System.Threading.Tasks.Task.Run(() =>
                        {
                            PostJson(baseUrl, jsonPayload, token, log);
                        });
                        while (!uploadTask.IsCompleted)
                        {
                            System.Threading.Thread.Sleep(100);
                            System.Windows.Forms.Application.DoEvents();
                        }
                        if (uploadTask.IsFaulted)
                        {
                            bgError = uploadTask.Exception.InnerException ?? uploadTask.Exception;
                            log.AppendLine("FEHLER Upload: " + bgError.Message);
                        }

                        // End progress bar BEFORE the dialog appears
                        if (progress != null)
                        {
                            progress.EndPart(true);
                            progress = null;
                        }

                        EnumDecisionReturn result = new Decider().Decide(
                            EnumDecisionType.eYesNoDecision,
                            "Export erfolgreich!\n\n" +
                            "Token: " + token + "\n" +
                            "(Token wurde in die Zwischenablage kopiert)\n\n" +
                            "Ergebnis in EPLAN öffnen?",
                            "Export abgeschlossen",
                            EnumDecisionReturn.eYES, EnumDecisionReturn.eYES,
                            "", false, EnumDecisionIcon.eINFORMATION);

                        if (result == EnumDecisionReturn.eYES)
                        {
                            new LappWizardForm(machineUrl).ShowDialog();
                        }
                    }
                    else
                    {
                        new Decider().Decide(EnumDecisionType.eOkDecision, "Fehler beim Sammeln der Projekt-Daten.", "Export", EnumDecisionReturn.eOK, EnumDecisionReturn.eOK, "", false, EnumDecisionIcon.eFATALERROR);
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
        finally
        {
            if (progress != null)
            {
                progress.EndPart(true);
            }
        }
    }


    // =====================================================================
    //  Full project export (functions, connections, cables)
    // =====================================================================
    private string ExportFullProjectData(object project, Type projectType,
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

        // All connections
        object conFilter = Activator.CreateInstance(conFilterType);
        MethodInfo getConns = finderType.GetMethod("GetConnections", new Type[] { conFilterType });
        Array connections = (Array)getConns.Invoke(finder, new object[] { conFilter });

        // All functions
        object funcFilter = Activator.CreateInstance(funcFilterType);
        MethodInfo getFuncs = finderType.GetMethod("GetFunctions", new Type[] { funcFilterType });
        Array functions = (Array)getFuncs.Invoke(finder, new object[] { funcFilter });

        log.AppendLine("Verbindungen: " + (connections != null ? connections.Length.ToString() : "0"));
        log.AppendLine("Funktionen: " + (functions != null ? functions.Length.ToString() : "0"));

        // CDP property enum values
        object propCrossSection = SafeEnumParse(cdpPropsEnumType, "CONNECTION_WIRECROSSSECTION", "CDP_CON_WIRECROSSSECTION");
        object propLength = SafeEnumParse(cdpPropsEnumType, "CONNECTION_WIRELENGTH_VALUE", "CDP_CON_WIRELENGTH");
        object propWireNumber = SafeEnumParse(cdpPropsEnumType, "CONNECTION_WIRENUMBER", "CDP_CON_WIRENUMBER");
        object propColorDesignation = SafeEnumParse(cdpPropsEnumType, "CONNECTION_COLORDESIGNATION", "CDP_CON_COLORDESIGNATION");
        object propColorNumber = SafeEnumParse(cdpPropsEnumType, "CONNECTION_COLORNUMBER", "CDP_CON_COLORNUMBER");
        object propPotential = SafeEnumParse(cdpPropsEnumType, "CONNECTION_POTENTIAL", "CDP_CON_POTENTIAL");
        object propSignalName = SafeEnumParse(cdpPropsEnumType, "CONNECTION_SIGNALNAME", "CDP_CON_SIGNALNAME");
        object propConnectionType = SafeEnumParse(cdpPropsEnumType, "CONNECTION_TYPE", "CDP_CON_TYPE");

        // Cable function properties
        object propCableWireCrossSection = SafeEnumParse(funcPropsEnumType, "FUNC_CABLEWIRECROSSSECTION", "FUNC_CABLEWIRECROSSSECTION");
        object propCableWireCountAndCrossSection = SafeEnumParse(funcPropsEnumType, "FUNC_CABLEWIRECOUNTANDCROSSSECTION", "FUNC_CABLEWIRECOUNTANDCROSSSECTION");
        object propCableLength = SafeEnumParse(funcPropsEnumType, "FUNC_CABLELENGTH", "FUNC_CABLELENGTH");

        // Cable properties
        object propCableCountOfUsedWires = SafeEnumParse(cablePropsEnumType, "CABLE_COUNTOFUSEDWIRES", "CABLE_COUNTOFUSEDWIRES");

        // Article properties
        object propArticleCurrentCapacity = SafeEnumParse(articlePropsEnumType, "ARTICLE_CURRENT_CARRYING_CAPACITY", "ARTICLE_CURRENT_CARRYING_CAPACITY");
        object propArticleRatedVoltage = SafeEnumParse(articlePropsEnumType, "ARTICLE_RATED_VOLTAGE", "ARTICLE_RATED_VOLTAGE");
        object propArticleDescr1 = SafeEnumParse(articlePropsEnumType, "ARTICLE_DESCR1", "ARTICLE_DESCR1");
        object propArticlePartNr = SafeEnumParse(articlePropsEnumType, "ARTICLE_PARTNR", "ARTICLE_PARTNR");

        // Project info
        string projectPath = SafeGetPropertyString(project, "ProjectLinkFilePath");
        if (string.IsNullOrEmpty(projectPath)) projectPath = SafeGetPropertyString(project, "ProjectDirectoryPath");
        string projectName = SafeGetPropertyString(project, "ProjectName");

        // Cable map for grouped export
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

                // --- Cable data ---
                string cableName = "";
                string cableTypeName = "";
                string cableCrossSection = "";
                string cableCrossSectionWithCount = "";
                string cableLen = "";
                string usedWiresCount = "";
                string operatingCurrent = "";
                string systemVoltage = "";
                string articleDescr = "";
                string articlePartNr = "";
                string artRefPartNr = "";
                string artRefVariantNr = "";
                string artRefReferencePos = "";

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

                            // Cable properties via function enum
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
                                            cableCrossSection = SafeReadProp(funcIndexer, cableProps, propCableWireCrossSection, true);
                                            cableCrossSectionWithCount = SafeReadProp(funcIndexer, cableProps, propCableWireCountAndCrossSection, false);
                                            cableLen = SafeReadProp(funcIndexer, cableProps, propCableLength, false);
                                        }

                                        PropertyInfo cblIndexer = FindIndexer(cableProps, cablePropsEnumType);
                                        if (cblIndexer != null)
                                            usedWiresCount = SafeReadProp(cblIndexer, cableProps, propCableCountOfUsedWires, false);
                                    }
                                }
                            }
                            catch { }

                            // Article data
                            SafeReadArticleProperties(cable, articlePropsEnumType,
                                propArticleCurrentCapacity, propArticleRatedVoltage,
                                propArticleDescr1, propArticlePartNr,
                                out operatingCurrent, out systemVoltage, out articleDescr, out articlePartNr,
                                out artRefPartNr, out artRefVariantNr, out artRefReferencePos);
                        }
                    }
                }
                catch { }

                // --- Read CDPs ---
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

                // Connection data from first CDP
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

                // Populate cable map
                if (!string.IsNullOrEmpty(cableName))
                {
                    if (!cableMap.ContainsKey(cableName))
                    {
                        cableMap[cableName] = new List<string[]>();
                        cableInfo[cableName] = new string[] {
                                cableTypeName, cableCrossSection, cableCrossSectionWithCount,
                                cableLen, usedWiresCount, operatingCurrent, systemVoltage,
                                articleDescr, articlePartNr, artRefPartNr, artRefVariantNr, artRefReferencePos
                            };
                    }
                    cableMap[cableName].Add(new string[] {
                            wireNumber, crossSection, wireLength, source, target,
                            wireColor, colorNumber, potential, signalName
                        });
                }

                // --- JSON for this connection ---
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

                // All CDPs individually
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
        //  CABLES (grouped)
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
                json.AppendLine("      \"articleRefPartNr\": " + JsonEscape(SafeIdx(ci, 9)) + ",");
                json.AppendLine("      \"articleRefVariantNr\": " + JsonEscape(SafeIdx(ci, 10)) + ",");
                json.AppendLine("      \"articleRefReferencePos\": " + JsonEscape(SafeIdx(ci, 11)) + ",");
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

        return json.ToString();
    }

    // =====================================================================
    //  Helper methods
    // =====================================================================


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
        out string description, out string partNr,
        out string artRefPartNr, out string artRefVariantNr, out string artRefReferencePos)
    {
        currentCapacity = "";
        ratedVoltage = "";
        description = "";
        partNr = "";
        artRefPartNr = "";
        artRefVariantNr = "";
        artRefReferencePos = "";
        try
        {
            if (articlePropsEnumType == null) return;

            Array artArr = SafeGetPropertyValue(cable, "ArticleReferences") as Array;
            if (artArr == null || artArr.Length == 0) return;

            object firstArtRef = artArr.GetValue(0);
            if (firstArtRef == null) return;

            artRefPartNr = SafeGetPropertyString(firstArtRef, "PartNr");
            artRefVariantNr = SafeGetPropertyString(firstArtRef, "VariantNr");
            artRefReferencePos = SafeGetPropertyString(firstArtRef, "ReferencePos");

            object article = SafeGetPropertyValue(firstArtRef, "Article");
            if (article == null) return;

            object artProps = SafeGetPropertyValue(article, "Properties");
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

    public static object SafeGetPropertyValue(object obj, string propertyName)
    {
        if (obj == null) return null;
        try
        {
            PropertyInfo prop = obj.GetType().GetProperty(propertyName, DeclaredPublic) ?? obj.GetType().GetProperty(propertyName);
            if (prop != null)
            {
                return prop.GetValue(obj, null);
            }
        }
        catch { }
        return null;
    }

    public static string SafeGetPropertyString(object obj, string propertyName)
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
            request.Timeout = 500;
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
            // Globale Defaults nur einmal setzen; vermeidet vor allem den "Expect: 100-Continue"-
            // Hänger gegenüber Reverse-Proxies (lapp-hack.de), der sonst pro Request mehrere
            // Sekunden Wartezeit verursacht.
            ServicePointManager.Expect100Continue = false;
            ServicePointManager.SecurityProtocol =
                (SecurityProtocolType)3072 /* Tls12 */ | (SecurityProtocolType)768 /* Tls11 */;
            ServicePointManager.DefaultConnectionLimit = 20;

            var request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = "POST";
            request.ContentType = "application/json; charset=utf-8";
            request.Headers["Authorization"] = "Bearer " + token;
            request.ServicePoint.Expect100Continue = false;
            request.KeepAlive = true;
            request.Timeout = 120000;
            request.ReadWriteTimeout = 120000;
            request.AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate;
            request.Headers["Accept-Encoding"] = "gzip";

            // Body gzip-komprimieren – schrumpft den ~1 MB JSON auf ~50–100 KB
            // und reduziert den Upload über DSL/4G drastisch.
            byte[] raw = Encoding.UTF8.GetBytes(json);
            byte[] data;
            using (var ms = new MemoryStream())
            {
                using (var gz = new System.IO.Compression.GZipStream(ms, System.IO.Compression.CompressionMode.Compress, true))
                {
                    gz.Write(raw, 0, raw.Length);
                }
                data = ms.ToArray();
            }
            request.Headers["Content-Encoding"] = "gzip";
            log.AppendLine("Payload: " + raw.Length + " B -> " + data.Length + " B (gzip)");
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

public class CopilotAction
{
    [Eplan.EplApi.Scripting.DeclareAction("CopilotAction")]
    public void Execute()
    {
        CopilotForm form = new CopilotForm();
        form.ShowDialog();
    }
}

public class CopilotForm : Form
{
    private Control webView;

    public CopilotForm()
    {
        this.Text = "Cable Copilot";
        this.Size = new Size(1200, 800);
        this.StartPosition = FormStartPosition.CenterScreen;
        
        try 
        {
            string eplanBin = AppDomain.CurrentDomain.BaseDirectory;
            string dllPath = Path.Combine(eplanBin, "Microsoft.Web.WebView2.WinForms.dll");
            
            if (!File.Exists(dllPath))
            {
                Label err = new Label();
                err.Text = "WebView2 DLL nicht gefunden in: " + dllPath;
                err.Dock = DockStyle.Fill;
                this.Controls.Add(err);
                return;
            }

            // Dynamically load WebView2 (avoids compiler errors in EPLAN script)
            Assembly wvAsm = Assembly.LoadFrom(dllPath);
            Type wvType = wvAsm.GetType("Microsoft.Web.WebView2.WinForms.WebView2");
            webView = (Control)Activator.CreateInstance(wvType);
            webView.Dock = DockStyle.Fill;
            this.Controls.Add(webView);
            
            // Prepare initialization (set UserDataFolder to temp for write permissions)
            Type propsType = wvAsm.GetType("Microsoft.Web.WebView2.WinForms.CoreWebView2CreationProperties");
            object props = Activator.CreateInstance(propsType);
            
            string tempFolder = Path.Combine(Path.GetTempPath(), "EplanWebView2Hack");
            propsType.GetProperty("UserDataFolder").SetValue(props, tempFolder);
            
            wvType.GetProperty("CreationProperties").SetValue(webView, props);
            
            // Setting the Source triggers WebView2 initialization
            string baseUrl = GetApiBaseUrl();
            Uri targetUri = new Uri(baseUrl + "/copilot?embedded=true");
            wvType.GetProperty("Source").SetValue(webView, targetUri);
        }
        catch (Exception ex)
        {
            Label lbl = new Label();
            lbl.Text = "Fehler beim Laden von WebView2:\n\n" + ex.ToString();
            lbl.Dock = DockStyle.Fill;
            this.Controls.Add(lbl);
        }
    }

    private static string GetApiBaseUrl()
    {
        try
        {
            var request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:8000/health");
            request.Timeout = 500;
            request.Method = "HEAD";
            using (request.GetResponse()) { }
            return "http://127.0.0.1:8000";
        }
        catch
        {
            return "https://lapp-hack.de";
        }
    }
}

public class LappWizardForm : Form
{
    private Control webView;

    public LappWizardForm(string url)
    {
        this.Text = "Lapp Wizard";
        this.Size = new Size(1400, 900);
        this.StartPosition = FormStartPosition.CenterScreen;
        this.WindowState = FormWindowState.Maximized;

        // TableLayoutPanel splits the form into toolbar row + webview row.
        // WebView2 is an Air-space (HWND) control and always paints over WinForms siblings,
        // so we must keep it in its own non-overlapping container cell.
        TableLayoutPanel layout = new TableLayoutPanel();
        layout.Dock = DockStyle.Fill;
        layout.RowCount = 2;
        layout.ColumnCount = 1;
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 80f));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
        layout.Padding = new System.Windows.Forms.Padding(0);
        layout.Margin = new System.Windows.Forms.Padding(0);
        this.Controls.Add(layout);

        // Toolbar row
        Panel toolbar = new Panel();
        toolbar.Dock = DockStyle.Fill;
        toolbar.BackColor = System.Drawing.Color.FromArgb(243, 146, 0); // Lapp orange
        toolbar.Padding = new System.Windows.Forms.Padding(10, 6, 10, 6);

        Button closeBtn = new Button();
        closeBtn.Text = "\u2190  Zurück zu EPLAN";
        closeBtn.FlatStyle = FlatStyle.Flat;
        closeBtn.FlatAppearance.BorderColor = System.Drawing.Color.FromArgb(220, 120, 0);
        closeBtn.FlatAppearance.MouseOverBackColor = System.Drawing.Color.FromArgb(220, 120, 0);
        closeBtn.BackColor = System.Drawing.Color.FromArgb(220, 120, 0);
        closeBtn.ForeColor = System.Drawing.Color.White;
        closeBtn.Font = new System.Drawing.Font("Segoe UI", 10f, System.Drawing.FontStyle.Bold);
        closeBtn.AutoSize = true;
        closeBtn.Cursor = Cursors.Hand;
        closeBtn.Location = new System.Drawing.Point(10, 8);
        closeBtn.Padding = new System.Windows.Forms.Padding(8, 2, 8, 2);
        closeBtn.Click += (s, e) => this.Close();
        toolbar.Controls.Add(closeBtn);

        layout.Controls.Add(toolbar, 0, 0);

        // WebView2 row – isolated in its own panel so its HWND can't bleed into the toolbar
        Panel webViewContainer = new Panel();
        webViewContainer.Dock = DockStyle.Fill;
        layout.Controls.Add(webViewContainer, 0, 1);

        try
        {
            string eplanBin = AppDomain.CurrentDomain.BaseDirectory;
            string dllPath = Path.Combine(eplanBin, "Microsoft.Web.WebView2.WinForms.dll");

            if (!File.Exists(dllPath))
            {
                Label err = new Label();
                err.Text = "WebView2 DLL nicht gefunden in: " + dllPath;
                err.Dock = DockStyle.Fill;
                webViewContainer.Controls.Add(err);
                return;
            }

            Assembly wvAsm = Assembly.LoadFrom(dllPath);
            Type wvType = wvAsm.GetType("Microsoft.Web.WebView2.WinForms.WebView2");
            webView = (Control)Activator.CreateInstance(wvType);
            webView.Dock = DockStyle.Fill;

            Type propsType = wvAsm.GetType("Microsoft.Web.WebView2.WinForms.CoreWebView2CreationProperties");
            object props = Activator.CreateInstance(propsType);

            string tempFolder = Path.Combine(Path.GetTempPath(), "EplanWebView2LappWizard");
            propsType.GetProperty("UserDataFolder").SetValue(props, tempFolder);

            wvType.GetProperty("CreationProperties").SetValue(webView, props);
            // embedded=true hides the header in machine.html
            string embeddedUrl = url.Contains("?") ? url + "&embedded=true" : url + "?embedded=true";
            wvType.GetProperty("Source").SetValue(webView, new Uri(embeddedUrl));

            webViewContainer.Controls.Add(webView);
        }
        catch (Exception ex)
        {
            Label lbl = new Label();
            lbl.Text = "Fehler beim Laden von WebView2:\n\n" + ex.ToString();
            lbl.Dock = DockStyle.Fill;
            webViewContainer.Controls.Add(lbl);
        }
    }
}

public class ReplaceSyncAction
{
    // Hilfsfunktion für Enum-Parsing (aus dem unteren Bereich kopiert)
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

    // Hilfsfunktion für Indexer-Findung (aus dem unteren Bereich kopiert)
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

    private static readonly BindingFlags DeclaredPublic = BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly;

    [Eplan.EplApi.Scripting.DeclareAction("ReplaceSyncAction")]
    public void Execute()
    {
        string token = "";
        if (System.Windows.Forms.Clipboard.ContainsText())
        {
            string cb = System.Windows.Forms.Clipboard.GetText().Trim();
            if (cb.Length == 32) token = cb;
        }

        using (System.Windows.Forms.Form prompt = new System.Windows.Forms.Form())
        {
            prompt.Text = "Lapp Sync - Token eingeben";
            prompt.FormBorderStyle = System.Windows.Forms.FormBorderStyle.FixedDialog;
            prompt.MaximizeBox = false;
            prompt.MinimizeBox = false;
            prompt.ShowIcon = false;
            prompt.ShowInTaskbar = false;
            prompt.StartPosition = System.Windows.Forms.FormStartPosition.CenterScreen;
            prompt.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font;
            prompt.AutoSize = true;
            prompt.AutoSizeMode = System.Windows.Forms.AutoSizeMode.GrowAndShrink;
            prompt.Padding = new System.Windows.Forms.Padding(16);
            prompt.MinimumSize = new Size(560, 220);

            System.Windows.Forms.TableLayoutPanel layout = new System.Windows.Forms.TableLayoutPanel();
            layout.AutoSize = true;
            layout.AutoSizeMode = System.Windows.Forms.AutoSizeMode.GrowAndShrink;
            layout.ColumnCount = 1;
            layout.RowCount = 3;
            layout.Dock = System.Windows.Forms.DockStyle.Top;
            layout.Margin = new System.Windows.Forms.Padding(0);

            System.Windows.Forms.Label label = new System.Windows.Forms.Label();
            label.AutoSize = true;
            label.Text = "Bitte den 32-stelligen Maschinen-Token eingeben:";
            label.MaximumSize = new Size(500, 0);
            label.Margin = new System.Windows.Forms.Padding(0, 0, 0, 12);

            System.Windows.Forms.TextBox textBox = new System.Windows.Forms.TextBox();
            textBox.Width = 500;
            textBox.Text = token;
            textBox.Margin = new System.Windows.Forms.Padding(0, 0, 0, 20);

            System.Windows.Forms.Button okButton = new System.Windows.Forms.Button();
            okButton.Text = "OK";
            okButton.DialogResult = System.Windows.Forms.DialogResult.OK;
            okButton.Size = new Size(75, 27);

            System.Windows.Forms.Button cancelButton = new System.Windows.Forms.Button();
            cancelButton.Text = "Abbrechen";
            cancelButton.DialogResult = System.Windows.Forms.DialogResult.Cancel;
            cancelButton.Size = new Size(75, 27);

            System.Windows.Forms.FlowLayoutPanel buttonPanel = new System.Windows.Forms.FlowLayoutPanel();
            buttonPanel.AutoSize = true;
            buttonPanel.AutoSizeMode = System.Windows.Forms.AutoSizeMode.GrowAndShrink;
            buttonPanel.Dock = System.Windows.Forms.DockStyle.Fill;
            buttonPanel.FlowDirection = System.Windows.Forms.FlowDirection.RightToLeft;
            buttonPanel.WrapContents = false;
            buttonPanel.Margin = new System.Windows.Forms.Padding(0);

            buttonPanel.Controls.Add(cancelButton);
            buttonPanel.Controls.Add(okButton);

            layout.Controls.Add(label, 0, 0);
            layout.Controls.Add(textBox, 0, 1);
            layout.Controls.Add(buttonPanel, 0, 2);
            prompt.Controls.Add(layout);
            prompt.AcceptButton = okButton;
            prompt.CancelButton = cancelButton;

            if (prompt.ShowDialog() != System.Windows.Forms.DialogResult.OK)
                return;

            token = textBox.Text.Trim();
        }

        if (token.Length != 32)
        {
            new Decider().Decide(
                EnumDecisionType.eOkDecision,
                "Der Token muss genau 32 Zeichen lang sein.",
                "Lapp Sync - Ungültiger Token",
                EnumDecisionReturn.eOK, EnumDecisionReturn.eOK,
                "", false, EnumDecisionIcon.eFATALERROR);
            return;
        }

        EnumDecisionReturn conf = new Decider().Decide(
            EnumDecisionType.eOkCancelDecision,
            "Soll der eingegebene Token verwendet werden?\n\nToken: " + token,
            "Lapp Sync - Token bestätigen",
            EnumDecisionReturn.eOK, EnumDecisionReturn.eOK,
            "", false, EnumDecisionIcon.eQUESTION);

        if (conf != EnumDecisionReturn.eOK) return;

        try 
        {
            string url = GetApiBaseUrl() + "/api/machine-db/" + token + "/replacements";
            string json = "";
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = "GET";
            request.Accept = "application/json";

            try {
                using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                using (Stream stream = response.GetResponseStream())
                using (StreamReader reader = new StreamReader(stream))
                {
                    json = reader.ReadToEnd();
                }
            } catch (WebException wex) {
                new Decider().Decide(EnumDecisionType.eOkDecision, "Fehler beim Abrufen der Ersetzungen (Token falsch?): " + wex.Message, "Lapp Sync", EnumDecisionReturn.eOK, EnumDecisionReturn.eOK, "", false, EnumDecisionIcon.eFATALERROR);
                return;
            }

            // Parse replacements as Dictionary<string, Dictionary<string, object>> for all fields
            var replacements = new Dictionary<string, Dictionary<string, object>>();
            var blocks = System.Text.RegularExpressions.Regex.Matches(json, @"\{[^{}]+\}");
            foreach (System.Text.RegularExpressions.Match block in blocks)
            {
                var mCable = System.Text.RegularExpressions.Regex.Match(block.Value, @"\""cable_name\""\s*:\s*\""([^\""]+)\""");
                var mArt = System.Text.RegularExpressions.Regex.Match(block.Value, @"\""recommended_article_nr\""\s*:\s*(?:null|\""([^\""]+)\"")");
                var mMm2 = System.Text.RegularExpressions.Regex.Match(block.Value, @"\""recommended_mm2\""\s*:\s*([0-9.]+)");
                var mType = System.Text.RegularExpressions.Regex.Match(block.Value, @"\""recommended_cable_type\""\s*:\s*(?:null|\""([^\""]+)\"")");

                if (mCable.Success && mArt.Success && mArt.Groups[1].Success)
                {
                    string cableName = mCable.Groups[1].Value;
                    string artValue = mArt.Groups[1].Value.Trim();
                    if (!string.IsNullOrEmpty(artValue)) {
                        if (!artValue.StartsWith("LAPP.")) {
                            artValue = "LAPP." + artValue;
                        }
                        var dict = new Dictionary<string, object>();
                        dict["recommended_article_nr"] = artValue;
                        if (mMm2.Success) dict["recommended_mm2"] = mMm2.Groups[1].Value;
                        if (mType.Success && mType.Groups[1].Success) dict["recommended_cable_type"] = mType.Groups[1].Value;
                        replacements[cableName] = dict;
                    }
                }
            }

            if (replacements.Count == 0)
            {
                new Decider().Decide(EnumDecisionType.eOkDecision, "Keine offenen zu aktualisierenden Kabel gefunden.\n\nAPI-Antwort:\n" + json, "Lapp Sync", EnumDecisionReturn.eOK, EnumDecisionReturn.eOK, "", false, EnumDecisionIcon.eINFORMATION);
                return;
            }

            Eplan.EplApi.Base.Progress progress = new Eplan.EplApi.Base.Progress("SimpleProgress");
            progress.ShowImmediately();
            progress.SetAllowCancel(false);
            progress.SetNeededSteps(3);
            progress.SetTitle("Lapp Sync");
            progress.SetActionText("Aktualisiere Kabel...");
            progress.Step(1);
            
            int updateCount = 0;
            StringBuilder report = new StringBuilder();
            StringBuilder debugCableNames = new StringBuilder();
            int debugCableCount = 0;
            try
            {
                Assembly dataModelAsm = null;
                Assembly heServicesAsm = null;
                Assembly masterDataAsm = null;
                foreach (Assembly asm in AppDomain.CurrentDomain.GetAssemblies())
                {
                    string name = asm.GetName().Name;
                    if (name == "Eplan.EplApi.DataModelu") dataModelAsm = asm;
                    if (name == "Eplan.EplApi.HEServicesu") heServicesAsm = asm;
                    if (name == "Eplan.EplApi.MasterDatau") masterDataAsm = asm;
                }

                // Falls MasterData-Assembly nicht im AppDomain, versuche sie neben den anderen zu finden
                if (masterDataAsm == null && dataModelAsm != null)
                {
                    try
                    {
                        string dir = Path.GetDirectoryName(dataModelAsm.Location);
                        string mdPath = Path.Combine(dir, "Eplan.EplApi.MasterDatau.dll");
                        if (File.Exists(mdPath))
                        {
                            masterDataAsm = Assembly.LoadFrom(mdPath);
                        }
                    }
                    catch { }
                }

                if (dataModelAsm == null || heServicesAsm == null) return;

                Type projectType = dataModelAsm.GetType("Eplan.EplApi.DataModel.Project");
                Type lockingStepType = dataModelAsm.GetType("Eplan.EplApi.DataModel.LockingStep");
                Type selSetType = heServicesAsm.GetType("Eplan.EplApi.HEServices.SelectionSet");

                using (IDisposable lockingStep = (IDisposable)Activator.CreateInstance(lockingStepType))
                {
                    object selSet = Activator.CreateInstance(selSetType);
                    MethodInfo getCurrentProject = selSetType.GetMethod("GetCurrentProject", new Type[] { typeof(bool) });
                    object project = getCurrentProject.Invoke(selSet, new object[] { true });

                    if (project == null) return;

                    Type finderType = dataModelAsm.GetType("Eplan.EplApi.DataModel.DMObjectsFinder");
                    Type conFilterType = dataModelAsm.GetType("Eplan.EplApi.DataModel.ConnectionsFilter");

                    ConstructorInfo finderCtor = finderType.GetConstructor(new Type[] { projectType });
                    object finder = finderCtor.Invoke(new object[] { project });

                    object conFilter = Activator.CreateInstance(conFilterType);
                    MethodInfo getConns = finderType.GetMethod("GetConnections", new Type[] { conFilterType });
                    Array connections = (Array)getConns.Invoke(finder, new object[] { conFilter });

                    HashSet<string> processedCables = new HashSet<string>();

                    if (connections != null)
                    {
                        foreach (object conn in connections)
                        {
                            Type connType = conn.GetType();
                            PropertyInfo cableProp = connType.GetProperty("CableDefinitionLine", DeclaredPublic) ?? connType.GetProperty("CableDefinitionLine");
                            if (cableProp != null)
                            {
                                object cable = cableProp.GetValue(conn, null);
                                if (cable != null)
                                {
                                    string cblName = SafeGetPropertyString(cable, "Name");
                                    if (!string.IsNullOrEmpty(cblName) && !processedCables.Contains(cblName))
                                    {
                                        if (debugCableCount < 20)
                                        {
                                            debugCableNames.AppendLine(cblName);
                                            debugCableCount++;
                                        }
                                    }
                                    if (!string.IsNullOrEmpty(cblName) && !processedCables.Contains(cblName) && replacements.ContainsKey(cblName))
                                    {
                                        processedCables.Add(cblName);
                                        var repl = replacements[cblName];
                                        string newArt = repl.ContainsKey("recommended_article_nr") ? (string)repl["recommended_article_nr"] : null;
                                        
                                        // Prüfen ob neuer Artikel in Stammdaten existiert
                                        bool articleExists = true;
                                        string articleCheckInfo = "";
                                        if (masterDataAsm != null)
                                        {
                                            try
                                            {
                                                Type pmType = masterDataAsm.GetType("Eplan.EplApi.MasterData.MDPartsManagement");
                                                if (pmType != null)
                                                {
                                                    object pm = Activator.CreateInstance(pmType);
                                                    MethodInfo openDb = pmType.GetMethod("OpenDatabase", Type.EmptyTypes);
                                                    if (openDb != null)
                                                    {
                                                        object db = openDb.Invoke(pm, null);
                                                        if (db != null)
                                                        {
                                                            Type dbType = db.GetType();
                                                            MethodInfo getPart = dbType.GetMethod("GetPart", new Type[] { typeof(string) });
                                                            if (getPart != null)
                                                            {
                                                                object part = getPart.Invoke(db, new object[] { newArt });
                                                                if (part == null)
                                                                {
                                                                    articleExists = false;
                                                                    articleCheckInfo = "nicht in Stammdaten";
                                                                    
                                                                    // User fragen ob Artikel angelegt werden soll
                                                                    EnumDecisionReturn userChoice = new Decider().Decide(
                                                                        EnumDecisionType.eYesNoDecision,
                                                                        string.Format(
                                                                            "Der Artikel \"{0}\" existiert nicht in der Stammdatenbank.\n\n" +
                                                                            "Soll er jetzt als leerer Artikel angelegt werden?\n" +
                                                                            "(Die Artikeldaten können danach manuell gepflegt werden.)",
                                                                            newArt),
                                                                        "Artikel nicht gefunden",
                                                                        EnumDecisionReturn.eYES, EnumDecisionReturn.eYES,
                                                                        "", false, EnumDecisionIcon.eQUESTION);
                                                                    
                                                                    if (userChoice == EnumDecisionReturn.eYES)
                                                                    {
                                                                        MethodInfo addPart = dbType.GetMethod("AddPart", new Type[] { typeof(string) });
                                                                        if (addPart != null)
                                                                        {
                                                                            addPart.Invoke(db, new object[] { newArt });
                                                                            articleExists = true;
                                                                            articleCheckInfo = "neu angelegt (leer)";
                                                                        }
                                                                    }
                                                                }
                                                                else
                                                                {
                                                                    articleCheckInfo = "in Stammdaten gefunden";
                                                                }
                                                            }
                                                            
                                                            // DB schließen
                                                            MethodInfo closeDb = dbType.GetMethod("Close", Type.EmptyTypes);
                                                            if (closeDb != null)
                                                            {
                                                                closeDb.Invoke(db, null);
                                                            }
                                                        }
                                                        else
                                                        {
                                                            articleCheckInfo = "DB konnte nicht geöffnet werden";
                                                        }
                                                    }
                                                }
                                            }
                                            catch (Exception mdEx)
                                            {
                                                articleCheckInfo = "Stammdaten-Fehler: " + (mdEx.InnerException != null ? mdEx.InnerException.Message : mdEx.Message);
                                                // Bei Fehler trotzdem fortfahren
                                                articleExists = true;
                                            }
                                        }
                                        else
                                        {
                                            articleCheckInfo = "MasterData-Assembly nicht geladen";
                                        }
                                        
                                        if (!articleExists)
                                        {
                                            report.AppendLine(string.Format("{0}: Übersprungen (Artikel {1} nicht angelegt)", cblName, newArt));
                                            continue;
                                        }
                                        
                                        // Alten Artikel merken für Report
                                        string oldArt = "";
                                        Array artArr = SafeGetPropertyValue(cable, "ArticleReferences") as Array;
                                        
                                        // 1. Alle bestehenden ArticleReferences entfernen
                                        if (artArr != null && artArr.Length > 0)
                                        {
                                            // Erst alte PartNr merken
                                            object firstArtRef = artArr.GetValue(0);
                                            if (firstArtRef != null)
                                            {
                                                oldArt = SafeGetPropertyString(firstArtRef, "PartNr");
                                            }
                                            
                                            // Rückwärts iterieren und alle entfernen
                                            for (int i = artArr.Length - 1; i >= 0; i--)
                                            {
                                                object artRef = artArr.GetValue(i);
                                                if (artRef != null)
                                                {
                                                    MethodInfo removeMethod = artRef.GetType().GetMethod("RemoveArticleReference", Type.EmptyTypes);
                                                    if (removeMethod != null)
                                                    {
                                                        removeMethod.Invoke(artRef, null);
                                                    }
                                                }
                                            }
                                        }


                                        // 2. Neuen Artikel hinzufügen via Instanz-Methode auf dem Kabel (Function)
                                        //    Function.AddArticleReference(String partNr, String variant, UInt32 count, Boolean bClean)
                                        MethodInfo addArtRefMethod = cable.GetType().GetMethod("AddArticleReference",
                                            new Type[] { typeof(string), typeof(string), typeof(uint), typeof(bool) });
                                        if (addArtRefMethod != null)
                                        {
                                            addArtRefMethod.Invoke(cable, new object[] { newArt, "", 1u, true });
                                        }
                                        else
                                        {
                                            // Fallback: Überladung ohne bClean
                                            MethodInfo addArtRefMethod2 = cable.GetType().GetMethod("AddArticleReference",
                                                new Type[] { typeof(string), typeof(string), typeof(uint) });
                                            if (addArtRefMethod2 != null)
                                            {
                                                addArtRefMethod2.Invoke(cable, new object[] { newArt, "", 1u });
                                            }
                                            else
                                            {
                                                // Letzter Fallback: nur PartNr
                                                MethodInfo addArtRefMethod3 = cable.GetType().GetMethod("AddArticleReference",
                                                    new Type[] { typeof(string) });
                                                if (addArtRefMethod3 != null)
                                                {
                                                    addArtRefMethod3.Invoke(cable, new object[] { newArt });
                                                }
                                            }
                                        }

                                        // 2b. Technische Felder setzen (z.B. Querschnitt)
                                        string techDebug = "";
                                        try {
                                            if (repl.ContainsKey("recommended_mm2")) {
                                                double mm2;
                                                if (double.TryParse(repl["recommended_mm2"].ToString(), System.Globalization.NumberStyles.Any, System.Globalization.CultureInfo.InvariantCulture, out mm2)) {
                                                    // Setze CableWireCrossSection
                                                    PropertyInfo propsProp = cable.GetType().GetProperty("Properties", DeclaredPublic) ?? cable.GetType().GetProperty("Properties");
                                                    if (propsProp != null) {
                                                        object props = propsProp.GetValue(cable, null);
                                                        if (props != null) {
                                                            Type funcPropsEnumType = cable.GetType().Assembly.GetType("Eplan.EplApi.DataModel.Properties+Function");
                                                            object propCableWireCrossSection = SafeEnumParse(funcPropsEnumType, "FUNC_CABLEWIRECROSSSECTION", "FUNC_CABLEWIRECROSSSECTION");
                                                            PropertyInfo funcIndexer = FindIndexer(props, funcPropsEnumType);
                                                            if (funcIndexer != null && propCableWireCrossSection != null) {
                                                                // Get PropertyValue object via indexer, then set its value
                                                                object propValue = funcIndexer.GetValue(props, new object[] { propCableWireCrossSection });
                                                                if (propValue != null) {
                                                                    // Try Set(double) first, then Set(string)
                                                                    MethodInfo setDouble = propValue.GetType().GetMethod("Set", new Type[] { typeof(double) });
                                                                    if (setDouble != null) {
                                                                        setDouble.Invoke(propValue, new object[] { mm2 });
                                                                        techDebug = "CableWireCrossSection gesetzt (double): " + mm2;
                                                                    } else {
                                                                        MethodInfo setString = propValue.GetType().GetMethod("Set", new Type[] { typeof(string) });
                                                                        if (setString != null) {
                                                                            setString.Invoke(propValue, new object[] { mm2.ToString(System.Globalization.CultureInfo.InvariantCulture) });
                                                                            techDebug = "CableWireCrossSection gesetzt (string): " + mm2;
                                                                        } else {
                                                                            techDebug = "PropertyValue.Set-Methode nicht gefunden. Verfügbar: " + string.Join(", ", Array.ConvertAll(propValue.GetType().GetMethods(), m => m.Name));
                                                                        }
                                                                    }
                                                                } else {
                                                                    techDebug = "PropertyValue ist null für FUNC_CABLEWIRECROSSSECTION.";
                                                                }
                                                            } else {
                                                                techDebug = "Feld FUNC_CABLEWIRECROSSSECTION nicht gefunden.";
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        } catch (Exception techEx) {
                                            techDebug = "Fehler beim Setzen technischer Felder: " + techEx.Message;
                                        }

                                        // 3. Gerätedaten aktualisieren (DeviceService.UpdateDevice)
                                        //    Überträgt Artikeldaten (Querschnitt, Adernzahl, etc.) auf das Kabel
                                        string deviceUpdateInfo = "";
                                        try
                                        {
                                            Type storableObjectType = dataModelAsm.GetType("Eplan.EplApi.DataModel.StorableObject");
                                            Type deviceServiceType = heServicesAsm.GetType("Eplan.EplApi.HEServices.DeviceService");
                                            if (deviceServiceType != null && storableObjectType != null)
                                            {
                                                object deviceService = Activator.CreateInstance(deviceServiceType);
                                                MethodInfo updateMethod = deviceServiceType.GetMethod("UpdateDevice", new Type[] { storableObjectType });
                                                if (updateMethod != null)
                                                {
                                                    updateMethod.Invoke(deviceService, new object[] { cable });
                                                    deviceUpdateInfo = "OK";
                                                }
                                                else
                                                {
                                                    deviceUpdateInfo = "UpdateDevice-Methode nicht gefunden";
                                                }
                                                if (deviceService is IDisposable)
                                                    ((IDisposable)deviceService).Dispose();
                                            }
                                            else
                                            {
                                                deviceUpdateInfo = "DeviceService/StorableObject-Typ nicht gefunden";
                                            }
                                        }
                                        catch (Exception devEx)
                                        {
                                            deviceUpdateInfo = "Fehler: " + (devEx.InnerException != null ? devEx.InnerException.Message : devEx.Message);
                                        }

                                        // 4. Kabeltyp-Bezeichnung setzen (FUNC_CABLETYPE auf dem Cable-Objekt)
                                        //    Property #20040 = "Cable / Conduit: Type" – das ist was die Kabelübersicht als "Kabeltyp" zeigt
                                        string typeDebug = "";
                                        string cableType = repl.ContainsKey("recommended_cable_type") ? (string)repl["recommended_cable_type"] : "";
                                        if (!string.IsNullOrEmpty(cableType))
                                        {
                                            try
                                            {
                                                PropertyInfo cablePropsProp2 = cable.GetType().GetProperty("Properties", DeclaredPublic)
                                                    ?? cable.GetType().GetProperty("Properties");
                                                if (cablePropsProp2 != null)
                                                {
                                                    object cableProps2 = cablePropsProp2.GetValue(cable, null);
                                                    if (cableProps2 != null)
                                                    {
                                                        Type funcPropsEnumType2 = cable.GetType().Assembly.GetType("Eplan.EplApi.DataModel.Properties+Function");
                                                        object propCableType = SafeEnumParse(funcPropsEnumType2, "FUNC_CABLETYPE", "FUNC_CABLETYPE");
                                                        PropertyInfo funcIndexer2 = FindIndexer(cableProps2, funcPropsEnumType2);
                                                        if (funcIndexer2 != null && propCableType != null)
                                                        {
                                                            object propValue = funcIndexer2.GetValue(cableProps2, new object[] { propCableType });
                                                            if (propValue != null)
                                                            {
                                                                MethodInfo setStr = propValue.GetType().GetMethod("Set", new Type[] { typeof(string) });
                                                                if (setStr != null)
                                                                {
                                                                    setStr.Invoke(propValue, new object[] { cableType });
                                                                    typeDebug = "FUNC_CABLETYPE gesetzt: " + cableType;
                                                                }
                                                                else
                                                                {
                                                                    typeDebug = "Set(string) nicht gefunden auf FUNC_CABLETYPE. Methoden: " +
                                                                        string.Join(", ", Array.ConvertAll(propValue.GetType().GetMethods(), m => m.Name));
                                                                }
                                                            }
                                                            else
                                                            {
                                                                typeDebug = "PropertyValue null für FUNC_CABLETYPE";
                                                            }
                                                        }
                                                        else
                                                        {
                                                            typeDebug = string.Format("FUNC_CABLETYPE: Enum={0} Indexer={1}",
                                                                propCableType != null ? "OK" : "null", funcIndexer2 != null ? "OK" : "null");
                                                        }
                                                    }
                                                }
                                            }
                                            catch (Exception typeEx)
                                            {
                                                typeDebug = "Fehler: " + (typeEx.InnerException != null ? typeEx.InnerException.Message : typeEx.Message);
                                            }
                                        }
                                        
                                        updateCount++;
                                        report.AppendLine(string.Format("{0}: {1} -> {2}{3} [Artikel: {4}] [DeviceUpdate: {5}] [Tech: {6}] [Type: {7}]", 
                                            cblName, oldArt, newArt, 
                                            !string.IsNullOrEmpty(cableType) ? " (" + cableType + ")" : "",
                                            articleCheckInfo, deviceUpdateInfo, techDebug, typeDebug));
                                    }
                                }
                            }
                        }
                    }

                    // --- Verbindungen programmatisch aktualisieren ---
                    if (updateCount > 0)
                    {
                        try
                        {
                            Type generateType = heServicesAsm.GetType("Eplan.EplApi.HEServices.Generate");
                            if (generateType != null)
                            {
                                object generateObj = Activator.CreateInstance(generateType);
                                MethodInfo genConns = generateType.GetMethod("Connections", new Type[] { project.GetType() });
                                if (genConns != null)
                                {
                                    genConns.Invoke(generateObj, new object[] { project });
                                }
                            }
                        }
                        catch (Exception ex)
                        {
                            report.AppendLine("\nFehler beim Aktualisieren der Verbindungen: " + ex.Message);
                        }

                        // --- Kabelübersicht / Auswertungen regenerieren ---
                        try
                        {
                            Type reportsType = heServicesAsm.GetType("Eplan.EplApi.HEServices.Reports");
                            if (reportsType != null)
                            {
                                object reportsObj = Activator.CreateInstance(reportsType);
                                MethodInfo genProject = reportsType.GetMethod("GenerateProject", new Type[] { project.GetType() });
                                if (genProject != null)
                                {
                                    genProject.Invoke(reportsObj, new object[] { project });
                                    report.AppendLine("\nAuswertungen (inkl. Kabelübersicht) wurden regeneriert.");
                                }
                                else
                                {
                                    report.AppendLine("\nReports.GenerateProject-Methode nicht gefunden.");
                                }
                            }
                            else
                            {
                                report.AppendLine("\nReports-Typ nicht gefunden in HEServices.");
                            }
                        }
                        catch (Exception ex)
                        {
                            report.AppendLine("\nFehler beim Regenerieren der Auswertungen: " + ex.Message);
                            if (ex.InnerException != null)
                                report.AppendLine("  Inner: " + ex.InnerException.Message);
                        }
                    }
                }
            }
            finally
            {
                progress.EndPart(true);

                if (updateCount > 0) {
                    new Decider().Decide(EnumDecisionType.eOkDecision, 
                        string.Format("Sync erfolgreich beendet.\nEs wurden {0} Kabel aus der Maschine aktualisiert:\n\n{1}", updateCount, report.ToString()), 
                        "Lapp Sync", EnumDecisionReturn.eOK, EnumDecisionReturn.eOK, "", false, EnumDecisionIcon.eINFORMATION);
                } else {
                    StringBuilder searchedFor = new StringBuilder();
                    foreach (string k in replacements.Keys) { if (searchedFor.Length > 0) searchedFor.Append(", "); searchedFor.Append(k); }
                    new Decider().Decide(EnumDecisionType.eOkDecision, 
                        string.Format("Sync beendet, aber keine passenden Kabelnamen im Projekt gefunden.\n\nGesucht: {0}\n\nGefundene Kabel im Projekt (erste 20):\n{1}", searchedFor.ToString(), debugCableNames.ToString()), 
                        "Lapp Sync", EnumDecisionReturn.eOK, EnumDecisionReturn.eOK, "", false, EnumDecisionIcon.eINFORMATION);
                }
            }
        }
        catch (Exception ex)
        {
            new Decider().Decide(EnumDecisionType.eOkDecision, "Fehler: " + ex.Message, "Lapp Sync", EnumDecisionReturn.eOK, EnumDecisionReturn.eOK, "", false, EnumDecisionIcon.eFATALERROR);
        }
    }

    private static string GetApiBaseUrl()
    {
        try
        {
            var request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:8000/health");
            request.Timeout = 500;
            request.Method = "HEAD";
            using (request.GetResponse()) { }
            return "http://127.0.0.1:8000";
        }
        catch
        {
            return "https://lapp-hack.de";
        }
    }

    private static object SafeGetPropertyValue(object obj, string propertyName)
    {
        if (obj == null) return null;
        try
        {
            PropertyInfo prop = obj.GetType().GetProperty(propertyName, DeclaredPublic) ?? obj.GetType().GetProperty(propertyName);
            if (prop != null)
            {
                return prop.GetValue(obj, null);
            }
        }
        catch { }
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
}
