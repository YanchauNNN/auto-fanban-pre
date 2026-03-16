using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace Module5CadBridge;

internal sealed class TitleblockConsistencyFixer
{
    private readonly BridgeTask _task;
    private readonly BridgeTraceLogger _trace;

    public TitleblockConsistencyFixer(BridgeTask task, BridgeTraceLogger trace)
    {
        _task = task;
        _trace = trace;
    }

    public void Execute(BridgeResultEnvelope result)
    {
        if (string.IsNullOrWhiteSpace(_task.OutputDwg))
        {
            result.Errors.Add("TITLEBLOCK_CONSISTENCY_OUTPUT_DWG_MISSING");
            return;
        }

        using var db = new Database(false, true);
        db.ReadDwgFile(_task.SourceDxf, FileShare.ReadWrite, true, string.Empty);
        db.CloseInput(true);

        var matcher = new ConsistencyPatchMatcher(_task.ConsistencyActions, _trace);

        using (var tr = db.TransactionManager.StartTransaction())
        {
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

                foreach (ObjectId entityId in record)
                {
                    if (!(tr.GetObject(entityId, OpenMode.ForRead, false) is Entity entity))
                    {
                        continue;
                    }

                    PatchEntity(
                        tr,
                        entity,
                        Matrix3d.Identity,
                        matcher
                    );
                }
            }

            tr.Commit();
        }

        matcher.AppendErrors(result.Errors);

        var outputDir = Path.GetDirectoryName(_task.OutputDwg);
        if (!string.IsNullOrWhiteSpace(outputDir))
        {
            Directory.CreateDirectory(outputDir);
        }

        db.SaveAs(_task.OutputDwg, DwgVersion.Current);
        _trace.Log(
            $"[DOTNET][CONSISTENCY] patched={matcher.PatchedCount} unmatched={matcher.UnmatchedCount} output={_task.OutputDwg}"
        );
    }

    private void PatchEntity(
        Transaction tr,
        Entity entity,
        Matrix3d transform,
        ConsistencyPatchMatcher matcher
    )
    {
        switch (entity)
        {
            case DBText dbText:
                matcher.TryPatch(
                    text: dbText.TextString,
                    position: TransformPoint(dbText.Position, transform),
                    apply: newText =>
                    {
                        EnsureWriteEnabled(dbText);
                        dbText.TextString = newText;
                    }
                );
                return;
            case MText mText:
                matcher.TryPatch(
                    text: mText.Text,
                    position: TransformPoint(mText.Location, transform),
                    apply: newText =>
                    {
                        EnsureWriteEnabled(mText);
                        mText.Contents = newText;
                    }
                );
                return;
            case Dimension dimension when !string.IsNullOrWhiteSpace(dimension.DimensionText)
                                         && !dimension.DimensionText.Equals("<>", StringComparison.Ordinal):
                matcher.TryPatch(
                    text: dimension.DimensionText,
                    position: TransformPoint(dimension.TextPosition, transform),
                    apply: newText =>
                    {
                        EnsureWriteEnabled(dimension);
                        dimension.DimensionText = newText;
                    }
                );
                return;
            case BlockReference blockReference:
                PatchBlockReference(tr, blockReference, transform, matcher);
                return;
            default:
                return;
        }
    }

    private void PatchBlockReference(
        Transaction tr,
        BlockReference blockReference,
        Matrix3d parentTransform,
        ConsistencyPatchMatcher matcher
    )
    {
        foreach (ObjectId attributeId in blockReference.AttributeCollection)
        {
            if (attributeId.IsNull || attributeId.IsErased)
            {
                continue;
            }

            if (!(tr.GetObject(attributeId, OpenMode.ForRead, false) is AttributeReference attributeReference))
            {
                continue;
            }

            matcher.TryPatch(
                text: attributeReference.TextString,
                position: TransformPoint(attributeReference.Position, parentTransform),
                apply: newText =>
                {
                    EnsureWriteEnabled(attributeReference);
                    attributeReference.TextString = newText;
                    TryUpdateMTextAttribute(attributeReference, newText);
                }
            );
        }

        if (!(tr.GetObject(blockReference.BlockTableRecord, OpenMode.ForRead) is BlockTableRecord record))
        {
            return;
        }

        if (record.IsFromExternalReference)
        {
            _trace.Log($"[DOTNET][CONSISTENCY][INFO] skip xref block={record.Name}");
            return;
        }

        var nextTransform = blockReference.BlockTransform * parentTransform;
        foreach (ObjectId nestedId in record)
        {
            if (!(tr.GetObject(nestedId, OpenMode.ForRead, false) is Entity nested))
            {
                continue;
            }

            PatchEntity(tr, nested, nextTransform, matcher);
        }
    }

    private static void TryUpdateMTextAttribute(AttributeReference attributeReference, string newText)
    {
        try
        {
            var mtext = attributeReference.MTextAttribute;
            if (mtext == null)
            {
                return;
            }

            mtext.Contents = newText;
            attributeReference.UpdateMTextAttribute();
        }
        catch
        {
            // Fall back to TextString only when MText sync is unavailable.
        }
    }

    private static void EnsureWriteEnabled(DBObject obj)
    {
        if (!obj.IsWriteEnabled)
        {
            obj.UpgradeOpen();
        }
    }

    private static Point3d TransformPoint(Point3d point, Matrix3d transform)
    {
        return point.TransformBy(transform);
    }
}

internal sealed class ConsistencyPatchMatcher
{
    private const double MatchTolerance = 3.0;

    private readonly List<PatchTargetState> _targets;
    private readonly BridgeTraceLogger _trace;

    public ConsistencyPatchMatcher(
        IEnumerable<BridgeConsistencyAction> actions,
        BridgeTraceLogger trace
    )
    {
        _trace = trace;
        _targets = actions
            .SelectMany(action => action.Targets.Select(target => new PatchTargetState(action, target)))
            .ToList();
    }

    public int PatchedCount => _targets.Count(target => target.Matched);
    public int UnmatchedCount => _targets.Count(target => !target.Matched);

    public void TryPatch(string? text, Point3d position, Action<string> apply)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return;
        }

        var normalizedText = Normalize(text);
        if (string.IsNullOrWhiteSpace(normalizedText))
        {
            return;
        }

        PatchTargetState? best = null;
        var bestDistance = double.MaxValue;
        foreach (var target in _targets)
        {
            if (target.Matched)
            {
                continue;
            }

            if (!Normalize(target.Target.OldText).Equals(normalizedText, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            if (!target.Action.RoiBBox.Contains(position))
            {
                continue;
            }

            var distance = Distance(position, target.Target.X, target.Target.Y);
            if (distance > MatchTolerance || distance >= bestDistance)
            {
                continue;
            }

            best = target;
            bestDistance = distance;
        }

        if (best == null)
        {
            return;
        }

        apply(best.Target.NewText);
        best.Matched = true;
        _trace.Log(
            $"[DOTNET][CONSISTENCY][PATCH] field={best.Action.FieldName} old={best.Target.OldText} new={best.Target.NewText} x={position.X:F3} y={position.Y:F3}"
        );
    }

    public void AppendErrors(List<string> sink)
    {
        foreach (var target in _targets.Where(target => !target.Matched))
        {
            sink.Add(
                $"TITLEBLOCK_CONSISTENCY_UNMATCHED:{target.Action.FieldName}:{target.Target.OldText}->{target.Target.NewText}@({target.Target.X:F3},{target.Target.Y:F3})"
            );
        }
    }

    private static string Normalize(string? value)
    {
        return string.Concat((value ?? string.Empty).Where(ch => !char.IsWhiteSpace(ch)));
    }

    private static double Distance(Point3d point, double x, double y)
    {
        var dx = point.X - x;
        var dy = point.Y - y;
        return Math.Sqrt(dx * dx + dy * dy);
    }

    private sealed class PatchTargetState
    {
        public PatchTargetState(BridgeConsistencyAction action, BridgeConsistencyTarget target)
        {
            Action = action;
            Target = target;
        }

        public BridgeConsistencyAction Action { get; }
        public BridgeConsistencyTarget Target { get; }
        public bool Matched { get; set; }
    }
}

internal static class BridgeBBoxExtensions
{
    public static bool Contains(this BridgeBBox bbox, Point3d point)
    {
        return point.X >= bbox.Xmin
               && point.X <= bbox.Xmax
               && point.Y >= bbox.Ymin
               && point.Y <= bbox.Ymax;
    }
}
