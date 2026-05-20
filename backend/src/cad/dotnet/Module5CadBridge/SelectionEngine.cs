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
        else if (TryWriteWblock(
                     db,
                     selectedIds,
                     outputDwg,
                     _task.SourceDwgVersion,
                     frame.BBox.Expand(_task.Selection.BBoxMarginPercent),
                     _trace,
                     out var writeError,
                     out var cleanedCount
                 ))
        {
            status = "ok";
            if (cleanedCount > 0)
            {
                flags.Add($"DWG_OUTSIDE_ENTITY_CLEANED:{cleanedCount}");
            }
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

            if (TryWriteWblock(
                    db,
                    pageIds,
                    pageDwg,
                    _task.SourceDwgVersion,
                    page.BBox.Expand(_task.Selection.BBoxMarginPercent),
                    _trace,
                    out _,
                    out _
                ))
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
        else if (TryWriteWblock(
                     db,
                     union,
                     unionDwg,
                     _task.SourceDwgVersion,
                     UnionPageBBoxes(sheetSet).Expand(_task.Selection.BBoxMarginPercent),
                     _trace,
                     out var writeError,
                     out var cleanedCount
                 ))
        {
            if (cleanedCount > 0)
            {
                flags.Add($"DWG_OUTSIDE_ENTITY_CLEANED:{cleanedCount}");
            }
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
                if (ShouldKeepEntityInSelection(ent!, extents, bbox))
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
        BridgeBBox cleanupBBox,
        BridgeTraceLogger trace,
        out string error,
        out int cleanedCount
    )
    {
        cleanedCount = 0;
        error = string.Empty;
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(outputDwg) ?? ".");
            var idCollection = new ObjectIdCollection(ids.ToArray());
            using var targetDb = new Database(true, true);
            sourceDb.Wblock(targetDb, idCollection, Point3d.Origin, DuplicateRecordCloning.Ignore);
            cleanedCount = CleanOutsideEntities(targetDb, cleanupBBox, trace);
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

    private static int CleanOutsideEntities(
        Database db,
        BridgeBBox cleanupBBox,
        BridgeTraceLogger trace
    )
    {
        var erased = 0;

        using var tr = db.TransactionManager.StartTransaction();
        if (!SafeCadAccess.TryGetObject(
                tr,
                db.BlockTableId,
                OpenMode.ForRead,
                trace,
                "selection.cleanup.block_table",
                out BlockTable? bt
            ))
        {
            return erased;
        }

        if (!SafeCadAccess.TryRead(
                () => bt![BlockTableRecord.ModelSpace],
                trace,
                "selection.cleanup.model_space_id",
                out ObjectId modelSpaceId
            ))
        {
            return erased;
        }

        if (!SafeCadAccess.TryGetObject(
                tr,
                modelSpaceId,
                OpenMode.ForRead,
                trace,
                "selection.cleanup.model_space",
                out BlockTableRecord? modelSpace
            ))
        {
            return erased;
        }

        var eraseIds = new List<ObjectId>();
        foreach (ObjectId id in modelSpace!)
        {
            if (!SafeCadAccess.TryGetObject(
                    tr,
                    id,
                    OpenMode.ForRead,
                    trace,
                    "selection.cleanup.entity",
                    out Entity? ent
                ))
            {
                continue;
            }

            if (!TryGetEntityExtents(ent!, out var extents))
            {
                continue;
            }

            if (!ShouldKeepEntityInSelection(ent!, extents, cleanupBBox))
            {
                eraseIds.Add(id);
            }
        }

        foreach (var id in eraseIds)
        {
            if (!SafeCadAccess.TryGetObject(
                    tr,
                    id,
                    OpenMode.ForWrite,
                    trace,
                    "selection.cleanup.erase_entity",
                    out Entity? ent
                ))
            {
                continue;
            }

            ent!.Erase();
            erased += 1;
        }

        tr.Commit();
        if (erased > 0)
        {
            trace.Log($"[DOTNET][SPLIT][CLEANUP] erased_outside_entities={erased}");
        }

        return erased;
    }

    private static bool ShouldKeepEntityInSelection(
        Entity entity,
        Extents3d extents,
        BridgeBBox bbox
    )
    {
        if (!Intersects(extents, bbox))
        {
            return false;
        }

        if (!TryGetTextReferencePoint(entity, out var textPoint))
        {
            return true;
        }

        return ContainsPoint(bbox, textPoint);
    }

    private static bool TryGetTextReferencePoint(Entity entity, out Point3d point)
    {
        switch (entity)
        {
            case MText mtext:
                point = mtext.Location;
                return true;
            case AttributeReference attribute:
                point = attribute.Position;
                return true;
            case AttributeDefinition attributeDefinition:
                point = attributeDefinition.Position;
                return true;
            case DBText dbText:
                point = dbText.Position;
                return true;
            default:
                point = Point3d.Origin;
                return false;
        }
    }

    private static bool ContainsPoint(BridgeBBox bbox, Point3d point)
    {
        return point.X >= bbox.Xmin
               && point.X <= bbox.Xmax
               && point.Y >= bbox.Ymin
               && point.Y <= bbox.Ymax;
    }

    private static BridgeBBox UnionPageBBoxes(BridgeSheetSetTask sheetSet)
    {
        var pages = sheetSet.Pages;
        if (pages.Count == 0)
        {
            return BridgeBBox.Empty;
        }

        var xmin = pages[0].BBox.Xmin;
        var ymin = pages[0].BBox.Ymin;
        var xmax = pages[0].BBox.Xmax;
        var ymax = pages[0].BBox.Ymax;
        foreach (var page in pages.Skip(1))
        {
            xmin = Math.Min(xmin, page.BBox.Xmin);
            ymin = Math.Min(ymin, page.BBox.Ymin);
            xmax = Math.Max(xmax, page.BBox.Xmax);
            ymax = Math.Max(ymax, page.BBox.Ymax);
        }

        return new BridgeBBox(xmin, ymin, xmax, ymax);
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
