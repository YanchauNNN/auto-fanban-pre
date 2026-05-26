using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Web.Script.Serialization;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Runtime;

namespace Module5CadBridge;

public class Commands
{
    [CommandMethod("M5BRIDGE_RUN", CommandFlags.Session)]
    public static void Run()
    {
        var doc = Application.DocumentManager.MdiActiveDocument;
        var editor = doc.Editor;

        var taskPath = PromptRequiredString(editor, "\nM5 task json path: ");
        var resultPath = PromptRequiredString(editor, "\nM5 result json path: ");
        var tracePath = PromptRequiredString(editor, "\nM5 trace log path: ");

        var trace = new BridgeTraceLogger(tracePath);
        BridgeTask task;
        BridgeResultEnvelope result;
        try
        {
            task = BridgeTask.Load(taskPath);
            result = new BridgeResultEnvelope(task.JobId, task.SourceDxf);
            ApplyRuntimeSystemVariables(trace);
            trace.Log($"[DOTNET] stage={task.WorkflowStage} source={task.SourceDxf}");

            if (task.WorkflowStage.Equals("split_only", StringComparison.OrdinalIgnoreCase))
            {
                var selectionEngine = new SelectionEngine(task, trace);
                selectionEngine.Execute(doc.Database, result);
            }
            else if (task.WorkflowStage.Equals("audit_check_scan", StringComparison.OrdinalIgnoreCase))
            {
                var auditScanner = new AuditCheckScanner(task, trace);
                auditScanner.Execute(result);
            }
            else if (
                task.WorkflowStage.Equals("font_preflight", StringComparison.OrdinalIgnoreCase)
                || task.WorkflowStage.Equals("font_replace_missing", StringComparison.OrdinalIgnoreCase)
            )
            {
                var fontProcessor = new FontPreflightProcessor(task, trace);
                fontProcessor.Execute(result);
            }
            else if (task.WorkflowStage.Equals("titleblock_consistency_fix", StringComparison.OrdinalIgnoreCase))
            {
                var fixer = new TitleblockConsistencyFixer(task, trace);
                fixer.Execute(result);
            }
            else if (task.WorkflowStage.Equals("factory_index_map_replace", StringComparison.OrdinalIgnoreCase))
            {
                var replacer = new FactoryIndexMapReplacer(task, trace);
                replacer.Execute(result);
            }
            else if (
                task.WorkflowStage.Equals("plot_window_only", StringComparison.OrdinalIgnoreCase)
                || task.WorkflowStage.Equals("plot_from_split_dwg", StringComparison.OrdinalIgnoreCase)
            )
            {
                var plotEngine = new PlotEngine(task, trace);
                plotEngine.Execute(doc.Database, result);
            }
            else
            {
                var err = $"UNSUPPORTED_WORKFLOW_STAGE:{task.WorkflowStage}";
                result.Errors.Add(err);
                trace.Log($"[DOTNET][ERROR] {err}");
            }
        }
        catch (System.Exception ex)
        {
            result = new BridgeResultEnvelope("unknown", string.Empty);
            result.Errors.Add($"DOTNET_BRIDGE_EXCEPTION:{ex.Message}");
            trace.Log($"[DOTNET][EXCEPTION] {ex}");
        }

        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(resultPath) ?? ".");
            File.WriteAllText(resultPath, result.ToJson(), Encoding.UTF8);
            trace.Log($"[DOTNET] result written: {resultPath}");
        }
        catch (System.Exception ex)
        {
            trace.Log($"[DOTNET][ERROR] write result failed: {ex}");
            throw;
        }
    }

    private static string PromptRequiredString(Editor editor, string prompt)
    {
        var options = new PromptStringOptions(prompt) { AllowSpaces = true };
        var result = editor.GetString(options);
        if (result.Status != PromptStatus.OK || string.IsNullOrWhiteSpace(result.StringResult))
        {
            throw new InvalidOperationException($"invalid command argument: {prompt}");
        }

        return result.StringResult.Trim();
    }

    private static void ApplyRuntimeSystemVariables(BridgeTraceLogger trace)
    {
        TrySetSystemVar("FILEDIA", 0, trace);
        TrySetSystemVar("CMDDIA", 0, trace);
        TrySetSystemVar("BACKGROUNDPLOT", 0, trace);
        TrySetSystemVar("TILEMODE", 1, trace);
        TrySetSystemVar("REPORTERROR", 0, trace);
    }

    private static void TrySetSystemVar(string name, object value, BridgeTraceLogger trace)
    {
        try
        {
            Application.SetSystemVariable(name, value);
        }
        catch (System.Exception ex)
        {
            trace.Log($"[DOTNET][WARN] setvar {name} failed: {ex.Message}");
        }
    }
}

internal sealed class BridgeTraceLogger
{
    private readonly string _tracePath;

    public BridgeTraceLogger(string tracePath)
    {
        _tracePath = tracePath;
        var dir = Path.GetDirectoryName(_tracePath);
        if (!string.IsNullOrWhiteSpace(dir))
        {
            Directory.CreateDirectory(dir);
        }
    }

    public void Log(string message)
    {
        var line = $"{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff} {message}{Environment.NewLine}";
        File.AppendAllText(_tracePath, line, Encoding.UTF8);
    }
}

internal sealed class BridgeTask
{
    public string WorkflowStage { get; private set; } = "split_only";
    public string JobId { get; private set; } = "unknown";
    public string SourceDxf { get; private set; } = string.Empty;
    public string SourceDwgVersion { get; private set; } = string.Empty;
    public string OutputDir { get; private set; } = string.Empty;
    public string OutputDwg { get; private set; } = string.Empty;

    public BridgePlotConfig Plot { get; private set; } = new();
    public BridgeSelectionConfig Selection { get; private set; } = new();
    public BridgeOutputConfig Output { get; private set; } = new();
    public List<BridgeFrameTask> Frames { get; private set; } = new();
    public List<BridgeSheetSetTask> SheetSets { get; private set; } = new();
    public List<BridgeConsistencyAction> ConsistencyActions { get; private set; } = new();
    public BridgeFactoryIndexMapConfig FactoryIndexMap { get; private set; } = new();
    public List<BridgeReplacementTarget> ReplacementTargets { get; private set; } = new();
    public string ReplacementFont { get; private set; } = string.Empty;
    public Dictionary<string, string> ReplacementFonts { get; private set; } =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, string> FontCompatibilityReplacements { get; private set; } =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

    public static BridgeTask Load(string taskPath)
    {
        var serializer = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
        var raw = File.ReadAllText(taskPath, Encoding.UTF8);
        var root = serializer.DeserializeObject(raw) as Dictionary<string, object>;
        if (root == null)
        {
            throw new InvalidOperationException("task json parse failed");
        }

        var task = new BridgeTask
        {
            WorkflowStage = BridgeValue.GetString(root, "workflow_stage", "split_only"),
            JobId = BridgeValue.GetString(root, "job_id", "unknown"),
            SourceDxf = BridgeValue.GetString(root, "source_dxf", string.Empty),
            SourceDwgVersion = BridgeValue.GetString(root, "source_dwg_version", string.Empty),
            OutputDir = BridgeValue.GetString(root, "output_dir", string.Empty),
            OutputDwg = BridgeValue.GetString(root, "output_dwg", string.Empty),
            ReplacementFont = BridgeValue.GetString(root, "replacement_font", string.Empty),
            ReplacementFonts = BridgeValue.GetStringMap(
                root.TryGetValue("replacement_fonts", out var replacementFontsObj) ? replacementFontsObj : null
            ),
            FontCompatibilityReplacements = BridgeValue.GetStringMap(
                root.TryGetValue("font_compatibility_replacements", out var compatibilityObj) ? compatibilityObj : null
            ),
            Plot = BridgePlotConfig.FromObject(root.TryGetValue("plot", out var plotObj) ? plotObj : null),
            Selection = BridgeSelectionConfig.FromObject(root.TryGetValue("selection", out var selectionObj) ? selectionObj : null),
            Output = BridgeOutputConfig.FromObject(root.TryGetValue("output", out var outputObj) ? outputObj : null),
            FactoryIndexMap = BridgeFactoryIndexMapConfig.FromObject(
                root.TryGetValue("factory_index_map", out var factoryIndexMapObj) ? factoryIndexMapObj : null
            ),
        };

        foreach (var item in BridgeValue.AsObjectEnumerable(root.TryGetValue("frames", out var framesObj) ? framesObj : null))
        {
            var frameDict = BridgeValue.AsDictionary(item);
            if (frameDict != null)
            {
                task.Frames.Add(BridgeFrameTask.FromDictionary(frameDict));
            }
        }

        foreach (var item in BridgeValue.AsObjectEnumerable(root.TryGetValue("sheet_sets", out var sheetSetsObj) ? sheetSetsObj : null))
        {
            var sheetDict = BridgeValue.AsDictionary(item);
            if (sheetDict != null)
            {
                task.SheetSets.Add(BridgeSheetSetTask.FromDictionary(sheetDict));
            }
        }

        foreach (var item in BridgeValue.AsObjectEnumerable(root.TryGetValue("consistency_actions", out var actionsObj) ? actionsObj : null))
        {
            var actionDict = BridgeValue.AsDictionary(item);
            if (actionDict != null)
            {
                task.ConsistencyActions.Add(BridgeConsistencyAction.FromDictionary(actionDict));
            }
        }

        foreach (var item in BridgeValue.AsObjectEnumerable(root.TryGetValue("replacement_targets", out var targetsObj) ? targetsObj : null))
        {
            var targetDict = BridgeValue.AsDictionary(item);
            if (targetDict != null)
            {
                task.ReplacementTargets.Add(BridgeReplacementTarget.FromDictionary(targetDict));
            }
        }

        return task;
    }
}

internal sealed class BridgeResultEnvelope
{
    public BridgeResultEnvelope(string jobId, string sourceDxf)
    {
        JobId = jobId;
        SourceDxf = sourceDxf;
    }

    public string JobId { get; }
    public string SourceDxf { get; }
    public List<Dictionary<string, object>> Frames { get; } = new();
    public List<Dictionary<string, object>> SheetSets { get; } = new();
    public List<Dictionary<string, object>> Texts { get; } = new();
    public List<string> Errors { get; } = new();
    public Dictionary<string, object> AdditionalData { get; } = new();

    public string ToJson()
    {
        var root = new Dictionary<string, object>
        {
            ["schema_version"] = "cad-dxf-result@1.0",
            ["job_id"] = JobId,
            ["source_dxf"] = SourceDxf,
            ["frames"] = Frames,
            ["sheet_sets"] = SheetSets,
            ["texts"] = Texts,
            ["errors"] = Errors,
        };
        foreach (var item in AdditionalData)
        {
            root[item.Key] = item.Value;
        }
        var serializer = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
        return serializer.Serialize(root);
    }
}

internal sealed class BridgeFrameTask
{
    public string FrameId { get; private set; } = string.Empty;
    public string Name { get; private set; } = string.Empty;
    public BridgeBBox BBox { get; private set; } = BridgeBBox.Empty;
    public bool HasPlotWindowBBox { get; private set; }
    public BridgeBBox PlotWindowBBox { get; private set; } = BridgeBBox.Empty;
    public List<BridgePoint> Vertices { get; private set; } = new();
    public string PaperVariantId { get; private set; } = string.Empty;
    public string PaperMediaName { get; private set; } = string.Empty;
    public double PaperWidthMm { get; private set; }
    public double PaperHeightMm { get; private set; }
    public double Sx { get; private set; }
    public double Sy { get; private set; }

    public static BridgeFrameTask FromDictionary(Dictionary<string, object> data)
    {
        var task = new BridgeFrameTask
        {
            FrameId = BridgeValue.GetString(data, "frame_id", string.Empty),
            Name = BridgeValue.GetString(data, "name", string.Empty),
            BBox = BridgeBBox.FromObject(data.TryGetValue("bbox", out var bboxObj) ? bboxObj : null),
            PlotWindowBBox = BridgeBBox.FromObject(
                data.TryGetValue("plot_window_bbox", out var plotWindowObj) ? plotWindowObj : null
            ),
            HasPlotWindowBBox = data.TryGetValue("plot_window_bbox", out var _),
            Vertices = BridgePoint.FromObjectList(data.TryGetValue("vertices", out var verticesObj) ? verticesObj : null),
            PaperVariantId = BridgeValue.GetString(data, "paper_variant_id", string.Empty),
            PaperMediaName = BridgeValue.GetString(data, "paper_media_name", string.Empty),
            Sx = BridgeValue.GetDouble(data, "sx", 0.0),
            Sy = BridgeValue.GetDouble(data, "sy", 0.0),
        };

        var paper = BridgeValue.AsObjectList(data.TryGetValue("paper_size_mm", out var paperObj) ? paperObj : null);
        task.PaperWidthMm = paper.Count > 0 ? BridgeValue.ToDouble(paper[0], 0.0) : 0.0;
        task.PaperHeightMm = paper.Count > 1 ? BridgeValue.ToDouble(paper[1], 0.0) : 0.0;
        return task;
    }
}

internal sealed class BridgeSheetSetTask
{
    public string ClusterId { get; private set; } = string.Empty;
    public string Name { get; private set; } = string.Empty;
    public List<BridgePageTask> Pages { get; private set; } = new();

    public static BridgeSheetSetTask FromDictionary(Dictionary<string, object> data)
    {
        var task = new BridgeSheetSetTask
        {
            ClusterId = BridgeValue.GetString(data, "cluster_id", string.Empty),
            Name = BridgeValue.GetString(data, "name", string.Empty),
        };

        foreach (var item in BridgeValue.AsObjectEnumerable(data.TryGetValue("pages", out var pagesObj) ? pagesObj : null))
        {
            var pageDict = BridgeValue.AsDictionary(item);
            if (pageDict != null)
            {
                task.Pages.Add(BridgePageTask.FromDictionary(pageDict));
            }
        }

        return task;
    }
}

internal sealed class BridgeConsistencyAction
{
    public string FrameId { get; private set; } = string.Empty;
    public string FieldName { get; private set; } = string.Empty;
    public string ExpectedText { get; private set; } = string.Empty;
    public string CurrentText { get; private set; } = string.Empty;
    public BridgeBBox RoiBBox { get; private set; } = BridgeBBox.Empty;
    public List<BridgeConsistencyTarget> Targets { get; private set; } = new();

    public static BridgeConsistencyAction FromDictionary(Dictionary<string, object> data)
    {
        var action = new BridgeConsistencyAction
        {
            FrameId = BridgeValue.GetString(data, "frame_id", string.Empty),
            FieldName = BridgeValue.GetString(data, "field_name", string.Empty),
            ExpectedText = BridgeValue.GetString(data, "expected_text", string.Empty),
            CurrentText = BridgeValue.GetString(data, "current_text", string.Empty),
            RoiBBox = BridgeBBox.FromObject(data.TryGetValue("roi_bbox", out var roiObj) ? roiObj : null),
        };

        foreach (var item in BridgeValue.AsObjectEnumerable(data.TryGetValue("targets", out var targetsObj) ? targetsObj : null))
        {
            var targetDict = BridgeValue.AsDictionary(item);
            if (targetDict != null)
            {
                action.Targets.Add(BridgeConsistencyTarget.FromDictionary(targetDict));
            }
        }

        return action;
    }
}

internal sealed class BridgeConsistencyTarget
{
    public string OldText { get; private set; } = string.Empty;
    public string NewText { get; private set; } = string.Empty;
    public double X { get; private set; }
    public double Y { get; private set; }

    public static BridgeConsistencyTarget FromDictionary(Dictionary<string, object> data)
    {
        return new BridgeConsistencyTarget
        {
            OldText = BridgeValue.GetString(data, "old_text", string.Empty),
            NewText = BridgeValue.GetString(data, "new_text", string.Empty),
            X = BridgeValue.GetDouble(data, "x", 0.0),
            Y = BridgeValue.GetDouble(data, "y", 0.0),
        };
    }
}

internal sealed class BridgeReplacementTarget
{
    public string StyleName { get; private set; } = string.Empty;
    public string FontName { get; private set; } = string.Empty;
    public string BigFontName { get; private set; } = string.Empty;
    public string Kind { get; private set; } = string.Empty;
    public bool UsedInBlock { get; private set; }

    public static BridgeReplacementTarget FromDictionary(Dictionary<string, object> data)
    {
        return new BridgeReplacementTarget
        {
            StyleName = BridgeValue.GetString(data, "style_name", string.Empty),
            FontName = BridgeValue.GetString(data, "font_name", string.Empty),
            BigFontName = BridgeValue.GetString(data, "bigfont_name", string.Empty),
            Kind = BridgeValue.GetString(data, "kind", string.Empty),
            UsedInBlock = BridgeValue.GetBool(data, "used_in_block", false),
        };
    }
}

internal sealed class BridgePageTask
{
    public int PageIndex { get; private set; }
    public BridgeBBox BBox { get; private set; } = BridgeBBox.Empty;
    public List<BridgePoint> Vertices { get; private set; } = new();
    public string PaperVariantId { get; private set; } = string.Empty;
    public string PaperMediaName { get; private set; } = string.Empty;
    public double PaperWidthMm { get; private set; }
    public double PaperHeightMm { get; private set; }
    public double Sx { get; private set; }
    public double Sy { get; private set; }

    public static BridgePageTask FromDictionary(Dictionary<string, object> data)
    {
        var task = new BridgePageTask
        {
            PageIndex = BridgeValue.GetInt(data, "page_index", 0),
            BBox = BridgeBBox.FromObject(data.TryGetValue("bbox", out var bboxObj) ? bboxObj : null),
            Vertices = BridgePoint.FromObjectList(data.TryGetValue("vertices", out var verticesObj) ? verticesObj : null),
            PaperVariantId = BridgeValue.GetString(data, "paper_variant_id", string.Empty),
            PaperMediaName = BridgeValue.GetString(data, "paper_media_name", string.Empty),
            Sx = BridgeValue.GetDouble(data, "sx", 0.0),
            Sy = BridgeValue.GetDouble(data, "sy", 0.0),
        };
        var paper = BridgeValue.AsObjectList(data.TryGetValue("paper_size_mm", out var paperObj) ? paperObj : null);
        task.PaperWidthMm = paper.Count > 0 ? BridgeValue.ToDouble(paper[0], 0.0) : 0.0;
        task.PaperHeightMm = paper.Count > 1 ? BridgeValue.ToDouble(paper[1], 0.0) : 0.0;
        return task;
    }
}

internal sealed class BridgePlotConfig
{
    public string Pc3Name { get; private set; } = "打印PDF2.pc3";
    public string Pc3ResolvedPath { get; private set; } = string.Empty;
    public List<string> Pc3SearchDirs { get; private set; } = new();
    public string CtbName { get; private set; } = "fanban_monochrome.ctb";
    public bool CenterPlot { get; private set; } = false;
    public double PlotOffsetXmm { get; private set; } = 0.0;
    public double PlotOffsetYmm { get; private set; } = 0.0;
    public double PlotWindowBottomLeftExpandRatio { get; private set; } = 0.0001;
    public double PlotWindowTopRightExpandRatio { get; private set; } = 0.0002;
    public string ScaleMode { get; private set; } = "manual_integer_from_geometry";
    public string ScaleIntegerRounding { get; private set; } = "round";
    public double MarginTopMm { get; private set; } = 0.0;
    public double MarginBottomMm { get; private set; } = 0.0;
    public double MarginLeftMm { get; private set; } = 0.0;
    public double MarginRightMm { get; private set; } = 0.0;

    public static BridgePlotConfig FromObject(object? obj)
    {
        var data = BridgeValue.AsDictionary(obj);
        if (data == null)
        {
            return new BridgePlotConfig();
        }

        var margins = BridgeValue.AsDictionary(data.TryGetValue("margins_mm", out var marginsObj) ? marginsObj : null);
        var offsets = BridgeValue.AsDictionary(data.TryGetValue("plot_offset_mm", out var offsetObj) ? offsetObj : null);
        return new BridgePlotConfig
        {
            Pc3Name = BridgeValue.GetString(data, "pc3_name", "打印PDF2.pc3"),
            Pc3ResolvedPath = BridgeValue.GetString(data, "pc3_resolved_path", string.Empty),
            Pc3SearchDirs = BridgeValue.AsObjectEnumerable(
                    data.TryGetValue("pc3_search_dirs", out var pc3DirsObj) ? pc3DirsObj : null
                )
                .Select(item => item?.ToString() ?? string.Empty)
                .Where(item => !string.IsNullOrWhiteSpace(item))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList(),
            CtbName = BridgeValue.GetString(data, "ctb_name", "fanban_monochrome.ctb"),
            CenterPlot = BridgeValue.GetBool(data, "center_plot", false),
            PlotOffsetXmm = BridgeValue.GetDouble(offsets, "x", 0.0),
            PlotOffsetYmm = BridgeValue.GetDouble(offsets, "y", 0.0),
            PlotWindowBottomLeftExpandRatio = Math.Max(
                0.0,
                BridgeValue.GetDouble(data, "plot_window_bottom_left_expand_ratio", 0.0001)
            ),
            PlotWindowTopRightExpandRatio = Math.Max(
                0.0,
                BridgeValue.GetDouble(data, "plot_window_top_right_expand_ratio", 0.0002)
            ),
            ScaleMode = BridgeValue.GetString(data, "scale_mode", "manual_integer_from_geometry"),
            ScaleIntegerRounding = BridgeValue.GetString(data, "scale_integer_rounding", "round"),
            MarginTopMm = BridgeValue.GetDouble(margins, "top", 0.0),
            MarginBottomMm = BridgeValue.GetDouble(margins, "bottom", 0.0),
            MarginLeftMm = BridgeValue.GetDouble(margins, "left", 0.0),
            MarginRightMm = BridgeValue.GetDouble(margins, "right", 0.0),
        };
    }
}

internal sealed class BridgeSelectionConfig
{
    public double BBoxMarginPercent { get; private set; } = 0.015;
    public double EmptySelectionRetryMarginPercent { get; private set; } = 0.03;
    public double HardRetryMarginPercent { get; private set; } = 0.25;
    public string DbUnknownBboxPolicy { get; private set; } = "keep_if_uncertain";

    public static BridgeSelectionConfig FromObject(object? obj)
    {
        var data = BridgeValue.AsDictionary(obj);
        if (data == null)
        {
            return new BridgeSelectionConfig();
        }

        return new BridgeSelectionConfig
        {
            BBoxMarginPercent = BridgeValue.GetDouble(data, "bbox_margin_percent", 0.015),
            EmptySelectionRetryMarginPercent = BridgeValue.GetDouble(data, "empty_selection_retry_margin_percent", 0.03),
            HardRetryMarginPercent = BridgeValue.GetDouble(data, "hard_retry_margin_percent", 0.25),
            DbUnknownBboxPolicy = BridgeValue.GetString(data, "db_unknown_bbox_policy", "keep_if_uncertain"),
        };
    }
}

internal sealed class BridgeOutputConfig
{
    public string PlotPreferredArea { get; private set; } = "extents";
    public string PlotFallbackArea { get; private set; } = "window";

    public static BridgeOutputConfig FromObject(object? obj)
    {
        var data = BridgeValue.AsDictionary(obj);
        if (data == null)
        {
            return new BridgeOutputConfig();
        }

        return new BridgeOutputConfig
        {
            PlotPreferredArea = BridgeValue.GetString(data, "plot_preferred_area", "extents"),
            PlotFallbackArea = BridgeValue.GetString(data, "plot_fallback_area", "window"),
        };
    }
}

internal sealed class BridgeBBox
{
    public static BridgeBBox Empty => new(0, 0, 0, 0);

    public BridgeBBox(double xmin, double ymin, double xmax, double ymax)
    {
        Xmin = xmin;
        Ymin = ymin;
        Xmax = xmax;
        Ymax = ymax;
    }

    public double Xmin { get; }
    public double Ymin { get; }
    public double Xmax { get; }
    public double Ymax { get; }
    public double Width => Xmax - Xmin;
    public double Height => Ymax - Ymin;
    public BridgePoint Center => new((Xmin + Xmax) / 2.0, (Ymin + Ymax) / 2.0);

    public BridgeBBox Expand(double ratio)
    {
        var dx = Width * ratio;
        var dy = Height * ratio;
        return new BridgeBBox(Xmin - dx, Ymin - dy, Xmax + dx, Ymax + dy);
    }

    public BridgeBBox ExpandTopRight(double ratio)
    {
        if (ratio <= 0.0)
        {
            return this;
        }

        var dx = Width * ratio;
        var dy = Height * ratio;
        return new BridgeBBox(Xmin, Ymin, Xmax + dx, Ymax + dy);
    }

    public BridgeBBox ExpandBottomLeftTopRight(double bottomLeftRatio, double topRightRatio)
    {
        if (bottomLeftRatio <= 0.0 && topRightRatio <= 0.0)
        {
            return this;
        }

        var leftDx = Width * Math.Max(0.0, bottomLeftRatio);
        var bottomDy = Height * Math.Max(0.0, bottomLeftRatio);
        var rightDx = Width * Math.Max(0.0, topRightRatio);
        var topDy = Height * Math.Max(0.0, topRightRatio);
        return new BridgeBBox(Xmin - leftDx, Ymin - bottomDy, Xmax + rightDx, Ymax + topDy);
    }

    public BridgeBBox ExpandMm(double left, double bottom, double right, double top)
    {
        return new BridgeBBox(
            Xmin - Math.Max(0.0, left),
            Ymin - Math.Max(0.0, bottom),
            Xmax + Math.Max(0.0, right),
            Ymax + Math.Max(0.0, top)
        );
    }

    public Dictionary<string, object> ToDictionary()
    {
        return new Dictionary<string, object>
        {
            ["xmin"] = Xmin,
            ["ymin"] = Ymin,
            ["xmax"] = Xmax,
            ["ymax"] = Ymax,
        };
    }

    public static BridgeBBox FromObject(object? obj)
    {
        var data = BridgeValue.AsDictionary(obj);
        if (data == null)
        {
            return Empty;
        }

        return new BridgeBBox(
            BridgeValue.GetDouble(data, "xmin", 0.0),
            BridgeValue.GetDouble(data, "ymin", 0.0),
            BridgeValue.GetDouble(data, "xmax", 0.0),
            BridgeValue.GetDouble(data, "ymax", 0.0)
        );
    }
}

internal sealed class BridgePoint
{
    public BridgePoint(double x, double y)
    {
        X = x;
        Y = y;
    }

    public double X { get; }
    public double Y { get; }

    public static List<BridgePoint> FromObjectList(object? obj)
    {
        var result = new List<BridgePoint>();
        foreach (var item in BridgeValue.AsObjectEnumerable(obj))
        {
            var dict = BridgeValue.AsDictionary(item);
            if (dict != null)
            {
                result.Add(
                    new BridgePoint(
                        BridgeValue.GetDouble(dict, "x", 0.0),
                        BridgeValue.GetDouble(dict, "y", 0.0)
                    )
                );
                continue;
            }

            var values = BridgeValue.AsObjectList(item);
            if (values.Count >= 2)
            {
                result.Add(new BridgePoint(
                    BridgeValue.ToDouble(values[0], 0.0),
                    BridgeValue.ToDouble(values[1], 0.0)
                ));
            }
        }

        return result;
    }
}

internal static class BridgeValue
{
    public static Dictionary<string, object>? AsDictionary(object? value)
    {
        return value as Dictionary<string, object>;
    }

    public static IEnumerable<object> AsObjectEnumerable(object? value)
    {
        if (value == null || value is string)
        {
            yield break;
        }

        if (value is object[] array)
        {
            foreach (var item in array)
            {
                if (item != null)
                {
                    yield return item;
                }
            }

            yield break;
        }

        if (value is ArrayList list)
        {
            foreach (var item in list)
            {
                if (item != null)
                {
                    yield return item;
                }
            }

            yield break;
        }

        if (value is IEnumerable enumerable)
        {
            foreach (var item in enumerable)
            {
                if (item != null)
                {
                    yield return item;
                }
            }
        }
    }

    public static List<object> AsObjectList(object? value)
    {
        return AsObjectEnumerable(value).ToList();
    }

    public static string GetString(Dictionary<string, object>? dict, string key, string defaultValue)
    {
        if (dict == null || !dict.TryGetValue(key, out var value) || value == null)
        {
            return defaultValue;
        }

        return Convert.ToString(value, CultureInfo.InvariantCulture) ?? defaultValue;
    }

    public static Dictionary<string, string> GetStringMap(object? value)
    {
        var dict = AsDictionary(value);
        if (dict == null)
        {
            return new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        }

        var results = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var pair in dict)
        {
            var key = (pair.Key ?? string.Empty).Trim();
            var text = Convert.ToString(pair.Value, CultureInfo.InvariantCulture)?.Trim() ?? string.Empty;
            if (string.IsNullOrWhiteSpace(key) || string.IsNullOrWhiteSpace(text))
            {
                continue;
            }

            results[key] = text;
        }

        return results;
    }

    public static double GetDouble(Dictionary<string, object>? dict, string key, double defaultValue)
    {
        if (dict == null || !dict.TryGetValue(key, out var value) || value == null)
        {
            return defaultValue;
        }

        return ToDouble(value, defaultValue);
    }

    public static int GetInt(Dictionary<string, object>? dict, string key, int defaultValue)
    {
        if (dict == null || !dict.TryGetValue(key, out var value) || value == null)
        {
            return defaultValue;
        }

        return (int)Math.Round(ToDouble(value, defaultValue), MidpointRounding.AwayFromZero);
    }

    public static bool GetBool(Dictionary<string, object>? dict, string key, bool defaultValue)
    {
        if (dict == null || !dict.TryGetValue(key, out var value) || value == null)
        {
            return defaultValue;
        }

        if (value is bool b)
        {
            return b;
        }

        if (value is string s && bool.TryParse(s, out var parsed))
        {
            return parsed;
        }

        return defaultValue;
    }

    public static double ToDouble(object value, double defaultValue)
    {
        try
        {
            return Convert.ToDouble(value, CultureInfo.InvariantCulture);
        }
        catch
        {
            return defaultValue;
        }
    }
}
