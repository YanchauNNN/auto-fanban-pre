using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace Module5CadBridge;

internal sealed class FactoryIndexMapReplacer
{
    private readonly BridgeTask _task;
    private readonly BridgeTraceLogger _trace;

    public FactoryIndexMapReplacer(BridgeTask task, BridgeTraceLogger trace)
    {
        _task = task;
        _trace = trace;
    }

    public void Execute(BridgeResultEnvelope result)
    {
        if (string.IsNullOrWhiteSpace(_task.OutputDwg))
        {
            result.Errors.Add("FACTORY_INDEX_OUTPUT_DWG_MISSING");
            return;
        }

        var config = _task.FactoryIndexMap;
        if (!config.Enabled || config.Actions.Count == 0)
        {
            result.Errors.Add("FACTORY_INDEX_NO_ACTIONS");
            return;
        }

        if (string.IsNullOrWhiteSpace(config.TargetTemplateDwg) || !File.Exists(config.TargetTemplateDwg))
        {
            result.Errors.Add($"FACTORY_INDEX_TEMPLATE_MISSING:{config.TargetTemplateDwg}");
            return;
        }

        using var db = new Database(false, true);
        db.ReadDwgFile(_task.SourceDxf, FileShare.ReadWrite, true, string.Empty);
        db.CloseInput(true);

        var blockName = $"FANBAN_FACTORY_INDEX_{config.TargetProjectNo}_{DateTime.Now:yyyyMMddHHmmssfff}";
        var importedBlockId = ImportTemplateBlock(db, config.TargetTemplateDwg, blockName);

        var applied = 0;
        var deleted = 0;
        var unmatched = 0;
        var explodedDimensions = 0;
        using (var tr = db.TransactionManager.StartTransaction())
        {
            explodedDimensions = ExplodeDimensionsInBlockDefinition(tr, importedBlockId);
            var targetExtents = MeasureBlockDefinitionExtents(db, tr, importedBlockId);
            var targetCenter = ExtentsCenter(targetExtents);
            var targetWidth = Math.Max(0.0, targetExtents.MaxPoint.X - targetExtents.MinPoint.X);
            var targetHeight = Math.Max(0.0, targetExtents.MaxPoint.Y - targetExtents.MinPoint.Y);
            foreach (var action in config.Actions)
            {
                var oldReference = FindOldReference(db, tr, action);
                if (oldReference == null)
                {
                    unmatched++;
                    _trace.Log($"[DOTNET][FACTORY_INDEX][WARN] old reference not found action={action.ActionId}");
                    continue;
                }

                var ownerId = oldReference.OwnerId;
                var oldExtents = oldReference.GeometricExtents;
                var oldExtentsCenter = ExtentsCenter(oldExtents);
                var hasSourceBounds = action.SourceBounds.Width > 0.0 && action.SourceBounds.Height > 0.0;
                var oldCenter = hasSourceBounds
                    ? action.SourceBounds.Center
                    : new BridgePoint(oldExtentsCenter.X, oldExtentsCenter.Y);
                var oldWidth = hasSourceBounds
                    ? action.SourceBounds.Width
                    : Math.Max(0.0, oldExtents.MaxPoint.X - oldExtents.MinPoint.X);
                var oldHeight = hasSourceBounds
                    ? action.SourceBounds.Height
                    : Math.Max(0.0, oldExtents.MaxPoint.Y - oldExtents.MinPoint.Y);
                var effectiveTargetWidth = Math.Max(targetWidth, action.TargetBounds.Width);
                var effectiveTargetHeight = Math.Max(targetHeight, action.TargetBounds.Height);
                var effectiveTargetCenter = new BridgePoint(
                    action.TargetBounds.Width >= targetWidth && action.TargetBounds.Width > 0.0
                        ? action.TargetBounds.Center.X
                        : targetCenter.X,
                    action.TargetBounds.Height >= targetHeight && action.TargetBounds.Height > 0.0
                        ? action.TargetBounds.Center.Y
                        : targetCenter.Y
                );
                if (oldWidth <= 0.0 || oldHeight <= 0.0 || effectiveTargetWidth <= 0.0 || effectiveTargetHeight <= 0.0)
                {
                    unmatched++;
                    _trace.Log(
                        $"[DOTNET][FACTORY_INDEX][WARN] invalid bbox action={action.ActionId} oldWidth={oldWidth} oldHeight={oldHeight} targetWidth={effectiveTargetWidth} targetHeight={effectiveTargetHeight}"
                    );
                    continue;
                }

                if (!oldReference.IsWriteEnabled)
                {
                    oldReference.UpgradeOpen();
                }
                oldReference.Erase();
                deleted++;

                if (!(tr.GetObject(ownerId, OpenMode.ForWrite, false) is BlockTableRecord ownerRecord))
                {
                    unmatched++;
                    _trace.Log($"[DOTNET][FACTORY_INDEX][WARN] owner record unavailable action={action.ActionId}");
                    continue;
                }

                var scale = Math.Min(oldWidth / effectiveTargetWidth, oldHeight / effectiveTargetHeight);
                var insertion = new Point3d(
                    oldCenter.X - effectiveTargetCenter.X * scale,
                    oldCenter.Y - effectiveTargetCenter.Y * scale,
                    0.0
                );
                var newReference = new BlockReference(insertion, importedBlockId)
                {
                    ScaleFactors = new Scale3d(scale)
                };
                ownerRecord.AppendEntity(newReference);
                tr.AddNewlyCreatedDBObject(newReference, true);
                applied++;
            }

            tr.Commit();
        }

        var outputDir = Path.GetDirectoryName(_task.OutputDwg);
        if (!string.IsNullOrWhiteSpace(outputDir))
        {
            Directory.CreateDirectory(outputDir);
        }

        var saveVersion = DwgVersionResolver.Resolve(
            _task.SourceDwgVersion,
            db.OriginalFileVersion
        );
        db.SaveAs(_task.OutputDwg, saveVersion);

        result.AdditionalData["factory_index_map"] = new Dictionary<string, object>
        {
            ["applied_count"] = applied,
            ["deleted_count"] = deleted,
            ["unmatched_count"] = unmatched,
            ["scale_mode"] = "fit_source_detected_block_bbox_uniform",
            ["template_block_name"] = blockName,
            ["exploded_dimension_count"] = explodedDimensions,
        };
        _trace.Log(
            $"[DOTNET][FACTORY_INDEX] applied={applied} deleted={deleted} unmatched={unmatched} output={_task.OutputDwg}"
        );
    }

    private static ObjectId ImportTemplateBlock(Database targetDb, string templateDwg, string blockName)
    {
        using var templateDb = new Database(false, true);
        templateDb.ReadDwgFile(templateDwg, FileShare.Read, true, string.Empty);
        templateDb.CloseInput(true);
        return targetDb.Insert(blockName, templateDb, false);
    }

    private static int ExplodeDimensionsInBlockDefinition(Transaction tr, ObjectId blockId)
    {
        var blockRecord = (BlockTableRecord)tr.GetObject(blockId, OpenMode.ForWrite);
        var dimensionIds = new List<ObjectId>();
        foreach (ObjectId entityId in blockRecord)
        {
            if (tr.GetObject(entityId, OpenMode.ForRead, false) is Dimension)
            {
                dimensionIds.Add(entityId);
            }
        }

        var explodedCount = 0;
        foreach (var dimensionId in dimensionIds)
        {
            if (!(tr.GetObject(dimensionId, OpenMode.ForWrite, false) is Dimension dimension))
            {
                continue;
            }

            var exploded = new DBObjectCollection();
            try
            {
                dimension.Explode(exploded);
            }
            catch
            {
                continue;
            }

            foreach (DBObject item in exploded)
            {
                if (item is Entity entity)
                {
                    blockRecord.AppendEntity(entity);
                    tr.AddNewlyCreatedDBObject(entity, true);
                }
                else
                {
                    item.Dispose();
                }
            }

            dimension.Erase();
            explodedCount++;
        }

        return explodedCount;
    }

    private static BlockReference? FindOldReference(
        Database db,
        Transaction tr,
        BridgeFactoryIndexAction action
    )
    {
        var byHandle = FindBlockReferenceByHandle(db, tr, action.SourceInsertHandle);
        if (byHandle != null)
        {
            return byHandle;
        }

        if (string.IsNullOrWhiteSpace(action.SourceBlockName))
        {
            return null;
        }

        var candidates = new List<Tuple<double, BlockReference>>();
        var blockTable = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
        foreach (ObjectId recordId in blockTable)
        {
            if (!(tr.GetObject(recordId, OpenMode.ForRead) is BlockTableRecord record) || !record.IsLayout)
            {
                continue;
            }

            foreach (ObjectId entityId in record)
            {
                if (!(tr.GetObject(entityId, OpenMode.ForRead, false) is BlockReference reference))
                {
                    continue;
                }

                var name = GetBlockName(tr, reference);
                if (!string.Equals(name, action.SourceBlockName, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                var distance = action.SourceInsertPoint == null
                    ? 0.0
                    : Distance(reference.Position, action.SourceInsertPoint);
                candidates.Add(Tuple.Create(distance, reference));
            }
        }

        return candidates.OrderBy(item => item.Item1).Select(item => item.Item2).FirstOrDefault();
    }

    private static BlockReference? FindBlockReferenceByHandle(
        Database db,
        Transaction tr,
        string handleText
    )
    {
        if (string.IsNullOrWhiteSpace(handleText))
        {
            return null;
        }

        try
        {
            var handleValue = Convert.ToInt64(handleText, 16);
            var id = db.GetObjectId(false, new Handle(handleValue), 0);
            if (id.IsNull || id.IsErased)
            {
                return null;
            }

            return tr.GetObject(id, OpenMode.ForRead, false) as BlockReference;
        }
        catch
        {
            return null;
        }
    }

    private static string GetBlockName(Transaction tr, BlockReference reference)
    {
        try
        {
            var record = (BlockTableRecord)tr.GetObject(reference.BlockTableRecord, OpenMode.ForRead);
            return record.Name;
        }
        catch
        {
            return string.Empty;
        }
    }

    private static double Distance(Point3d point, BridgePoint target)
    {
        var dx = point.X - target.X;
        var dy = point.Y - target.Y;
        return Math.Sqrt(dx * dx + dy * dy);
    }

    private static Point3d ExtentsCenter(Extents3d extents)
    {
        return new Point3d(
            (extents.MinPoint.X + extents.MaxPoint.X) / 2.0,
            (extents.MinPoint.Y + extents.MaxPoint.Y) / 2.0,
            (extents.MinPoint.Z + extents.MaxPoint.Z) / 2.0
        );
    }

    private static Extents3d MeasureBlockDefinitionExtents(
        Database db,
        Transaction tr,
        ObjectId blockId
    )
    {
        var blockRecord = (BlockTableRecord)tr.GetObject(blockId, OpenMode.ForRead);
        var hasExtents = false;
        var merged = new Extents3d();
        foreach (ObjectId entityId in blockRecord)
        {
            if (!(tr.GetObject(entityId, OpenMode.ForRead, false) is Entity entity))
            {
                continue;
            }

            try
            {
                var entityExtents = entity.GeometricExtents;
                if (!hasExtents)
                {
                    merged = entityExtents;
                    hasExtents = true;
                }
                else
                {
                    merged.AddExtents(entityExtents);
                }
            }
            catch
            {
                // Some imported proxy/annotation entities may not expose extents.
            }
        }

        if (hasExtents)
        {
            return merged;
        }

        var blockTable = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
        var modelSpace = (BlockTableRecord)tr.GetObject(
            blockTable[BlockTableRecord.ModelSpace],
            OpenMode.ForWrite
        );
        var tempReference = new BlockReference(Point3d.Origin, blockId);
        modelSpace.AppendEntity(tempReference);
        tr.AddNewlyCreatedDBObject(tempReference, true);
        var fallbackExtents = tempReference.GeometricExtents;
        tempReference.Erase();
        return fallbackExtents;
    }
}

internal sealed class BridgeFactoryIndexMapConfig
{
    public bool Enabled { get; private set; }
    public string SourceProjectNo { get; private set; } = string.Empty;
    public string TargetProjectNo { get; private set; } = string.Empty;
    public string TargetTemplateDwg { get; private set; } = string.Empty;
    public List<BridgeFactoryIndexAction> Actions { get; private set; } = new();

    public static BridgeFactoryIndexMapConfig FromObject(object? obj)
    {
        var data = BridgeValue.AsDictionary(obj);
        if (data == null)
        {
            return new BridgeFactoryIndexMapConfig();
        }

        var config = new BridgeFactoryIndexMapConfig
        {
            Enabled = BridgeValue.GetBool(data, "enabled", false),
            SourceProjectNo = BridgeValue.GetString(data, "source_project_no", string.Empty),
            TargetProjectNo = BridgeValue.GetString(data, "target_project_no", string.Empty),
            TargetTemplateDwg = BridgeValue.GetString(data, "target_template_dwg", string.Empty),
        };

        foreach (var item in BridgeValue.AsObjectEnumerable(data.TryGetValue("actions", out var actionsObj) ? actionsObj : null))
        {
            var actionDict = BridgeValue.AsDictionary(item);
            if (actionDict != null)
            {
                config.Actions.Add(BridgeFactoryIndexAction.FromDictionary(actionDict));
            }
        }

        return config;
    }
}

internal sealed class BridgeFactoryIndexAction
{
    public string ActionId { get; private set; } = string.Empty;
    public string Layout { get; private set; } = string.Empty;
    public string SourceAngleKey { get; private set; } = string.Empty;
    public string TargetAngleKey { get; private set; } = string.Empty;
    public BridgePoint SourceCompassCenter { get; private set; } = new(0.0, 0.0);
    public double SourceCompassRadius { get; private set; }
    public BridgePoint TargetCompassCenter { get; private set; } = new(0.0, 0.0);
    public double TargetCompassRadius { get; private set; }
    public BridgeBBox SourceBounds { get; private set; } = BridgeBBox.Empty;
    public BridgeBBox TargetBounds { get; private set; } = BridgeBBox.Empty;
    public string SourceBlockName { get; private set; } = string.Empty;
    public string SourceInsertHandle { get; private set; } = string.Empty;
    public BridgePoint? SourceInsertPoint { get; private set; }

    public double Scale => TargetCompassRadius > 0.0 ? SourceCompassRadius / TargetCompassRadius : 1.0;

    public static BridgeFactoryIndexAction FromDictionary(Dictionary<string, object> data)
    {
        return new BridgeFactoryIndexAction
        {
            ActionId = BridgeValue.GetString(data, "action_id", string.Empty),
            Layout = BridgeValue.GetString(data, "layout", string.Empty),
            SourceAngleKey = BridgeValue.GetString(data, "source_angle_key", string.Empty),
            TargetAngleKey = BridgeValue.GetString(data, "target_angle_key", string.Empty),
            SourceCompassCenter = ReadPoint(data, "source_compass_center"),
            SourceCompassRadius = BridgeValue.GetDouble(data, "source_compass_radius", 0.0),
            TargetCompassCenter = ReadPoint(data, "target_compass_center"),
            TargetCompassRadius = BridgeValue.GetDouble(data, "target_compass_radius", 0.0),
            SourceBounds = BridgeBBox.FromObject(data.TryGetValue("source_bounds", out var sourceBoundsObj) ? sourceBoundsObj : null),
            TargetBounds = BridgeBBox.FromObject(data.TryGetValue("target_bounds", out var targetBoundsObj) ? targetBoundsObj : null),
            SourceBlockName = BridgeValue.GetString(data, "source_block_name", string.Empty),
            SourceInsertHandle = BridgeValue.GetString(data, "source_insert_handle", string.Empty),
            SourceInsertPoint = ReadOptionalPoint(data, "source_insert_point"),
        };
    }

    private static BridgePoint ReadPoint(Dictionary<string, object> data, string key)
    {
        return ReadOptionalPoint(data, key) ?? new BridgePoint(0.0, 0.0);
    }

    private static BridgePoint? ReadOptionalPoint(Dictionary<string, object> data, string key)
    {
        if (!data.TryGetValue(key, out var value))
        {
            return null;
        }

        var dict = BridgeValue.AsDictionary(value);
        if (dict != null)
        {
            return new BridgePoint(
                BridgeValue.GetDouble(dict, "x", 0.0),
                BridgeValue.GetDouble(dict, "y", 0.0)
            );
        }

        var list = BridgeValue.AsObjectList(value);
        if (list.Count >= 2)
        {
            return new BridgePoint(
                BridgeValue.ToDouble(list[0], 0.0),
                BridgeValue.ToDouble(list[1], 0.0)
            );
        }

        return null;
    }
}
