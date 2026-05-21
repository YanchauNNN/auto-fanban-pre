using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace Module5CadBridge;

internal sealed class RebarScanner
{
    private readonly BridgeTask _task;
    private readonly BridgeTraceLogger _trace;
    private readonly List<Dictionary<string, object>> _texts = new();
    private readonly List<Dictionary<string, object>> _circles = new();
    private readonly List<Dictionary<string, object>> _lines = new();
    private readonly List<Dictionary<string, object>> _debugSymbols = new();

    public RebarScanner(BridgeTask task, BridgeTraceLogger trace)
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
            if (!(tr.GetObject(recordId, OpenMode.ForRead) is BlockTableRecord record) || !record.IsLayout)
            {
                continue;
            }

            var layoutName = ResolveLayoutName(record, tr);
            foreach (ObjectId entityId in record)
            {
                if (tr.GetObject(entityId, OpenMode.ForRead, false) is Entity entity)
                {
                    ScanEntity(tr, entity, layoutName, new List<string>(), Matrix3d.Identity);
                }
            }
        }

        tr.Commit();
        result.AdditionalData["rebar_scan"] = new Dictionary<string, object>
        {
            ["circle_count"] = _circles.Count,
            ["line_count"] = _lines.Count,
            ["text_count"] = _texts.Count,
            ["debug_symbol_count"] = _debugSymbols.Count,
        };
        result.AdditionalData["rebar_circles"] = _circles;
        result.AdditionalData["rebar_lines"] = _lines;
        result.AdditionalData["rebar_texts"] = _texts;
        result.AdditionalData["rebar_debug_symbols"] = _debugSymbols;
        _trace.Log(
            $"[DOTNET][REBAR] circles={_circles.Count} lines={_lines.Count} texts={_texts.Count} source={_task.SourceDxf}"
        );
    }

    private void ScanEntity(
        Transaction tr,
        Entity entity,
        string layoutName,
        List<string> blockPath,
        Matrix3d transform
    )
    {
        switch (entity)
        {
            case Circle circle:
                AddCircle(circle, layoutName, blockPath, transform);
                return;
            case Line line:
                AddLine(line.Handle.ToString(), layoutName, blockPath, TransformPoint(line.StartPoint, transform), TransformPoint(line.EndPoint, transform), 0);
                return;
            case Autodesk.AutoCAD.DatabaseServices.Polyline polyline:
                AddPolylineSegments(polyline, layoutName, blockPath, transform);
                return;
            case AttributeDefinition attributeDefinition:
                AddText(
                    rawText: attributeDefinition.TextString,
                    entityType: nameof(AttributeDefinition),
                    layoutName: layoutName,
                    entityHandle: attributeDefinition.Handle.ToString(),
                    blockPath: blockPath,
                    position: TransformPoint(attributeDefinition.Position, transform),
                    bbox: TryGetEntityBounds(attributeDefinition, transform),
                    styleInfo: ReadTextStyle(tr, attributeDefinition.TextStyleId)
                );
                return;
            case AttributeReference attributeReference:
                AddText(
                    rawText: attributeReference.TextString,
                    entityType: nameof(AttributeReference),
                    layoutName: layoutName,
                    entityHandle: attributeReference.Handle.ToString(),
                    blockPath: blockPath,
                    position: TransformPoint(attributeReference.Position, transform),
                    bbox: TryGetEntityBounds(attributeReference, transform),
                    styleInfo: ReadTextStyle(tr, attributeReference.TextStyleId)
                );
                return;
            case DBText dbText:
                AddText(
                    rawText: dbText.TextString,
                    entityType: nameof(DBText),
                    layoutName: layoutName,
                    entityHandle: dbText.Handle.ToString(),
                    blockPath: blockPath,
                    position: TransformPoint(dbText.Position, transform),
                    bbox: TryGetEntityBounds(dbText, transform),
                    styleInfo: ReadTextStyle(tr, dbText.TextStyleId)
                );
                return;
            case MText mText:
                AddText(
                    rawText: mText.Text,
                    entityType: nameof(MText),
                    layoutName: layoutName,
                    entityHandle: mText.Handle.ToString(),
                    blockPath: blockPath,
                    position: TransformPoint(mText.Location, transform),
                    bbox: TryGetEntityBounds(mText, transform),
                    styleInfo: ReadTextStyle(tr, mText.TextStyleId)
                );
                return;
            case MLeader leader:
                AddLeaderText(tr, leader, layoutName, blockPath, transform);
                return;
            case BlockReference blockReference:
                ScanBlockReference(tr, blockReference, layoutName, blockPath, transform);
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
        Matrix3d parentTransform
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
                    rawText: attributeReference.TextString,
                    entityType: nameof(AttributeReference),
                    layoutName: layoutName,
                    entityHandle: attributeReference.Handle.ToString(),
                    blockPath: blockPath,
                    position: TransformPoint(attributeReference.Position, parentTransform),
                    bbox: TryGetEntityBounds(attributeReference, parentTransform),
                    styleInfo: ReadTextStyle(tr, attributeReference.TextStyleId)
                );
            }
        }

        var blockHandle = blockReference.Handle.ToString();
        var blockName = ResolveBlockReferenceName(blockReference);
        if (!SafeCadAccess.TryRead(
                () => blockReference.BlockTableRecord,
                _trace,
                $"rebar_block_reference.BlockTableRecord handle={blockHandle} name={blockName}",
                out var blockRecordId
            ))
        {
            return;
        }

        if (!SafeCadAccess.IsUsableObjectId(blockRecordId))
        {
            _trace.Log($"[DOTNET][REBAR][WARN] skip block_reference handle={blockHandle} name={blockName}: invalid_block_table_record");
            return;
        }

        if (!SafeCadAccess.TryGetObject(
                tr,
                blockRecordId,
                OpenMode.ForRead,
                _trace,
                $"rebar_block_definition block_handle={blockHandle} block_name={blockName}",
                out BlockTableRecord? record
            ) || record is null)
        {
            return;
        }

        if (record.IsFromExternalReference)
        {
            _trace.Log($"[DOTNET][REBAR][INFO] skip xref block={record.Name}");
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
            if (tr.GetObject(nestedId, OpenMode.ForRead, false) is Entity nested)
            {
                ScanEntity(tr, nested, layoutName, nextPath, nextTransform);
            }
        }
    }

    private void AddCircle(Circle circle, string layoutName, List<string> blockPath, Matrix3d transform)
    {
        var center = TransformPoint(circle.Center, transform);
        var radiusPoint = TransformPoint(new Point3d(circle.Center.X + circle.Radius, circle.Center.Y, circle.Center.Z), transform);
        var radius = center.DistanceTo(radiusPoint);
        _circles.Add(new Dictionary<string, object>
        {
            ["handle"] = circle.Handle.ToString(),
            ["layout_name"] = layoutName,
            ["block_path"] = string.Join(" > ", blockPath),
            ["center"] = PointToDictionary(center),
            ["radius"] = radius,
            ["bbox"] = new Dictionary<string, object>
            {
                ["xmin"] = center.X - radius,
                ["ymin"] = center.Y - radius,
                ["xmax"] = center.X + radius,
                ["ymax"] = center.Y + radius,
            },
        });
    }

    private void AddPolylineSegments(
        Autodesk.AutoCAD.DatabaseServices.Polyline polyline,
        string layoutName,
        List<string> blockPath,
        Matrix3d transform
    )
    {
        var vertexCount = polyline.NumberOfVertices;
        for (var index = 0; index < vertexCount - 1; index++)
        {
            var start = TransformPoint(polyline.GetPoint3dAt(index), transform);
            var end = TransformPoint(polyline.GetPoint3dAt(index + 1), transform);
            AddLine(polyline.Handle.ToString(), layoutName, blockPath, start, end, index);
        }

        if (polyline.Closed && vertexCount > 2)
        {
            var start = TransformPoint(polyline.GetPoint3dAt(vertexCount - 1), transform);
            var end = TransformPoint(polyline.GetPoint3dAt(0), transform);
            AddLine(polyline.Handle.ToString(), layoutName, blockPath, start, end, vertexCount - 1);
        }
    }

    private void AddLine(
        string handle,
        string layoutName,
        List<string> blockPath,
        Point3d start,
        Point3d end,
        int segmentIndex
    )
    {
        var length = start.DistanceTo(end);
        if (length <= 1e-9)
        {
            return;
        }

        var angle = Math.Atan2(end.Y - start.Y, end.X - start.X) * 180.0 / Math.PI;
        _lines.Add(new Dictionary<string, object>
        {
            ["handle"] = segmentIndex > 0 ? $"{handle}:{segmentIndex.ToString(CultureInfo.InvariantCulture)}" : handle,
            ["layout_name"] = layoutName,
            ["block_path"] = string.Join(" > ", blockPath),
            ["start"] = PointToDictionary(start),
            ["end"] = PointToDictionary(end),
            ["angle_degrees"] = angle,
            ["length"] = length,
        });
    }

    private void AddLeaderText(
        Transaction tr,
        MLeader leader,
        string layoutName,
        List<string> blockPath,
        Matrix3d transform
    )
    {
        try
        {
            var mtextProperty = typeof(MLeader).GetProperty("MText", BindingFlags.Instance | BindingFlags.Public);
            var mtext = mtextProperty?.GetValue(leader);
            if (mtext is MText mt && !string.IsNullOrWhiteSpace(mt.Contents))
            {
                AddText(
                    rawText: mt.Contents,
                    entityType: nameof(MLeader),
                    layoutName: layoutName,
                    entityHandle: leader.Handle.ToString(),
                    blockPath: blockPath,
                    position: TransformPoint(mt.Location, transform),
                    bbox: TryGetEntityBounds(leader, transform),
                    styleInfo: ReadTextStyle(tr, mt.TextStyleId)
                );
            }
        }
        catch
        {
            // MLeader text APIs vary between AutoCAD versions; skip unreadable leaders.
        }
    }

    private void AddText(
        string? rawText,
        string entityType,
        string layoutName,
        string entityHandle,
        List<string> blockPath,
        Point3d position,
        Dictionary<string, object>? bbox,
        TextStyleInfo styleInfo
    )
    {
        if (string.IsNullOrWhiteSpace(rawText))
        {
            return;
        }

        var text = rawText ?? string.Empty;
        var codepoints = ToCodepoints(text);
        var payload = new Dictionary<string, object>
        {
            ["handle"] = entityHandle,
            ["entity_handle"] = entityHandle,
            ["raw_text"] = text,
            ["entity_type"] = entityType,
            ["layout_name"] = layoutName,
            ["block_path"] = string.Join(" > ", blockPath),
            ["position"] = PointToDictionary(position),
            ["position_x"] = position.X,
            ["position_y"] = position.Y,
            ["text_style"] = styleInfo.StyleName,
            ["font"] = styleInfo.FontFile,
            ["bigfont"] = styleInfo.BigFontFile,
            ["codepoints"] = codepoints,
        };
        if (bbox is not null)
        {
            payload["bbox"] = bbox;
        }

        _texts.Add(payload);
        if (ContainsDebugSymbol(text))
        {
            _debugSymbols.Add(new Dictionary<string, object>
            {
                ["handle"] = entityHandle,
                ["raw_text"] = text,
                ["codepoints"] = codepoints,
                ["text_style"] = styleInfo.StyleName,
                ["font"] = styleInfo.FontFile,
                ["bigfont"] = styleInfo.BigFontFile,
            });
        }
    }

    private static bool ContainsDebugSymbol(string text)
    {
        foreach (var ch in text)
        {
            var codepoint = (int)ch;
            if (codepoint == 0x0085 || (codepoint >= 0xE000 && codepoint <= 0xF8FF))
            {
                return true;
            }
        }

        return false;
    }

    private TextStyleInfo ReadTextStyle(Transaction tr, ObjectId styleId)
    {
        if (styleId.IsNull || styleId.IsErased)
        {
            return TextStyleInfo.Empty;
        }

        try
        {
            if (tr.GetObject(styleId, OpenMode.ForRead, false) is TextStyleTableRecord style)
            {
                return new TextStyleInfo(
                    style.Name ?? string.Empty,
                    style.FileName ?? string.Empty,
                    style.BigFontFileName ?? string.Empty
                );
            }
        }
        catch
        {
            // Best-effort metadata only.
        }

        return TextStyleInfo.Empty;
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

    private static Dictionary<string, object> PointToDictionary(Point3d point)
    {
        return new Dictionary<string, object> { ["x"] = point.X, ["y"] = point.Y, ["z"] = point.Z };
    }

    private static List<string> ToCodepoints(string text)
    {
        var result = new List<string>();
        for (var index = 0; index < text.Length; index++)
        {
            var codepoint = char.ConvertToUtf32(text, index);
            if (char.IsHighSurrogate(text[index]))
            {
                index++;
            }
            result.Add($"U+{codepoint:X4}");
        }

        return result;
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

    private readonly struct TextStyleInfo
    {
        public static TextStyleInfo Empty => new(string.Empty, string.Empty, string.Empty);

        public TextStyleInfo(string styleName, string fontFile, string bigFontFile)
        {
            StyleName = styleName;
            FontFile = fontFile;
            BigFontFile = bigFontFile;
        }

        public string StyleName { get; }
        public string FontFile { get; }
        public string BigFontFile { get; }
    }
}
