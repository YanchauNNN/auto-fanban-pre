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

        if (selectedIds.Count <= 0)
        {
            flags.Add("CAD_EMPTY_SELECTION");
        }
        else if (TryWriteWblock(db, selectedIds, outputDwg, out var writeError))
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

            if (TryWriteWblock(db, pageIds, pageDwg, out _))
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
        else if (TryWriteWblock(db, union, unionDwg, out var writeError))
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
        var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
        var modelSpace = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
        foreach (ObjectId id in modelSpace)
        {
            if (!(tr.GetObject(id, OpenMode.ForRead, false) is Entity ent))
            {
                continue;
            }

            if (TryGetEntityExtents(ent, out var extents))
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

    private static bool TryWriteWblock(Database sourceDb, IEnumerable<ObjectId> ids, string outputDwg, out string error)
    {
        error = string.Empty;
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(outputDwg) ?? ".");
            var idCollection = new ObjectIdCollection(ids.ToArray());
            using var targetDb = new Database(true, true);
            sourceDb.Wblock(targetDb, idCollection, Point3d.Origin, DuplicateRecordCloning.Ignore);
            targetDb.SaveAs(outputDwg, DwgVersion.Current);
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

    private static bool Intersects(Extents3d extents, BridgeBBox bbox)
    {
        return !(extents.MinPoint.X > bbox.Xmax
                 || extents.MaxPoint.X < bbox.Xmin
                 || extents.MinPoint.Y > bbox.Ymax
                 || extents.MaxPoint.Y < bbox.Ymin);
    }
}
