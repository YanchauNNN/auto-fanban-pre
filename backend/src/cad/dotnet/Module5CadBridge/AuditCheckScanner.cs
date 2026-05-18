using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace Module5CadBridge;

internal sealed class AuditCheckScanner
{
    private readonly BridgeTask _task;
    private readonly BridgeTraceLogger _trace;

    public AuditCheckScanner(BridgeTask task, BridgeTraceLogger trace)
    {
        _task = task;
        _trace = trace;
    }

    public void Execute(BridgeResultEnvelope result)
    {
        using var db = new Database(false, true);
        db.ReadDwgFile(_task.SourceDxf, FileShare.ReadWrite, true, string.Empty);
        db.CloseInput(true);

        using var tr = db.TransactionManager.StartTransaction();
        var blockTable = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);

        foreach (ObjectId recordId in blockTable)
        {
            if (!(tr.GetObject(recordId, OpenMode.ForRead) is BlockTableRecord record))
            {
                continue;
            }

            if (!record.IsLayout)
            {
                continue;
            }

            var layoutName = ResolveLayoutName(record, tr);
            var blockPath = new List<string>();
            foreach (ObjectId entityId in record)
            {
                if (!(tr.GetObject(entityId, OpenMode.ForRead, false) is Entity entity))
                {
                    continue;
                }

                ScanEntity(
                    tr,
                    entity,
                    layoutName,
                    blockPath,
                    Matrix3d.Identity,
                    result.Texts
                );
            }
        }

        tr.Commit();
        _trace.Log($"[DOTNET][AUDIT] scanned_texts={result.Texts.Count} source={_task.SourceDxf}");
    }

    private void ScanEntity(
        Transaction tr,
        Entity entity,
        string layoutName,
        List<string> blockPath,
        Matrix3d transform,
        List<Dictionary<string, object>> sink
    )
    {
        switch (entity)
        {
            case AttributeDefinition attributeDefinition:
                AddText(
                    sink,
                    rawText: attributeDefinition.TextString,
                    entityType: nameof(AttributeDefinition),
                    layoutName: layoutName,
                    entityHandle: attributeDefinition.Handle.ToString(),
                    blockPath: blockPath,
                    position: TransformPoint(attributeDefinition.Position, transform),
                    bbox: TryGetEntityBounds(attributeDefinition, transform)
                );
                return;
            case AttributeReference attributeReference:
                AddText(
                    sink,
                    rawText: attributeReference.TextString,
                    entityType: nameof(AttributeReference),
                    layoutName: layoutName,
                    entityHandle: attributeReference.Handle.ToString(),
                    blockPath: blockPath,
                    position: TransformPoint(attributeReference.Position, transform),
                    bbox: TryGetEntityBounds(attributeReference, transform)
                );
                return;
            case DBText dbText:
                AddText(
                    sink,
                    rawText: dbText.TextString,
                    entityType: nameof(DBText),
                    layoutName: layoutName,
                    entityHandle: dbText.Handle.ToString(),
                    blockPath: blockPath,
                    position: TransformPoint(dbText.Position, transform),
                    bbox: TryGetEntityBounds(dbText, transform)
                );
                return;
            case MText mText:
                AddText(
                    sink,
                    rawText: mText.Text,
                    entityType: nameof(MText),
                    layoutName: layoutName,
                    entityHandle: mText.Handle.ToString(),
                    blockPath: blockPath,
                    position: TransformPoint(mText.Location, transform),
                    bbox: TryGetEntityBounds(mText, transform)
                );
                return;
            case Dimension dimension:
                if (!string.IsNullOrWhiteSpace(dimension.DimensionText) && !dimension.DimensionText.Equals("<>", StringComparison.Ordinal))
                {
                    AddText(
                        sink,
                        rawText: dimension.DimensionText,
                        entityType: nameof(Dimension),
                        layoutName: layoutName,
                        entityHandle: dimension.Handle.ToString(),
                        blockPath: blockPath,
                        position: TransformPoint(dimension.TextPosition, transform),
                        bbox: TryGetEntityBounds(dimension, transform)
                    );
                }
                return;
            case MLeader leader:
                if (TryGetMLeaderText(leader, out var leaderText))
                {
                    AddText(
                        sink,
                        rawText: leaderText,
                        entityType: nameof(MLeader),
                        layoutName: layoutName,
                        entityHandle: leader.Handle.ToString(),
                        blockPath: blockPath,
                        position: TryGetLeaderPosition(leader, transform),
                        bbox: TryGetEntityBounds(leader, transform)
                    );
                }
                return;
            case Table table:
                AddTableTexts(sink, table, layoutName, blockPath, transform);
                return;
            case BlockReference blockReference:
                ScanBlockReference(tr, blockReference, layoutName, blockPath, transform, sink);
                return;
            default:
                return;
        }
    }

    private void ScanBlockReference(
        Transaction tr,
        BlockReference blockReference,
        string layoutName,
        List<string> blockPath,
        Matrix3d parentTransform,
        List<Dictionary<string, object>> sink
    )
    {
        foreach (ObjectId attributeId in blockReference.AttributeCollection)
        {
            if (attributeId.IsNull || attributeId.IsErased)
            {
                continue;
            }

            if (tr.GetObject(attributeId, OpenMode.ForRead, false) is AttributeReference attributeReference)
            {
                AddText(
                    sink,
                    rawText: attributeReference.TextString,
                    entityType: nameof(AttributeReference),
                    layoutName: layoutName,
                    entityHandle: attributeReference.Handle.ToString(),
                    blockPath: blockPath,
                    position: TransformPoint(attributeReference.Position, parentTransform),
                    bbox: TryGetEntityBounds(attributeReference, parentTransform)
                );
            }
        }

        var blockHandle = blockReference.Handle.ToString();
        var blockName = ResolveBlockReferenceName(blockReference);
        if (!SafeCadAccess.TryRead(
                () => blockReference.BlockTableRecord,
                _trace,
                $"audit_block_reference.BlockTableRecord handle={blockHandle} name={blockName}",
                out var blockRecordId
            ))
        {
            return;
        }

        if (!SafeCadAccess.IsUsableObjectId(blockRecordId))
        {
            _trace.Log(
                $"[DOTNET][AUDIT][WARN] skip block_reference handle={blockHandle} name={blockName}: invalid_block_table_record"
            );
            return;
        }

        if (!SafeCadAccess.TryGetObject(
                tr,
                blockRecordId,
                OpenMode.ForRead,
                _trace,
                $"audit_block_definition block_handle={blockHandle} block_name={blockName}",
                out BlockTableRecord? record
            ))
        {
            return;
        }

        if (record is null)
        {
            return;
        }

        if (record.IsFromExternalReference)
        {
            _trace.Log($"[DOTNET][AUDIT][INFO] skip xref block={record.Name}");
            return;
        }

        var nextTransform = blockReference.BlockTransform * parentTransform;
        var nextPath = new List<string>(blockPath);
        if (!string.IsNullOrWhiteSpace(record.Name))
        {
            nextPath.Add(record.Name);
        }

        foreach (ObjectId nestedId in record)
        {
            if (!(tr.GetObject(nestedId, OpenMode.ForRead, false) is Entity nested))
            {
                continue;
            }

            ScanEntity(tr, nested, layoutName, nextPath, nextTransform, sink);
        }
    }

    private static void AddTableTexts(
        List<Dictionary<string, object>> sink,
        Table table,
        string layoutName,
        List<string> blockPath,
        Matrix3d transform
    )
    {
        var rows = table.Rows.Count;
        var cols = table.Columns.Count;
        for (var row = 0; row < rows; row++)
        {
            for (var col = 0; col < cols; col++)
            {
                string? text = null;
                try
                {
                    text = table.Cells[row, col].TextString;
                }
                catch
                {
                    try
                    {
                        text = table.Cells[row, col].Contents?.FirstOrDefault()?.Value?.ToString();
                    }
                    catch
                    {
                        text = null;
                    }
                }

                if (string.IsNullOrWhiteSpace(text))
                {
                    continue;
                }

                AddText(
                    sink,
                    rawText: text,
                    entityType: nameof(Table),
                    layoutName: layoutName,
                    entityHandle: table.Handle.ToString(),
                    blockPath: blockPath,
                    position: TryGetTableCellPosition(table, row, col, transform)
                );
            }
        }
    }

    private static void AddText(
        List<Dictionary<string, object>> sink,
        string? rawText,
        string entityType,
        string layoutName,
        string entityHandle,
        List<string> blockPath,
        Point3d? position,
        Dictionary<string, object>? bbox = null
    )
    {
        if (string.IsNullOrWhiteSpace(rawText))
        {
            return;
        }

        var text = rawText ?? string.Empty;

        var payload = new Dictionary<string, object>
        {
            ["raw_text"] = text,
            ["entity_type"] = entityType,
            ["layout_name"] = layoutName,
            ["entity_handle"] = entityHandle,
            ["block_path"] = string.Join(" > ", blockPath),
        };
        if (position.HasValue)
        {
            payload["position_x"] = position.Value.X;
            payload["position_y"] = position.Value.Y;
        }
        if (bbox is not null)
        {
            payload["bbox"] = bbox;
        }

        sink.Add(payload);
    }

    private static string ResolveLayoutName(BlockTableRecord record, Transaction tr)
    {
        try
        {
            if (!record.LayoutId.IsNull && tr.GetObject(record.LayoutId, OpenMode.ForRead, false) is Layout layout)
            {
                return layout.LayoutName;
            }
        }
        catch
        {
            // ignore and fall back to block table record name
        }

        return record.Name;
    }

    private static string ResolveBlockReferenceName(BlockReference blockReference)
    {
        try
        {
            return blockReference.Name ?? string.Empty;
        }
        catch
        {
            return string.Empty;
        }
    }

    private static Point3d TransformPoint(Point3d point, Matrix3d transform)
    {
        return point.TransformBy(transform);
    }

    private static Dictionary<string, object>? TryGetEntityBounds(Entity entity, Matrix3d transform)
    {
        try
        {
            var extents = entity.GeometricExtents;
            var points = new[]
            {
                new Point3d(extents.MinPoint.X, extents.MinPoint.Y, 0.0),
                new Point3d(extents.MaxPoint.X, extents.MinPoint.Y, 0.0),
                new Point3d(extents.MaxPoint.X, extents.MaxPoint.Y, 0.0),
                new Point3d(extents.MinPoint.X, extents.MaxPoint.Y, 0.0),
            }.Select(point => point.TransformBy(transform)).ToArray();
            var xs = points.Select(point => point.X).ToArray();
            var ys = points.Select(point => point.Y).ToArray();
            var xmin = xs.Min();
            var xmax = xs.Max();
            var ymin = ys.Min();
            var ymax = ys.Max();
            if (xmax <= xmin || ymax <= ymin)
            {
                return null;
            }
            return new Dictionary<string, object>
            {
                ["xmin"] = xmin,
                ["ymin"] = ymin,
                ["xmax"] = xmax,
                ["ymax"] = ymax,
            };
        }
        catch
        {
            return null;
        }
    }

    private static Point3d? TryGetLeaderPosition(MLeader leader, Matrix3d transform)
    {
        try
        {
            var mtextProperty = typeof(MLeader).GetProperty("MText", BindingFlags.Instance | BindingFlags.Public);
            var mtext = mtextProperty?.GetValue(leader);
            if (mtext is MText mt)
            {
                return mt.Location.TransformBy(transform);
            }
        }
        catch
        {
            // ignore
        }

        return null;
    }

    private static bool TryGetMLeaderText(MLeader leader, out string text)
    {
        text = string.Empty;
        try
        {
            var mtextProperty = typeof(MLeader).GetProperty("MText", BindingFlags.Instance | BindingFlags.Public);
            var mtext = mtextProperty?.GetValue(leader);
            if (mtext is MText mt && !string.IsNullOrWhiteSpace(mt.Contents))
            {
                text = mt.Contents;
                return true;
            }
        }
        catch
        {
            // ignore
        }

        return false;
    }

    private static Point3d? TryGetTableCellPosition(Table table, int row, int col, Matrix3d transform)
    {
        try
        {
            var extents = table.GeometricExtents;
            var rowHeight = Math.Max(1.0, table.Height / Math.Max(1, table.Rows.Count));
            var colWidth = Math.Max(1.0, table.Width / Math.Max(1, table.Columns.Count));
            var x = extents.MinPoint.X + (col + 0.5) * colWidth;
            var y = extents.MaxPoint.Y - (row + 0.5) * rowHeight;
            return new Point3d(x, y, 0.0).TransformBy(transform);
        }
        catch
        {
            return null;
        }
    }
}
