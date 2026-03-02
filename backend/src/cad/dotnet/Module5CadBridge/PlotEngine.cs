using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.PlottingServices;
using AcadPlotEngine = Autodesk.AutoCAD.PlottingServices.PlotEngine;

namespace Module5CadBridge;

internal sealed class PlotEngine
{
    private readonly BridgeTask _task;
    private readonly BridgeTraceLogger _trace;

    public PlotEngine(BridgeTask task, BridgeTraceLogger trace)
    {
        _task = task;
        _trace = trace;
    }

    public void Execute(Database db, BridgeResultEnvelope result)
    {
        foreach (var frame in _task.Frames)
        {
            result.Frames.Add(PlotFrame(db, frame));
        }
    }

    private Dictionary<string, object> PlotFrame(Database db, BridgeFrameTask frame)
    {
        var pdfPath = Path.Combine(_task.OutputDir, $"{frame.Name}.pdf");
        var flags = new List<string>();
        var areaMode = ResolveAreaMode();
        var status = "failed";
        var usedFlag = areaMode == "extents" ? "PLOT_EXTENTS_USED" : "PLOT_WINDOW_USED";

        if (TryPlot(db, frame, pdfPath, areaMode, out var error))
        {
            status = "ok";
            flags.Add(usedFlag);
            _trace.Log($"[DOTNET][PLOT] frame={frame.FrameId} mode={areaMode} pdf={pdfPath}");
        }
        else
        {
            flags.Add(areaMode == "window" ? "PLOT_WINDOW_FAILED" : "PLOT_FAILED");
            if (!string.IsNullOrWhiteSpace(error))
            {
                flags.Add($"PLOT_ERROR:{SanitizeFlagText(error)}");
            }
        }

        return new Dictionary<string, object>
        {
            ["frame_id"] = frame.FrameId,
            ["status"] = status,
            ["pdf_path"] = pdfPath,
            ["dwg_path"] = _task.SourceDxf,
            ["selection_count"] = 1,
            ["flags"] = flags,
        };
    }

    private string ResolveAreaMode()
    {
        if (_task.WorkflowStage.Equals("plot_window_only", StringComparison.OrdinalIgnoreCase))
        {
            return "window";
        }

        return _task.Output.PlotPreferredArea.Equals("window", StringComparison.OrdinalIgnoreCase)
            ? "window"
            : "extents";
    }

    private bool TryPlot(
        Database db,
        BridgeFrameTask frame,
        string pdfPath,
        string areaMode,
        out string error
    )
    {
        error = string.Empty;
        Directory.CreateDirectory(Path.GetDirectoryName(pdfPath) ?? ".");
        foreach (var mediaName in ResolveMediaCandidates(frame.PaperWidthMm, frame.PaperHeightMm))
        {
            if (TryPlotOnce(db, frame, pdfPath, mediaName, areaMode, out error))
            {
                return true;
            }
        }

        return false;
    }

    private bool TryPlotOnce(
        Database db,
        BridgeFrameTask frame,
        string pdfPath,
        string mediaName,
        string areaMode,
        out string error
    )
    {
        error = string.Empty;
        var doc = Application.DocumentManager.MdiActiveDocument;
        var editor = doc.Editor;
        var useWindow = areaMode.Equals("window", StringComparison.OrdinalIgnoreCase);

        try
        {
            using var tr = db.TransactionManager.StartTransaction();
            var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
            var model = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
            var layout = (Layout)tr.GetObject(model.LayoutId, OpenMode.ForRead);
            var settings = new PlotSettings(layout.ModelType);
            settings.CopyFrom(layout);

            var validator = PlotSettingsValidator.Current;
            validator.SetPlotConfigurationName(settings, _task.Plot.Pc3Name, mediaName);
            validator.RefreshLists(settings);
            validator.SetPlotPaperUnits(settings, PlotPaperUnit.Millimeters);
            validator.SetUseStandardScale(settings, true);
            validator.SetStdScaleType(settings, StdScaleType.ScaleToFit);
            validator.SetPlotCentered(settings, true);
            validator.SetPlotType(
                settings,
                useWindow
                    ? Autodesk.AutoCAD.DatabaseServices.PlotType.Window
                    : Autodesk.AutoCAD.DatabaseServices.PlotType.Extents
            );
            validator.SetPlotRotation(
                settings,
                frame.PaperWidthMm >= frame.PaperHeightMm
                    ? PlotRotation.Degrees000
                    : PlotRotation.Degrees090
            );
            if (!string.IsNullOrWhiteSpace(_task.Plot.CtbName))
            {
                validator.SetCurrentStyleSheet(settings, _task.Plot.CtbName);
            }

            if (useWindow)
            {
                var expanded = BuildWindowBBox(frame);
                var windowDcs = ToDcsWindow(editor, expanded);
                validator.SetPlotWindowArea(settings, windowDcs);
            }

            var plotInfo = new PlotInfo
            {
                Layout = layout.ObjectId,
                OverrideSettings = settings,
            };
            var plotInfoValidator = new PlotInfoValidator
            {
                MediaMatchingPolicy = MatchingPolicy.MatchEnabled,
            };
            plotInfoValidator.Validate(plotInfo);
            tr.Commit();

            if (PlotFactory.ProcessPlotState != ProcessPlotState.NotPlotting)
            {
                error = "PLOT_ENGINE_BUSY";
                return false;
            }

            using AcadPlotEngine engine = PlotFactory.CreatePublishEngine();
            using var progress = new PlotProgressDialog(false, 1, true);
            progress.OnBeginPlot();
            progress.IsVisible = false;
            engine.BeginPlot(progress, null);
            engine.BeginDocument(plotInfo, doc.Name, null, 1, true, pdfPath);
            var pageInfo = new PlotPageInfo();
            engine.BeginPage(pageInfo, plotInfo, true, null);
            engine.BeginGenerateGraphics(null);
            engine.EndGenerateGraphics(null);
            engine.EndPage(null);
            engine.EndDocument(null);
            engine.EndPlot(null);
            progress.OnEndPlot();
            return File.Exists(pdfPath);
        }
        catch (System.Exception ex)
        {
            error = ex.Message;
            _trace.Log($"[DOTNET][PLOT][ERROR] frame={frame.FrameId} media={mediaName} err={ex}");
            return false;
        }
    }

    private BridgeBBox BuildWindowBBox(BridgeFrameTask frame)
    {
        var sx = frame.Sx > 1e-6
            ? frame.Sx
            : (frame.PaperWidthMm > 1e-6 ? frame.BBox.Width / frame.PaperWidthMm : 1.0);
        var sy = frame.Sy > 1e-6
            ? frame.Sy
            : (frame.PaperHeightMm > 1e-6 ? frame.BBox.Height / frame.PaperHeightMm : 1.0);
        return new BridgeBBox(
            frame.BBox.Xmin - _task.Plot.MarginLeftMm * sx,
            frame.BBox.Ymin - _task.Plot.MarginBottomMm * sy,
            frame.BBox.Xmax + _task.Plot.MarginRightMm * sx,
            frame.BBox.Ymax + _task.Plot.MarginTopMm * sy
        );
    }

    private static Extents2d ToDcsWindow(Editor editor, BridgeBBox bbox)
    {
        using var view = editor.GetCurrentView();
        var wcsToDcs = Matrix3d.PlaneToWorld(view.ViewDirection);
        wcsToDcs = Matrix3d.Displacement(view.Target - Point3d.Origin) * wcsToDcs;
        wcsToDcs = Matrix3d.Rotation(-view.ViewTwist, view.ViewDirection, view.Target) * wcsToDcs;
        wcsToDcs = wcsToDcs.Inverse();

        var p1 = new Point3d(bbox.Xmin, bbox.Ymin, 0).TransformBy(wcsToDcs);
        var p2 = new Point3d(bbox.Xmax, bbox.Ymax, 0).TransformBy(wcsToDcs);
        return new Extents2d(
            Math.Min(p1.X, p2.X),
            Math.Min(p1.Y, p2.Y),
            Math.Max(p1.X, p2.X),
            Math.Max(p1.Y, p2.Y)
        );
    }

    private static IEnumerable<string> ResolveMediaCandidates(double paperWidthMm, double paperHeightMm)
    {
        var candidates = new List<string>();
        AddCandidate(candidates, ResolveMediaName(paperWidthMm, paperHeightMm));
        AddCandidate(candidates, ResolveMediaName(paperHeightMm, paperWidthMm));
        if (IsA0(paperWidthMm, paperHeightMm))
        {
            AddCandidate(candidates, "ISO_expand_A0_(1219.00_x_871.00_MM)");
            AddCandidate(candidates, "ISO_expand_A0_(871.00_x_1219.00_MM)");
            AddCandidate(candidates, "ISO_expand_A0_(1189.00_x_841.00_MM)");
            AddCandidate(candidates, "ISO_expand_A0_(841.00_x_1189.00_MM)");
        }

        return candidates;
    }

    private static void AddCandidate(List<string> candidates, string mediaName)
    {
        if (!string.IsNullOrWhiteSpace(mediaName) && !candidates.Contains(mediaName))
        {
            candidates.Add(mediaName);
        }
    }

    private static bool IsA0(double paperWidthMm, double paperHeightMm)
    {
        return IsNearPair(paperWidthMm, paperHeightMm, 1189.0, 841.0)
               || IsNearPair(paperWidthMm, paperHeightMm, 841.0, 1189.0);
    }

    private static string ResolveMediaName(double paperWidthMm, double paperHeightMm)
    {
        if (IsNearPair(paperWidthMm, paperHeightMm, 1189.0, 841.0)) return "ISO_A0_(1189.00_x_841.00_MM)";
        if (IsNearPair(paperWidthMm, paperHeightMm, 841.0, 1189.0)) return "ISO_A0_(841.00_x_1189.00_MM)";
        if (IsNearPair(paperWidthMm, paperHeightMm, 841.0, 594.0)) return "ISO_A1_(841.00_x_594.00_MM)";
        if (IsNearPair(paperWidthMm, paperHeightMm, 594.0, 841.0)) return "ISO_A1_(594.00_x_841.00_MM)";
        if (IsNearPair(paperWidthMm, paperHeightMm, 594.0, 420.0)) return "ISO_A2_(594.00_x_420.00_MM)";
        if (IsNearPair(paperWidthMm, paperHeightMm, 420.0, 594.0)) return "ISO_A2_(420.00_x_594.00_MM)";
        if (IsNearPair(paperWidthMm, paperHeightMm, 420.0, 297.0)) return "ISO_A3_(420.00_x_297.00_MM)";
        if (IsNearPair(paperWidthMm, paperHeightMm, 297.0, 420.0)) return "ISO_A3_(297.00_x_420.00_MM)";
        if (IsNearPair(paperWidthMm, paperHeightMm, 297.0, 210.0)) return "ISO_A4_(297.00_x_210.00_MM)";
        if (IsNearPair(paperWidthMm, paperHeightMm, 210.0, 297.0)) return "ISO_A4_(210.00_x_297.00_MM)";
        return "ISO_A1_(841.00_x_594.00_MM)";
    }

    private static bool IsNearPair(double actualW, double actualH, double expectedW, double expectedH)
    {
        return Math.Abs(actualW - expectedW) <= 10.0 && Math.Abs(actualH - expectedH) <= 10.0;
    }

    private static string SanitizeFlagText(string value)
    {
        return value
            .Replace("\r", " ")
            .Replace("\n", " ")
            .Replace(":", "_")
            .Trim();
    }
}
