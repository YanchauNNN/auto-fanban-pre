using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.PlottingServices;
using AcadPlotEngine = Autodesk.AutoCAD.PlottingServices.PlotEngine;

namespace Module5CadBridge;

internal sealed class PlotEngine
{
    private const double MediaToleranceMm = 1.0;
    private readonly BridgeTask _task;
    private readonly BridgeTraceLogger _trace;
    private readonly Dictionary<string, List<string>> _strictMediaCandidatesCache = new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _missingMediaLogged = new(StringComparer.OrdinalIgnoreCase);
    private List<string>? _availableMediaNamesCache;

    public PlotEngine(BridgeTask task, BridgeTraceLogger trace)
    {
        _task = task;
        _trace = trace;
    }

    public void Execute(Database db, BridgeResultEnvelope result)
    {
        RunMediaPrecheck(db, result);

        foreach (var frame in _task.Frames)
        {
            result.Frames.Add(PlotFrame(db, frame));
        }

        foreach (var sheetSet in _task.SheetSets)
        {
            result.SheetSets.Add(PlotSheetSet(db, sheetSet));
        }
    }

    private Dictionary<string, object> PlotFrame(Database db, BridgeFrameTask frame)
    {
        var pdfPath = Path.Combine(_task.OutputDir, $"{frame.Name}.pdf");
        var flags = new List<string>();
        var status = "failed";
        var errors = new List<string>();
        var areaModes = ResolveAreaModes();
        var selectedMode = string.Empty;

        foreach (var mode in areaModes)
        {
            if (TryPlotFrame(db, frame, pdfPath, mode, out var error))
            {
                status = "ok";
                selectedMode = mode;
                break;
            }

            if (!string.IsNullOrWhiteSpace(error))
            {
                errors.Add(error);
            }
        }

        if (status == "ok")
        {
            flags.Add(selectedMode == "window" ? "PLOT_WINDOW_USED" : "PLOT_EXTENTS_USED");
            if (selectedMode != areaModes[0])
            {
                flags.Add("PLOT_AREA_FALLBACK_USED");
            }
            _trace.Log($"[DOTNET][PLOT] frame={frame.FrameId} mode={selectedMode} pdf={pdfPath}");
        }
        else
        {
            flags.Add(areaModes[0] == "window" ? "PLOT_WINDOW_FAILED" : "PLOT_FAILED");
            foreach (var error in errors)
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

    private Dictionary<string, object> PlotSheetSet(Database db, BridgeSheetSetTask sheetSet)
    {
        var pdfPath = Path.Combine(_task.OutputDir, $"{sheetSet.Name}.pdf");
        var flags = new List<string>();
        var status = "failed";
        var areaModes = ResolveAreaModes();
        var errors = new List<string>();
        var selectedMode = string.Empty;

        var pages = sheetSet.Pages.OrderBy(p => p.PageIndex).ToList();
        if (pages.Count <= 0)
        {
            flags.Add("A4_MULTI_NO_PAGES");
            return new Dictionary<string, object>
            {
                ["cluster_id"] = sheetSet.ClusterId,
                ["status"] = "failed",
                ["pdf_path"] = pdfPath,
                ["dwg_path"] = _task.SourceDxf,
                ["page_count"] = 0,
                ["flags"] = flags,
                ["page_pdf_paths"] = new List<string>(),
            };
        }

        foreach (var mode in areaModes)
        {
            if (TryPlotSheetSet(db, sheetSet, pdfPath, mode, out var error))
            {
                status = "ok";
                selectedMode = mode;
                break;
            }

            if (!string.IsNullOrWhiteSpace(error))
            {
                errors.Add(error);
            }
        }

        if (status == "ok")
        {
            flags.Add(selectedMode == "window" ? "PLOT_WINDOW_USED" : "PLOT_EXTENTS_USED");
            if (selectedMode != areaModes[0])
            {
                flags.Add("PLOT_AREA_FALLBACK_USED");
            }
            flags.Add("PLOT_MULTIPAGE_USED");
            _trace.Log(
                $"[DOTNET][PLOT][MULTI] cluster={sheetSet.ClusterId} pages={pages.Count} mode={selectedMode} pdf={pdfPath}"
            );
        }
        else
        {
            flags.Add(areaModes[0] == "window" ? "PLOT_WINDOW_FAILED" : "PLOT_FAILED");
            foreach (var error in errors)
            {
                flags.Add($"PLOT_ERROR:{SanitizeFlagText(error)}");
            }
        }

        return new Dictionary<string, object>
        {
            ["cluster_id"] = sheetSet.ClusterId,
            ["status"] = status,
            ["pdf_path"] = pdfPath,
            ["dwg_path"] = _task.SourceDxf,
            ["page_count"] = pages.Count,
            ["flags"] = flags,
            ["page_pdf_paths"] = new List<string>(),
        };
    }

    private List<string> ResolveAreaModes()
    {
        var modes = new List<string>();
        var preferred = ResolveAreaMode();
        modes.Add(preferred);
        var fallback = NormalizeAreaMode(_task.Output.PlotFallbackArea);
        if (!fallback.Equals("none", StringComparison.OrdinalIgnoreCase)
            && !fallback.Equals(preferred, StringComparison.OrdinalIgnoreCase))
        {
            modes.Add(fallback);
        }

        return modes;
    }

    private string ResolveAreaMode()
    {
        if (_task.WorkflowStage.Equals("plot_window_only", StringComparison.OrdinalIgnoreCase))
        {
            return "window";
        }

        return NormalizeAreaMode(_task.Output.PlotPreferredArea);
    }

    private static string NormalizeAreaMode(string raw)
    {
        if (raw.Equals("window", StringComparison.OrdinalIgnoreCase))
        {
            return "window";
        }

        if (raw.Equals("none", StringComparison.OrdinalIgnoreCase))
        {
            return "none";
        }

        return "extents";
    }

    private bool TryPlotFrame(
        Database db,
        BridgeFrameTask frame,
        string pdfPath,
        string areaMode,
        out string error
    )
    {
        error = string.Empty;
        Directory.CreateDirectory(Path.GetDirectoryName(pdfPath) ?? ".");
        var mediaCandidates = GetStrictMediaCandidates(
            db,
            frame.PaperVariantId,
            frame.PaperMediaName,
            frame.PaperWidthMm,
            frame.PaperHeightMm
        );
        if (mediaCandidates.Count <= 0)
        {
            error = $"MEDIA_NOT_MATCHED:{frame.PaperWidthMm:F3}x{frame.PaperHeightMm:F3}";
            _trace.Log($"[DOTNET][PLOT][WARN] frame={frame.FrameId} {error}");
            return false;
        }

        var lastError = string.Empty;
        foreach (var mediaName in mediaCandidates)
        {
            if (TryPlotOnce(
                    db,
                    frame.BBox,
                    frame.Vertices,
                    frame.Sx,
                    frame.Sy,
                    frame.PaperVariantId,
                    frame.PaperWidthMm,
                    frame.PaperHeightMm,
                    pdfPath,
                    mediaName,
                    areaMode,
                    out error))
            {
                _trace.Log(
                    $"[DOTNET][PLOT][CANDIDATE_OK] frame={frame.FrameId} media={mediaName} area={areaMode}"
                );
                return true;
            }

            lastError = error;
            _trace.Log(
                $"[DOTNET][PLOT][CANDIDATE_FAIL] frame={frame.FrameId} media={mediaName} area={areaMode} err={error}"
            );
        }

        error = string.IsNullOrWhiteSpace(lastError)
            ? $"MEDIA_NOT_MATCHED:{frame.PaperWidthMm:F3}x{frame.PaperHeightMm:F3}"
            : lastError;
        return false;
    }

    private bool TryPlotSheetSet(
        Database db,
        BridgeSheetSetTask sheetSet,
        string pdfPath,
        string areaMode,
        out string error
    )
    {
        error = string.Empty;
        Directory.CreateDirectory(Path.GetDirectoryName(pdfPath) ?? ".");
        var pages = sheetSet.Pages.OrderBy(p => p.PageIndex).ToList();
        if (pages.Count <= 0)
        {
            error = "A4_MULTI_NO_PAGES";
            return false;
        }

        var pageInfos = new List<PlotInfo>();
        foreach (var page in pages)
        {
            var mediaCandidates = GetStrictMediaCandidates(
                db,
                page.PaperVariantId,
                page.PaperMediaName,
                page.PaperWidthMm,
                page.PaperHeightMm
            );
            if (mediaCandidates.Count <= 0)
            {
                error = $"MEDIA_NOT_MATCHED_PAGE:{page.PageIndex}:{page.PaperWidthMm:F3}x{page.PaperHeightMm:F3}";
                return false;
            }

            PlotInfo? pageInfo = null;
            var pageError = string.Empty;
            foreach (var mediaName in mediaCandidates)
            {
                if (TryBuildPlotInfo(
                        db,
                        page.BBox,
                        page.Vertices,
                        page.Sx,
                        page.Sy,
                        page.PaperVariantId,
                        page.PaperWidthMm,
                        page.PaperHeightMm,
                        mediaName,
                        areaMode,
                        out pageInfo,
                        out pageError))
                {
                    _trace.Log(
                        $"[DOTNET][PLOT][PAGE_CANDIDATE_OK] cluster={sheetSet.ClusterId} page={page.PageIndex} media={mediaName} area={areaMode}"
                    );
                    break;
                }

                _trace.Log(
                    $"[DOTNET][PLOT][PAGE_CANDIDATE_FAIL] cluster={sheetSet.ClusterId} page={page.PageIndex} media={mediaName} area={areaMode} err={pageError}"
                );
            }

            if (pageInfo == null)
            {
                error = string.IsNullOrWhiteSpace(pageError)
                    ? $"MEDIA_NOT_MATCHED_PAGE:{page.PageIndex}:{page.PaperWidthMm:F3}x{page.PaperHeightMm:F3}"
                    : pageError;
                return false;
            }

            pageInfos.Add(pageInfo);
        }

        if (PlotFactory.ProcessPlotState != ProcessPlotState.NotPlotting)
        {
            error = "PLOT_ENGINE_BUSY";
            return false;
        }

        var doc = Application.DocumentManager.MdiActiveDocument;
        try
        {
            using AcadPlotEngine engine = PlotFactory.CreatePublishEngine();
            using var progress = new PlotProgressDialog(false, pageInfos.Count, true);
            progress.OnBeginPlot();
            progress.IsVisible = false;
            engine.BeginPlot(progress, null);

            engine.BeginDocument(pageInfos[0], doc.Name, null, 1, true, pdfPath);
            for (var i = 0; i < pageInfos.Count; i++)
            {
                var isLastPage = i == pageInfos.Count - 1;
                var pageInfo = new PlotPageInfo();
                engine.BeginPage(pageInfo, pageInfos[i], isLastPage, null);
                engine.BeginGenerateGraphics(null);
                engine.EndGenerateGraphics(null);
                engine.EndPage(null);
            }

            engine.EndDocument(null);
            engine.EndPlot(null);
            progress.OnEndPlot();
            return File.Exists(pdfPath);
        }
        catch (System.Exception ex)
        {
            error = ex.Message;
            _trace.Log($"[DOTNET][PLOT][MULTI][ERROR] cluster={sheetSet.ClusterId} err={ex}");
            return false;
        }
    }

    private bool TryPlotOnce(
        Database db,
        BridgeBBox bbox,
        List<BridgePoint> vertices,
        double sx,
        double sy,
        string paperVariantId,
        double paperWidthMm,
        double paperHeightMm,
        string pdfPath,
        string mediaName,
        string areaMode,
        out string error
    )
    {
        error = string.Empty;
        if (!TryBuildPlotInfo(
                db,
                bbox,
                vertices,
                sx,
                sy,
                paperVariantId,
                paperWidthMm,
                paperHeightMm,
                mediaName,
                areaMode,
                out var plotInfo,
                out error))
        {
            return false;
        }

        if (PlotFactory.ProcessPlotState != ProcessPlotState.NotPlotting)
        {
            error = "PLOT_ENGINE_BUSY";
            return false;
        }

        var doc = Application.DocumentManager.MdiActiveDocument;
        try
        {
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
            _trace.Log($"[DOTNET][PLOT][ERROR] media={mediaName} err={ex}");
            return false;
        }
    }

    private bool TryBuildPlotInfo(
        Database db,
        BridgeBBox bbox,
        List<BridgePoint> vertices,
        double sx,
        double sy,
        string paperVariantId,
        double paperWidthMm,
        double paperHeightMm,
        string mediaName,
        string areaMode,
        out PlotInfo? plotInfo,
        out string error
    )
    {
        plotInfo = null;
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
            ApplyScaleSettings(
                validator,
                settings,
                sx,
                sy,
                bbox,
                paperWidthMm,
                paperHeightMm
            );
            validator.SetPlotCentered(settings, _task.Plot.CenterPlot);
            TrySetPlotOffset(validator, settings, _task.Plot.PlotOffsetXmm, _task.Plot.PlotOffsetYmm);
            validator.SetPlotType(settings, Autodesk.AutoCAD.DatabaseServices.PlotType.Extents);
            var windowBBox = BuildWindowBBox(vertices, bbox);
            var paperLandscape = paperWidthMm > paperHeightMm;
            var useRotatedOrientation = false;
            if (TryExtractMediaSizeMm(mediaName, out var mediaWidthMm, out var mediaHeightMm))
            {
                var mediaLandscape = mediaWidthMm > mediaHeightMm;
                useRotatedOrientation = mediaLandscape != paperLandscape;
            }
            else
            {
                var bboxLandscape = windowBBox.Width > windowBBox.Height;
                useRotatedOrientation = bboxLandscape != paperLandscape;
            }
            validator.SetPlotRotation(
                settings,
                useRotatedOrientation
                    ? PlotRotation.Degrees090
                    : PlotRotation.Degrees000
            );
            if (!string.IsNullOrWhiteSpace(_task.Plot.CtbName))
            {
                validator.SetCurrentStyleSheet(settings, _task.Plot.CtbName);
            }

            if (useWindow)
            {
                var windowDcs = ToDcsWindow(editor, windowBBox);
                validator.SetPlotWindowArea(settings, windowDcs);
                validator.SetPlotType(settings, Autodesk.AutoCAD.DatabaseServices.PlotType.Window);
            }

            _trace.Log(
                $"[DOTNET][PLOT][BUILD] variant={paperVariantId} media={mediaName} area={areaMode} rotate={(useRotatedOrientation ? 90 : 0)} bbox={windowBBox.Width:F3}x{windowBBox.Height:F3} paper={paperWidthMm:F3}x{paperHeightMm:F3} center={_task.Plot.CenterPlot} offset={_task.Plot.PlotOffsetXmm:F3},{_task.Plot.PlotOffsetYmm:F3} scale_mode={_task.Plot.ScaleMode}"
            );

            plotInfo = new PlotInfo
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
            return true;
        }
        catch (System.Exception ex)
        {
            error = ex.Message;
            _trace.Log($"[DOTNET][PLOT][BUILD][ERROR] media={mediaName} mode={areaMode} err={ex}");
            return false;
        }
    }

    private void ApplyScaleSettings(
        PlotSettingsValidator validator,
        PlotSettings settings,
        double sx,
        double sy,
        BridgeBBox bbox,
        double paperWidthMm,
        double paperHeightMm
    )
    {
        if (_task.Plot.ScaleMode.Equals("scale_to_fit", StringComparison.OrdinalIgnoreCase))
        {
            validator.SetUseStandardScale(settings, true);
            validator.SetStdScaleType(settings, StdScaleType.ScaleToFit);
            return;
        }

        var denominator = ResolveManualScaleDenominator(
            sx,
            sy,
            bbox,
            paperWidthMm,
            paperHeightMm
        );
        validator.SetUseStandardScale(settings, false);
        validator.SetCustomPrintScale(settings, new CustomScale(1.0, denominator));
    }

    private int ResolveManualScaleDenominator(
        double sx,
        double sy,
        BridgeBBox bbox,
        double paperWidthMm,
        double paperHeightMm
    )
    {
        var candidates = new List<double>();
        if (sx > 1e-6)
        {
            candidates.Add(sx);
        }

        if (sy > 1e-6)
        {
            candidates.Add(sy);
        }

        if (paperWidthMm > 1e-6 && bbox.Width > 1e-6)
        {
            candidates.Add(bbox.Width / paperWidthMm);
        }

        if (paperHeightMm > 1e-6 && bbox.Height > 1e-6)
        {
            candidates.Add(bbox.Height / paperHeightMm);
        }

        var measuredScale = candidates.Count > 0 ? candidates.Max() : 1.0;
        int rounded;
        if (_task.Plot.ScaleIntegerRounding.Equals("ceil", StringComparison.OrdinalIgnoreCase))
        {
            rounded = (int)Math.Ceiling(measuredScale);
        }
        else if (_task.Plot.ScaleIntegerRounding.Equals("round", StringComparison.OrdinalIgnoreCase))
        {
            rounded = (int)Math.Round(measuredScale, MidpointRounding.AwayFromZero);
        }
        else
        {
            rounded = (int)Math.Floor(measuredScale);
        }

        return Math.Max(1, rounded);
    }

    private static BridgeBBox BuildWindowBBox(
        List<BridgePoint> vertices,
        BridgeBBox fallback
    )
    {
        if (vertices == null || vertices.Count < 2)
        {
            return fallback;
        }

        var xmin = vertices.Min(v => v.X);
        var ymin = vertices.Min(v => v.Y);
        var xmax = vertices.Max(v => v.X);
        var ymax = vertices.Max(v => v.Y);
        if (xmax - xmin <= 1e-6 || ymax - ymin <= 1e-6)
        {
            return fallback;
        }

        return new BridgeBBox(xmin, ymin, xmax, ymax);
    }

    private void TrySetPlotOffset(
        PlotSettingsValidator validator,
        PlotSettings settings,
        double offsetXmm,
        double offsetYmm
    )
    {
        try
        {
            validator.SetPlotOrigin(settings, new Point2d(offsetXmm, offsetYmm));
        }
        catch (System.Exception ex)
        {
            _trace.Log($"[DOTNET][PLOT][WARN] set plot offset failed: {ex.Message}");
        }
    }

    private static Extents2d ToDcsWindow(Editor editor, BridgeBBox bbox)
    {
        _ = editor;
        var p1 = new Point2d(bbox.Xmin, bbox.Ymin);
        var p2 = new Point2d(bbox.Xmax, bbox.Ymax);
        return new Extents2d(
            Math.Min(p1.X, p2.X),
            Math.Min(p1.Y, p2.Y),
            Math.Max(p1.X, p2.X),
            Math.Max(p1.Y, p2.Y)
        );
    }

    private List<string> GetStrictMediaCandidates(
        Database db,
        string paperVariantId,
        string paperMediaName,
        double paperWidthMm,
        double paperHeightMm
    )
    {
        if (paperWidthMm <= 1e-6 || paperHeightMm <= 1e-6)
        {
            return new List<string>();
        }

        var cacheKey = BuildPaperKey(paperVariantId, paperMediaName, paperWidthMm, paperHeightMm);
        if (_strictMediaCandidatesCache.TryGetValue(cacheKey, out var cached))
        {
            return new List<string>(cached);
        }

        var availableMediaNames = GetAvailableMediaNames(db);
        var resolved = ResolveMediaCandidates(
            paperVariantId,
            paperMediaName,
            paperWidthMm,
            paperHeightMm,
            availableMediaNames
        );
        if (resolved.Count > 0)
        {
            _strictMediaCandidatesCache[cacheKey] = resolved;
            return new List<string>(resolved);
        }

        if (_missingMediaLogged.Add(cacheKey))
        {
            var variantTag = string.IsNullOrWhiteSpace(paperVariantId) ? "-" : paperVariantId;
            var mediaTag = string.IsNullOrWhiteSpace(paperMediaName) ? "-" : paperMediaName;
            if (availableMediaNames.Count > 0)
            {
                _trace.Log(
                    $"[DOTNET][PLOT][MEDIA] variant={variantTag} media_hint={mediaTag} target={paperWidthMm:F3}x{paperHeightMm:F3} available_count={availableMediaNames.Count} sample={string.Join(" | ", availableMediaNames.Take(30))}"
                );
            }
            else
            {
                _trace.Log(
                    $"[DOTNET][PLOT][WARN] media list unavailable for variant={variantTag} media_hint={mediaTag} target={paperWidthMm:F3}x{paperHeightMm:F3}"
                );
            }
        }

        _strictMediaCandidatesCache[cacheKey] = new List<string>();
        return new List<string>();
    }

    private List<string> ResolveMediaCandidates(
        string paperVariantId,
        string paperMediaName,
        double paperWidthMm,
        double paperHeightMm,
        List<string> availableMediaNames
    )
    {
        var explicitHintMatched = ResolveExplicitHintMediaCandidates(
            paperMediaName,
            paperWidthMm,
            paperHeightMm,
            availableMediaNames
        );
        if (explicitHintMatched.Count > 0)
        {
            return explicitHintMatched;
        }

        var nameMatched = ResolveNameMatchedMediaCandidates(
            paperVariantId,
            paperWidthMm,
            paperHeightMm,
            availableMediaNames
        );
        if (nameMatched.Count > 0)
        {
            return nameMatched;
        }

        return ResolveStrictMediaCandidates(paperWidthMm, paperHeightMm, availableMediaNames);
    }

    private List<string> ResolveExplicitHintMediaCandidates(
        string paperMediaName,
        double paperWidthMm,
        double paperHeightMm,
        List<string> availableMediaNames
    )
    {
        var hintToken = NormalizeMediaHintToken(paperMediaName);
        if (string.IsNullOrWhiteSpace(hintToken) || availableMediaNames.Count <= 0)
        {
            return new List<string>();
        }

        var desiredLandscape = paperWidthMm > paperHeightMm;
        var candidates = new List<(string Name, int OrientationScore, int PrefixScore, double Delta)>();
        foreach (var mediaName in availableMediaNames)
        {
            if (!IsMediaNameMatchedByHint(mediaName, hintToken))
            {
                continue;
            }

            var orientationScore = 2;
            var delta = double.MaxValue;
            if (TryExtractMediaSizeMm(mediaName, out var mediaW, out var mediaH))
            {
                var mediaLandscape = mediaW > mediaH;
                var mediaIsSquare = Math.Abs(mediaW - mediaH) <= MediaToleranceMm;
                if (!mediaIsSquare && mediaLandscape != desiredLandscape)
                {
                    continue;
                }
                orientationScore = 0;
                delta = Math.Abs(mediaW - paperWidthMm) + Math.Abs(mediaH - paperHeightMm);
            }

            var compactName = mediaName.Replace(" ", string.Empty);
            var compactHint = hintToken.Replace(" ", string.Empty);
            var prefixScore = compactName.StartsWith(compactHint, StringComparison.OrdinalIgnoreCase)
                ? 0
                : 1;
            candidates.Add((mediaName, orientationScore, prefixScore, delta));
        }

        return candidates
            .OrderBy(c => c.OrientationScore)
            .ThenBy(c => c.PrefixScore)
            .ThenBy(c => c.Delta)
            .ThenBy(c => c.Name, StringComparer.OrdinalIgnoreCase)
            .Select(c => c.Name)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static bool IsMediaNameMatchedByHint(string mediaName, string hintToken)
    {
        if (string.IsNullOrWhiteSpace(mediaName) || string.IsNullOrWhiteSpace(hintToken))
        {
            return false;
        }

        if (TryExtractMediaPaperToken(mediaName, out var mediaToken))
        {
            if (mediaToken.Equals(hintToken, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        var normalizedMedia = Regex.Replace(
            mediaName.ToUpperInvariant(),
            @"[^A-Z0-9\+\./]",
            string.Empty
        );
        var normalizedHint = Regex.Replace(
            hintToken.ToUpperInvariant(),
            @"[^A-Z0-9\+\./]",
            string.Empty
        );
        return normalizedMedia.IndexOf(normalizedHint, StringComparison.OrdinalIgnoreCase) >= 0;
    }

    private static string NormalizeMediaHintToken(string paperMediaName)
    {
        if (string.IsNullOrWhiteSpace(paperMediaName))
        {
            return string.Empty;
        }

        var match = Regex.Match(
            paperMediaName.ToUpperInvariant(),
            @"A\d+(?:\+\d+(?:/\d+|\.\d+)?)?",
            RegexOptions.IgnoreCase
        );
        if (match.Success)
        {
            return NormalizePaperToken(match.Value);
        }

        return Regex.Replace(
            paperMediaName.ToUpperInvariant(),
            @"[^A-Z0-9\+\./]",
            string.Empty
        );
    }

    private List<string> ResolveNameMatchedMediaCandidates(
        string paperVariantId,
        double paperWidthMm,
        double paperHeightMm,
        List<string> availableMediaNames
    )
    {
        var aliases = BuildVariantNameAliases(paperVariantId);
        if (aliases.Count <= 0 || availableMediaNames.Count <= 0)
        {
            return new List<string>();
        }

        var desiredLandscape = paperWidthMm > paperHeightMm;
        var candidates = new List<(string Name, int OrientationScore, int PrefixScore, double Delta)>();
        foreach (var mediaName in availableMediaNames)
        {
            if (!TryExtractMediaPaperToken(mediaName, out var mediaToken))
            {
                continue;
            }

            if (!aliases.Contains(mediaToken))
            {
                continue;
            }

            var orientationScore = 2;
            var delta = double.MaxValue;
            if (TryExtractMediaSizeMm(mediaName, out var mediaW, out var mediaH))
            {
                var mediaLandscape = mediaW > mediaH;
                var mediaIsSquare = Math.Abs(mediaW - mediaH) <= MediaToleranceMm;
                if (!mediaIsSquare && mediaLandscape != desiredLandscape)
                {
                    continue;
                }
                orientationScore = 0;
                delta = Math.Abs(mediaW - paperWidthMm) + Math.Abs(mediaH - paperHeightMm);
            }

            var compactName = mediaName.Replace(" ", string.Empty);
            var compactToken = mediaToken.Replace(" ", string.Empty);
            var prefixScore = compactName.StartsWith(
                compactToken,
                StringComparison.OrdinalIgnoreCase
            )
                ? 0
                : 1;

            candidates.Add((mediaName, orientationScore, prefixScore, delta));
        }

        return candidates
            .OrderBy(c => c.OrientationScore)
            .ThenBy(c => c.PrefixScore)
            .ThenBy(c => c.Delta)
            .ThenBy(c => c.Name, StringComparer.OrdinalIgnoreCase)
            .Select(c => c.Name)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private List<string> ResolveStrictMediaCandidates(
        double paperWidthMm,
        double paperHeightMm,
        List<string> availableMediaNames
    )
    {
        var candidates = new List<(string Name, int OrientationScore, double Delta)>();
        var paperIsSquare = Math.Abs(paperWidthMm - paperHeightMm) <= MediaToleranceMm;
        foreach (var mediaName in availableMediaNames)
        {
            if (!TryExtractMediaSizeMm(mediaName, out var mediaW, out var mediaH))
            {
                continue;
            }

            if (IsNearPair(mediaW, mediaH, paperWidthMm, paperHeightMm, MediaToleranceMm))
            {
                var delta = Math.Abs(mediaW - paperWidthMm) + Math.Abs(mediaH - paperHeightMm);
                candidates.Add((mediaName, 0, delta));
                continue;
            }

            if (paperIsSquare
                && IsNearPair(mediaW, mediaH, paperHeightMm, paperWidthMm, MediaToleranceMm))
            {
                var delta = Math.Abs(mediaW - paperHeightMm) + Math.Abs(mediaH - paperWidthMm);
                candidates.Add((mediaName, 1, delta));
            }
        }

        var strictFromMediaList = candidates
            .OrderBy(c => c.OrientationScore)
            .ThenBy(c => c.Delta)
            .ThenBy(c => c.Name, StringComparer.OrdinalIgnoreCase)
            .Select(c => c.Name)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        if (strictFromMediaList.Count > 0)
        {
            return strictFromMediaList;
        }

        return new List<string>();
    }

    private void RunMediaPrecheck(Database db, BridgeResultEnvelope result)
    {
        var requested = CollectRequestedPaperSizes();
        if (requested.Count <= 0)
        {
            return;
        }

        var availableMediaNames = GetAvailableMediaNames(db);
        var missing = new List<PaperRequestInfo>();
        foreach (var item in requested.Values)
        {
            var candidates = ResolveMediaCandidates(
                item.VariantId,
                item.MediaName,
                item.WidthMm,
                item.HeightMm,
                availableMediaNames
            );
            if (candidates.Count <= 0)
            {
                missing.Add(item);
            }
        }

        if (missing.Count <= 0)
        {
            _trace.Log(
                $"[DOTNET][PLOT][PRECHECK] all required media available, unique_sizes={requested.Count}"
            );
            return;
        }

        foreach (var miss in missing)
        {
            var variant = string.IsNullOrWhiteSpace(miss.VariantId) ? "-" : miss.VariantId;
            var mediaName = string.IsNullOrWhiteSpace(miss.MediaName) ? "-" : miss.MediaName;
            var err =
                $"PLOT_MEDIA_PRECHECK_MISSING:{miss.WidthMm:F3}x{miss.HeightMm:F3}:variant={variant}:media={mediaName}:count={miss.Count}:examples={string.Join(",", miss.Examples)}";
            result.Errors.Add(err);
        }

        _trace.Log(
            $"[DOTNET][PLOT][PRECHECK][MISSING] {string.Join(" | ", missing.Select(m => $"{m.VariantId}:{m.MediaName}@{m.WidthMm:F3}x{m.HeightMm:F3} x{m.Count}"))}"
        );
    }

    private Dictionary<string, PaperRequestInfo> CollectRequestedPaperSizes()
    {
        var result = new Dictionary<string, PaperRequestInfo>(StringComparer.OrdinalIgnoreCase);

        void Add(string paperVariantId, string paperMediaName, double widthMm, double heightMm, string sampleId)
        {
            if (widthMm <= 1e-6 || heightMm <= 1e-6)
            {
                return;
            }

            var key = BuildPaperKey(paperVariantId, paperMediaName, widthMm, heightMm);
            if (!result.TryGetValue(key, out var item))
            {
                item = new PaperRequestInfo(paperVariantId, paperMediaName, widthMm, heightMm);
                result[key] = item;
            }

            item.Count += 1;
            if (item.Examples.Count < 4 && !item.Examples.Any(s => s.Equals(sampleId, StringComparison.OrdinalIgnoreCase)))
            {
                item.Examples.Add(sampleId);
            }
        }

        foreach (var frame in _task.Frames)
        {
            Add(
                frame.PaperVariantId,
                frame.PaperMediaName,
                frame.PaperWidthMm,
                frame.PaperHeightMm,
                $"frame:{frame.Name}"
            );
        }

        foreach (var sheetSet in _task.SheetSets)
        {
            foreach (var page in sheetSet.Pages)
            {
                Add(
                    page.PaperVariantId,
                    page.PaperMediaName,
                    page.PaperWidthMm,
                    page.PaperHeightMm,
                    $"sheet:{sheetSet.Name}#p{page.PageIndex}"
                );
            }
        }

        return result;
    }

    private List<string> GetAvailableMediaNames(Database db)
    {
        if (_availableMediaNamesCache != null)
        {
            return new List<string>(_availableMediaNamesCache);
        }

        var mediaNames = new List<string>();
        try
        {
            using var tr = db.TransactionManager.StartTransaction();
            var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
            var model = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
            var layout = (Layout)tr.GetObject(model.LayoutId, OpenMode.ForRead);
            var settings = new PlotSettings(layout.ModelType);
            settings.CopyFrom(layout);

            var validator = PlotSettingsValidator.Current;
            var configured = false;
            try
            {
                validator.SetPlotConfigurationName(settings, _task.Plot.Pc3Name, layout.CanonicalMediaName);
                configured = true;
            }
            catch
            {
                // ignore and fallback below
            }

            if (!configured)
            {
                validator.SetPlotConfigurationName(settings, _task.Plot.Pc3Name, null);
            }

            validator.RefreshLists(settings);
            var names = validator.GetCanonicalMediaNameList(settings);
            foreach (string mediaName in names)
            {
                if (!string.IsNullOrWhiteSpace(mediaName))
                {
                    mediaNames.Add(mediaName);
                }
            }

            tr.Commit();
        }
        catch (System.Exception ex)
        {
            _trace.Log($"[DOTNET][PLOT][WARN] get media list failed: {ex.Message}");
        }

        _availableMediaNamesCache = mediaNames
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        return new List<string>(_availableMediaNamesCache);
    }

    private static string BuildPaperKey(
        string paperVariantId,
        string paperMediaName,
        double widthMm,
        double heightMm
    )
    {
        var variant = string.IsNullOrWhiteSpace(paperVariantId)
            ? "-"
            : paperVariantId.Trim().ToUpperInvariant();
        var mediaName = string.IsNullOrWhiteSpace(paperMediaName)
            ? "-"
            : NormalizeMediaHintToken(paperMediaName);
        return $"{variant}|{mediaName}|{BuildPaperKey(widthMm, heightMm)}";
    }

    private static string BuildPaperKey(double widthMm, double heightMm)
    {
        return $"{widthMm:F3}x{heightMm:F3}";
    }

    private sealed class PaperRequestInfo
    {
        public PaperRequestInfo(
            string variantId,
            string mediaName,
            double widthMm,
            double heightMm
        )
        {
            VariantId = string.IsNullOrWhiteSpace(variantId) ? "-" : variantId;
            MediaName = string.IsNullOrWhiteSpace(mediaName) ? "-" : mediaName;
            WidthMm = widthMm;
            HeightMm = heightMm;
        }

        public string VariantId { get; }
        public string MediaName { get; }
        public double WidthMm { get; }
        public double HeightMm { get; }
        public int Count { get; set; }
        public List<string> Examples { get; } = new();
    }

    private static HashSet<string> BuildVariantNameAliases(string paperVariantId)
    {
        var aliases = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (string.IsNullOrWhiteSpace(paperVariantId))
        {
            return aliases;
        }

        var normalized = paperVariantId.Trim().ToUpperInvariant();
        if (normalized.StartsWith("CNPE_", StringComparison.OrdinalIgnoreCase))
        {
            normalized = normalized.Substring("CNPE_".Length);
        }

        if (normalized.EndsWith("H", StringComparison.OrdinalIgnoreCase) && normalized.Length > 2)
        {
            normalized = normalized.Substring(0, normalized.Length - 1);
        }

        var match = Regex.Match(
            normalized,
            @"^(?<base>A\d+)(?:\+(?<num>\d+)/(?<den>\d+))?$",
            RegexOptions.IgnoreCase
        );
        if (!match.Success)
        {
            return aliases;
        }

        var baseToken = match.Groups["base"].Value.ToUpperInvariant();
        if (!match.Groups["num"].Success || !match.Groups["den"].Success)
        {
            aliases.Add(baseToken);
            return aliases;
        }

        if (!int.TryParse(
                match.Groups["num"].Value,
                NumberStyles.Integer,
                CultureInfo.InvariantCulture,
                out var numerator
            ))
        {
            return aliases;
        }

        if (!int.TryParse(
                match.Groups["den"].Value,
                NumberStyles.Integer,
                CultureInfo.InvariantCulture,
                out var denominator
            ))
        {
            return aliases;
        }

        if (denominator <= 0)
        {
            return aliases;
        }

        var decimalValue = numerator / (double)denominator;
        var decimalSuffix = decimalValue.ToString("0.###", CultureInfo.InvariantCulture);
        aliases.Add(NormalizePaperToken($"{baseToken}+{decimalSuffix}"));
        aliases.Add(NormalizePaperToken($"{baseToken}+{numerator}/{denominator}"));
        if (denominator == 1)
        {
            aliases.Add(NormalizePaperToken($"{baseToken}+{numerator}"));
        }

        return aliases;
    }

    private static bool TryExtractMediaPaperToken(string mediaName, out string token)
    {
        token = string.Empty;
        if (string.IsNullOrWhiteSpace(mediaName))
        {
            return false;
        }

        var match = Regex.Match(
            mediaName.ToUpperInvariant(),
            @"A\d+(?:\+\d+(?:/\d+|\.\d+)?)?",
            RegexOptions.IgnoreCase
        );
        if (!match.Success)
        {
            return false;
        }

        token = NormalizePaperToken(match.Value);
        return !string.IsNullOrWhiteSpace(token);
    }

    private static string NormalizePaperToken(string rawToken)
    {
        var token = rawToken.Trim().ToUpperInvariant().Replace(" ", string.Empty);
        var plusIdx = token.IndexOf('+');
        if (plusIdx < 0 || plusIdx == token.Length - 1)
        {
            return token;
        }

        var prefix = token.Substring(0, plusIdx);
        var suffix = token.Substring(plusIdx + 1);
        if (suffix.Contains("/"))
        {
            var parts = suffix.Split('/');
            if (parts.Length == 2
                && double.TryParse(
                    parts[0],
                    NumberStyles.Float,
                    CultureInfo.InvariantCulture,
                    out var numerator
                )
                && double.TryParse(
                    parts[1],
                    NumberStyles.Float,
                    CultureInfo.InvariantCulture,
                    out var denominator
                )
                && denominator > 1e-9)
            {
                var decimalValue = numerator / denominator;
                var decimalSuffix = decimalValue.ToString("0.###", CultureInfo.InvariantCulture);
                return $"{prefix}+{decimalSuffix}";
            }

            return token;
        }

        if (double.TryParse(
                suffix,
                NumberStyles.Float,
                CultureInfo.InvariantCulture,
                out var numericSuffix
            ))
        {
            var normalizedSuffix = numericSuffix.ToString("0.###", CultureInfo.InvariantCulture);
            return $"{prefix}+{normalizedSuffix}";
        }

        return token;
    }

    private static List<string> BuildFallbackMediaCandidates(double paperWidthMm, double paperHeightMm)
    {
        static IEnumerable<string> BuildFor(double width, double height)
        {
            var w = width.ToString("0.00", CultureInfo.InvariantCulture);
            var h = height.ToString("0.00", CultureInfo.InvariantCulture);
            string[] underscorePrefixes =
            {
                "ISO_expand_A0",
                "ISO_expand_A1",
                "ISO_expand_A2",
                "ISO_A0",
                "ISO_A1",
                "ISO_A2",
                "ISO_A3",
                "ISO_A4",
                "ISO_full_bleed_A0",
                "ISO_full_bleed_A1",
                "ISO_full_bleed_A2",
                "ISO_full_bleed_A3",
                "ISO_full_bleed_A4",
            };
            string[] spacePrefixes =
            {
                "ISO expand A0",
                "ISO expand A1",
                "ISO expand A2",
                "ISO A0",
                "ISO A1",
                "ISO A2",
                "ISO A3",
                "ISO A4",
                "ISO full bleed A0",
                "ISO full bleed A1",
                "ISO full bleed A2",
                "ISO full bleed A3",
                "ISO full bleed A4",
            };
            foreach (var prefix in underscorePrefixes)
            {
                yield return $"{prefix}_({w}_x_{h}_MM)";
            }

            foreach (var prefix in spacePrefixes)
            {
                yield return $"{prefix} ({w} x {h} MM)";
                yield return $"{prefix} ({w} x {h} mm)";
            }

            yield return $"UserDefinedMetric ({w} x {h}mm)";
            yield return $"UserDefinedMetric ({w} x {h} mm)";
            yield return $"UserDefinedMetric ({w} x {h} MM)";
            yield return $"UserDefinedMetric ({w} x {h} 毫米)";
            yield return $"UserDefinedMetric ({w}_x_{h}_MM)";
        }

        return BuildFor(paperWidthMm, paperHeightMm)
            .Concat(BuildFor(paperHeightMm, paperWidthMm))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static bool TryExtractMediaSizeMm(string mediaName, out double widthMm, out double heightMm)
    {
        widthMm = 0.0;
        heightMm = 0.0;
        if (string.IsNullOrWhiteSpace(mediaName))
        {
            return false;
        }

        var normalized = mediaName.Replace(',', '.');
        var match = Regex.Match(
            normalized,
            @"\((?<w>\d+(?:\.\d+)?)\s*_x_\s*(?<h>\d+(?:\.\d+)?)\s*_MM\)",
            RegexOptions.IgnoreCase
        );
        if (!match.Success)
        {
            match = Regex.Match(
                normalized,
                @"\((?<w>\d+(?:\.\d+)?)\s*[xX×]\s*(?<h>\d+(?:\.\d+)?)\s*(?:mm|MM|毫米)?\)",
                RegexOptions.IgnoreCase
            );
            if (match.Success)
            {
                if (!double.TryParse(
                        match.Groups["w"].Value,
                        NumberStyles.Float,
                        CultureInfo.InvariantCulture,
                        out widthMm
                    ))
                {
                    return false;
                }

                if (!double.TryParse(
                        match.Groups["h"].Value,
                        NumberStyles.Float,
                        CultureInfo.InvariantCulture,
                        out heightMm
                    ))
                {
                    return false;
                }

                return true;
            }

            match = Regex.Match(
                normalized,
                @"\((?<w>\d+(?:\.\d+)?)\s*_x_\s*(?<h>\d+(?:\.\d+)?)\s*_(?:Inches|INCHES)\)",
                RegexOptions.IgnoreCase
            );
            if (!match.Success)
            {
                match = Regex.Match(
                    normalized,
                    @"\((?<w>\d+(?:\.\d+)?)\s*[xX×]\s*(?<h>\d+(?:\.\d+)?)\s*(?:Inches|INCHES)\)",
                    RegexOptions.IgnoreCase
                );
            }

            if (!match.Success)
            {
                return false;
            }

            if (!double.TryParse(
                    match.Groups["w"].Value,
                    NumberStyles.Float,
                    CultureInfo.InvariantCulture,
                    out var widthIn
                ))
            {
                return false;
            }

            if (!double.TryParse(
                    match.Groups["h"].Value,
                    NumberStyles.Float,
                    CultureInfo.InvariantCulture,
                    out var heightIn
                ))
            {
                return false;
            }

            widthMm = widthIn * 25.4;
            heightMm = heightIn * 25.4;
            return true;
        }

        if (!double.TryParse(
                match.Groups["w"].Value,
                NumberStyles.Float,
                CultureInfo.InvariantCulture,
                out widthMm
            ))
        {
            return false;
        }

        if (!double.TryParse(
                match.Groups["h"].Value,
                NumberStyles.Float,
                CultureInfo.InvariantCulture,
                out heightMm
            ))
        {
            return false;
        }

        return true;
    }

    private static bool IsNearPair(
        double actualW,
        double actualH,
        double expectedW,
        double expectedH,
        double toleranceMm
    )
    {
        return Math.Abs(actualW - expectedW) <= toleranceMm
               && Math.Abs(actualH - expectedH) <= toleranceMm;
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
