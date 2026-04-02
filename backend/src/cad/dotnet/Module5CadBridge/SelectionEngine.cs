using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace Module5CadBridge;

internal sealed class SelectionEngine
{
    private readonly BridgeTask _task;
    private readonly BridgeTraceLogger _trace;

    public SelectionEngine(BridgeTask task, BridgeTraceLogger trace)
    {
        _task = task;
        _trace = trace;
    }

    public void Execute(Database db, BridgeResultEnvelope result)
    {
        foreach (var frame in _task.Frames)
        {
            result.Frames.Add(ExportFrame(db, frame));
        }

        foreach (var sheetSet in _task.SheetSets)
        {
            result.SheetSets.Add(ExportSheetSet(db, sheetSet));
        }
    }

    private Dictionary<string, object> ExportFrame(Database db, BridgeFrameTask frame)
    {
        var selectedIds = SelectWithRetry(db, frame.BBox);
        var outputDwg = Path.Combine(_task.OutputDir, $"{frame.Name}.dwg");
        var flags = new List<string>();
        var status = "failed";
        var hasSelectionExtents = TryGetSelectionExtents(db, selectedIds, out var selectionExtents);

        if (selectedIds.Count <= 0)
        {
            flags.Add("CAD_EMPTY_SELECTION");
        }
        else if (TryWriteWblock(db, selectedIds, outputDwg, _task.SourceDwgVersion, out var writeError))
        {
            status = "ok";
            _trace.Log($"[DOTNET][SPLIT] frame={frame.FrameId} selected={selectedIds.Count} dwg={outputDwg}");
        }
        else
        {
            flags.Add($"WBLOCK_FAILED:{writeError}");
        }

        return new Dictionary<string, object>
        {
            ["frame_id"] = frame.FrameId,
            ["status"] = status,
            ["pdf_path"] = string.Empty,
            ["dwg_path"] = outputDwg,
            ["selection_count"] = selectedIds.Count,
            ["flags"] = flags,
            ["selection_extents"] = hasSelectionExtents ? selectionExtents!.ToDictionary() : null!,
        };
    }

    private Dictionary<string, object> ExportSheetSet(Database db, BridgeSheetSetTask sheetSet)
    {
        var pageDwgPaths = new List<string>();
        var pagePdfPaths = new List<string>();
        var flags = new List<string>();
        var union = new HashSet<ObjectId>();
        var pagePartial = false;

        foreach (var page in sheetSet.Pages)
        {
            var pageIds = SelectWithRetry(db, page.BBox);
            foreach (var id in pageIds)
            {
                union.Add(id);
            }

            var pageDwg = Path.Combine(_task.OutputDir, $"{sheetSet.Name}__p{page.PageIndex}.dwg");
            if (pageIds.Count <= 0)
            {
                pagePartial = true;
                continue;
            }

            if (TryWriteWblock(db, pageIds, pageDwg, _task.SourceDwgVersion, out _))
            {
                pageDwgPaths.Add(pageDwg);
            }
            else
            {
                pagePartial = true;
            }
        }

        var unionDwg = Path.Combine(_task.OutputDir, $"{sheetSet.Name}.dwg");
        var unionPdf = Path.Combine(_task.OutputDir, $"{sheetSet.Name}.pdf");
        var status = "failed";

        if (union.Count <= 0)
        {
            flags.Add("CAD_EMPTY_SELECTION");
        }
        else if (TryWriteWblock(db, union, unionDwg, _task.SourceDwgVersion, out var writeError))
        {
            if (pagePartial || pageDwgPaths.Count != sheetSet.Pages.Count)
            {
                flags.Add("A4_PAGE_WBLOCK_PARTIAL");
            }
            else
            {
                status = "ok";
            }
            _trace.Log($"[DOTNET][SPLIT] sheet={sheetSet.ClusterId} union={union.Count} pages={pageDwgPaths.Count}/{sheetSet.Pages.Count}");
        }
        else
        {
            flags.Add($"WBLOCK_FAILED:{writeError}");
        }

        return new Dictionary<string, object>
        {
            ["cluster_id"] = sheetSet.ClusterId,
            ["status"] = status,
            ["pdf_path"] = unionPdf,
            ["dwg_path"] = unionDwg,
            ["page_count"] = sheetSet.Pages.Count,
            ["flags"] = flags,
            ["page_dwg_paths"] = pageDwgPaths,
            ["page_pdf_paths"] = pagePdfPaths,
        };
    }

    private HashSet<ObjectId> SelectWithRetry(Database db, BridgeBBox bbox)
    {
        var first = SelectByBBox(db, bbox.Expand(_task.Selection.BBoxMarginPercent));
        if (first.Count > 0)
        {
            return first;
        }

        var second = SelectByBBox(db, bbox.Expand(_task.Selection.EmptySelectionRetryMarginPercent));
        if (second.Count > 0)
        {
            return second;
        }

        return SelectByBBox(db, bbox.Expand(_task.Selection.HardRetryMarginPercent));
    }

    private HashSet<ObjectId> SelectByBBox(Database db, BridgeBBox bbox)
    {
        var selected = new HashSet<ObjectId>();
        var keepIfUncertain = _task.Selection.DbUnknownBboxPolicy.Equals(
            "keep_if_uncertain",
            StringComparison.OrdinalIgnoreCase
        );

        using var tr = db.TransactionManager.StartTransaction();
        if (!SafeCadAccess.TryGetObject(
                tr,
                db.BlockTableId,
                OpenMode.ForRead,
                _trace,
                "selection.block_table",
                out BlockTable? bt
            ))
        {
            return selected;
        }

        if (!SafeCadAccess.TryRead(
                () => bt![BlockTableRecord.ModelSpace],
                _trace,
                "selection.model_space_id",
                out ObjectId modelSpaceId
            ))
        {
            return selected;
        }

        if (!SafeCadAccess.TryGetObject(
                tr,
                modelSpaceId,
                OpenMode.ForRead,
                _trace,
                "selection.model_space",
                out BlockTableRecord? modelSpace
            ))
        {
            return selected;
        }

        foreach (ObjectId id in modelSpace!)
        {
            if (!SafeCadAccess.TryGetObject(
                    tr,
                    id,
                    OpenMode.ForRead,
                    _trace,
                    "selection.entity",
                    out Entity? ent
                ))
            {
                continue;
            }

            if (TryGetEntityExtents(ent!, out var extents))
            {
                if (Intersects(extents, bbox))
                {
                    selected.Add(id);
                }
            }
            else if (keepIfUncertain)
            {
                selected.Add(id);
            }
        }

        tr.Commit();
        return selected;
    }

    private static bool TryWriteWblock(
        Database sourceDb,
        IEnumerable<ObjectId> ids,
        string outputDwg,
        string sourceDwgVersion,
        out string error
    )
    {
        error = string.Empty;
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(outputDwg) ?? ".");
            var idCollection = new ObjectIdCollection(ids.ToArray());
            using var targetDb = new Database(true, true);
            sourceDb.Wblock(targetDb, idCollection, Point3d.Origin, DuplicateRecordCloning.Ignore);
            var saveVersion = DwgVersionResolver.Resolve(
                sourceDwgVersion,
                sourceDb.OriginalFileVersion
            );
            targetDb.SaveAs(outputDwg, saveVersion);
            return File.Exists(outputDwg);
        }
        catch (Exception ex)
        {
            error = ex.Message;
            return false;
        }
    }

    private static bool TryGetEntityExtents(Entity entity, out Extents3d extents)
    {
        try
        {
            extents = entity.GeometricExtents;
            return true;
        }
        catch
        {
            try
            {
                var bounds = entity.Bounds;
                if (bounds.HasValue)
                {
                    extents = bounds.Value;
                    return true;
                }
            }
            catch
            {
                // ignored
            }
        }

        extents = default;
        return false;
    }

    private bool TryGetSelectionExtents(
        Database db,
        IEnumerable<ObjectId> ids,
        out BridgeBBox? bbox
    )
    {
        bbox = null;
        var hasExtents = false;
        double xmin = 0.0;
        double ymin = 0.0;
        double xmax = 0.0;
        double ymax = 0.0;

        using var tr = db.TransactionManager.StartTransaction();
        foreach (var id in ids)
        {
            if (!SafeCadAccess.TryGetObject(
                    tr,
                    id,
                    OpenMode.ForRead,
                    _trace,
                    "selection.extents.entity",
                    out Entity? ent
                ))
            {
                continue;
            }

            if (!TryGetEntityExtents(ent!, out var extents))
            {
                continue;
            }

            if (!hasExtents)
            {
                xmin = extents.MinPoint.X;
                ymin = extents.MinPoint.Y;
                xmax = extents.MaxPoint.X;
                ymax = extents.MaxPoint.Y;
                hasExtents = true;
                continue;
            }

            xmin = Math.Min(xmin, extents.MinPoint.X);
            ymin = Math.Min(ymin, extents.MinPoint.Y);
            xmax = Math.Max(xmax, extents.MaxPoint.X);
            ymax = Math.Max(ymax, extents.MaxPoint.Y);
        }

        tr.Commit();
        if (!hasExtents)
        {
            return false;
        }

        bbox = new BridgeBBox(xmin, ymin, xmax, ymax);
        return true;
    }

    private static bool Intersects(Extents3d extents, BridgeBBox bbox)
    {
        return !(extents.MinPoint.X > bbox.Xmax
                 || extents.MaxPoint.X < bbox.Xmin
                 || extents.MinPoint.Y > bbox.Ymax
                 || extents.MaxPoint.Y < bbox.Ymin);
    }
}
