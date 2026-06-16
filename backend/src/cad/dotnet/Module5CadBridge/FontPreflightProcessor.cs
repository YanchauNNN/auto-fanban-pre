using System;
using System.Collections.Generic;
using System.Drawing.Text;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.GraphicsInterface;
using Autodesk.AutoCAD.Geometry;

namespace Module5CadBridge;

internal sealed class FontPreflightProcessor
{
    private static readonly Dictionary<string, string[]> TrueTypeFileAliases = new(StringComparer.OrdinalIgnoreCase)
    {
        ["simsun.ttf"] = new[] { "simsun.ttc" },
    };

    private readonly BridgeTask _task;
    private readonly BridgeTraceLogger _trace;
    private readonly HashSet<string> _installedFontFiles;
    private readonly HashSet<string> _installedFamilies;
    private readonly Dictionary<string, string> _installedFamilyMap;
    private readonly List<string> _autocadFontDirs;
    private int _skippedInvalidObjectCount;

    public FontPreflightProcessor(BridgeTask task, BridgeTraceLogger trace)
    {
        _task = task;
        _trace = trace;
        _installedFontFiles = LoadInstalledFontFiles();
        _installedFamilies = LoadInstalledFontFamilies();
        _installedFamilyMap = LoadInstalledFamilyMap();
        _autocadFontDirs = LoadAutoCADFontDirs();
    }

    public void Execute(BridgeResultEnvelope result)
    {
        using var db = new Database(false, true);
        db.ReadDwgFile(_task.SourceDxf, FileShare.ReadWrite, true, string.Empty);
        db.CloseInput(true);

        Dictionary<ObjectId, FontStyleUsage> usageByStyle;
        var missingFonts = new List<Dictionary<string, object>>();
        var replacedStyleCount = 0;
        var replacedEntityCount = 0;
        var emptyStyleStylePatchedCount = 0;
        var emptyStyleSharedSkippedCount = 0;
        var emptyStyleSharedStyles = new List<string>();
        var emptyStyleGlobalReplacedCount = 0;
        var detectedStyleCount = 0;
        var replaceMissing = _task.WorkflowStage.Equals("font_replace_missing", StringComparison.OrdinalIgnoreCase);
        var targetByStyleName = BuildReplacementTargetMap(_task.ReplacementTargets);

        using (var tr = db.TransactionManager.StartTransaction())
        {
            usageByStyle = CollectStyleUsage(db, tr);
            var styleTable = (TextStyleTable)tr.GetObject(db.TextStyleTableId, OpenMode.ForRead);
            foreach (ObjectId styleId in styleTable)
            {
                detectedStyleCount += 1;
                if (!(tr.GetObject(styleId, replaceMissing ? OpenMode.ForWrite : OpenMode.ForRead) is TextStyleTableRecord styleRecord))
                {
                    continue;
                }

                if (!usageByStyle.TryGetValue(styleId, out var usage) || !usage.IsUsed)
                {
                    continue;
                }

                var styleName = styleRecord.Name ?? string.Empty;
                var hasExplicitTarget = targetByStyleName.TryGetValue(styleName, out var explicitTarget);
                var compatibilityMatch = ResolveCompatibilityMatch(styleRecord);
                var hasCompatibilityTarget = compatibilityMatch != null;
                if (!hasExplicitTarget && !hasCompatibilityTarget && !IsStyleMissing(styleRecord, db))
                {
                    continue;
                }

                if (!replaceMissing)
                {
                    missingFonts.Add(BuildMissingFontPayload(styleRecord, usage));
                    continue;
                }

                if (string.IsNullOrWhiteSpace(_task.ReplacementFont))
                {
                    // legacy single-font flow may still be empty; kind-specific mapping is preferred
                }

                EnsureWriteEnabled(styleRecord);
                var replacementKind = hasCompatibilityTarget
                    ? compatibilityMatch!.Kind
                    : hasExplicitTarget
                        ? explicitTarget.Kind
                        : DetectKind(styleRecord.FileName ?? string.Empty, styleRecord.BigFontFileName ?? string.Empty);
                var replacementFont = hasCompatibilityTarget
                    ? compatibilityMatch!.ReplacementFont
                    : ResolveReplacementFont(replacementKind);
                if (string.IsNullOrWhiteSpace(replacementFont))
                {
                    result.Errors.Add($"FONT_REPLACEMENT_FONT_MISSING:{replacementKind}");
                    continue;
                }
                if (replacementKind.Equals("bigfont", StringComparison.OrdinalIgnoreCase))
                {
                    styleRecord.BigFontFileName = replacementFont;
                }
                else
                {
                    styleRecord.FileName = replacementFont;
                    if (replacementKind.Equals("ttf", StringComparison.OrdinalIgnoreCase))
                    {
                        styleRecord.BigFontFileName = string.Empty;
                        TryUpdateTextStyleFontDescriptor(styleRecord, replacementFont);
                    }
                }
                replacedStyleCount += 1;
                _trace.Log(
                    $"[DOTNET][FONT][REPLACE] style={styleRecord.Name} kind={replacementKind} replacement={replacementFont} explicitTarget={hasExplicitTarget} compatibilityTarget={hasCompatibilityTarget} compatibilitySource={compatibilityMatch?.SourceFont ?? string.Empty}"
                );
            }

            if (replaceMissing)
            {
                replacedEntityCount = ApplyEmptyStyleEntityReplacements(
                    db,
                    tr,
                    result,
                    out emptyStyleStylePatchedCount,
                    out emptyStyleSharedSkippedCount,
                    out emptyStyleSharedStyles
                );
            }

            tr.Commit();
        }

        if (replaceMissing)
        {
            TryRegenActiveDocument();
            if (string.IsNullOrWhiteSpace(_task.OutputDwg))
            {
                result.Errors.Add("FONT_REPLACEMENT_OUTPUT_DWG_MISSING");
            }
            else
            {
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
            }
        }

        result.AdditionalData["schema_version"] = "font-preflight-result@1.0";
        result.AdditionalData["filename"] = Path.GetFileName(_task.SourceDxf);
        result.AdditionalData["status"] = missingFonts.Count > 0 ? "missing_fonts" : "ok";
        result.AdditionalData["detected_style_count"] = detectedStyleCount;
        result.AdditionalData["missing_style_count"] = missingFonts.Count;
        result.AdditionalData["missing_fonts"] = missingFonts;
        result.AdditionalData["font_replacement_applied"] = replaceMissing && (replacedStyleCount > 0 || replacedEntityCount > 0);
        result.AdditionalData["replacement_font"] = string.IsNullOrWhiteSpace(_task.ReplacementFont)
            ? string.Empty
            : _task.ReplacementFont;
        result.AdditionalData["replacement_fonts"] = new Dictionary<string, string>(_task.ReplacementFonts);
        result.AdditionalData["font_compatibility_replacements"] =
            new Dictionary<string, string>(_task.FontCompatibilityReplacements);
        result.AdditionalData["empty_style_replacement"] =
            new Dictionary<string, string>(_task.EmptyStyleReplacement);
        result.AdditionalData["empty_style_target_regions_count"] = _task.EmptyStyleTargetRegions.Count;
        result.AdditionalData["empty_style_entity_replaced_count"] = replacedEntityCount;
        result.AdditionalData["empty_style_style_patched_count"] = emptyStyleStylePatchedCount;
        result.AdditionalData["empty_style_shared_skipped_count"] = emptyStyleSharedSkippedCount;
        result.AdditionalData["empty_style_shared_styles"] = emptyStyleSharedStyles;
        result.AdditionalData["empty_style_global_replaced_count"] = emptyStyleGlobalReplacedCount;
        result.AdditionalData["replaced_style_count"] = replacedStyleCount;
        result.AdditionalData["skipped_invalid_object_count"] = _skippedInvalidObjectCount;
        _trace.Log(
            $"[DOTNET][FONT] status={result.AdditionalData["status"]} detected={detectedStyleCount} missing={missingFonts.Count} replaced={replacedStyleCount} skipped_invalid={_skippedInvalidObjectCount}"
        );
    }

    private Dictionary<ObjectId, FontStyleUsage> CollectStyleUsage(Database db, Transaction tr)
    {
        var usageByStyle = new Dictionary<ObjectId, FontStyleUsage>();
        var blockTable = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
        foreach (ObjectId recordId in blockTable)
        {
            if (!TryGetObject(tr, recordId, OpenMode.ForRead, out BlockTableRecord record, "layout_record"))
            {
                continue;
            }

            if (!TryRead(() => record.IsLayout, "layout_record.IsLayout", out var isLayout) || !isLayout)
            {
                continue;
            }

            foreach (ObjectId entityId in record)
            {
                if (!TryGetObject(tr, entityId, OpenMode.ForRead, out Entity entity, "layout_entity"))
                {
                    continue;
                }

                ScanEntityUsage(tr, entity, usageByStyle, usedInBlock: false, usedInAttribute: false);
            }
        }

        return usageByStyle;
    }

    private void ScanEntityUsage(
        Transaction tr,
        Entity entity,
        Dictionary<ObjectId, FontStyleUsage> usageByStyle,
        bool usedInBlock,
        bool usedInAttribute
    )
    {
        switch (entity)
        {
            case AttributeDefinition attributeDefinition:
                TryMarkUsage(usageByStyle, () => attributeDefinition.TextStyleId, true, true, "attribute_definition.TextStyleId");
                return;
            case AttributeReference attributeReference:
                TryMarkUsage(usageByStyle, () => attributeReference.TextStyleId, true, true, "attribute_reference.TextStyleId");
                return;
            case DBText dbText:
                TryMarkUsage(usageByStyle, () => dbText.TextStyleId, usedInBlock, usedInAttribute, "dbtext.TextStyleId");
                return;
            case MText mText:
                TryMarkUsage(usageByStyle, () => mText.TextStyleId, usedInBlock, usedInAttribute, "mtext.TextStyleId");
                return;
            case BlockReference blockReference:
                ScanBlockReferenceUsage(tr, blockReference, usageByStyle, usedInBlock: true);
                return;
            default:
                return;
        }
    }

    private void ScanBlockReferenceUsage(
        Transaction tr,
        BlockReference blockReference,
        Dictionary<ObjectId, FontStyleUsage> usageByStyle,
        bool usedInBlock
    )
    {
        List<ObjectId> attributeIds;
        try
        {
            attributeIds = blockReference.AttributeCollection.Cast<ObjectId>().ToList();
        }
        catch (Exception ex)
        {
            RegisterSkippedObject("block_reference.AttributeCollection", ex);
            return;
        }

        foreach (ObjectId attributeId in attributeIds)
        {
            if (TryGetObject(tr, attributeId, OpenMode.ForRead, out AttributeReference attributeReference, "block_attribute"))
            {
                TryMarkUsage(usageByStyle, () => attributeReference.TextStyleId, true, true, "block_attribute.TextStyleId");
            }
        }

        if (!TryRead(() => blockReference.BlockTableRecord, "block_reference.BlockTableRecord", out var blockRecordId))
        {
            return;
        }

        if (!TryGetObject(tr, blockRecordId, OpenMode.ForRead, out BlockTableRecord record, "block_definition"))
        {
            return;
        }

        if (TryRead(() => record.IsFromExternalReference, "block_definition.IsFromExternalReference", out var isXref) && isXref)
        {
            _trace.Log($"[DOTNET][FONT][INFO] skip xref block={record.Name}");
            return;
        }

        foreach (ObjectId nestedId in record)
        {
            if (!TryGetObject(tr, nestedId, OpenMode.ForRead, out Entity nested, "nested_block_entity"))
            {
                continue;
            }

            ScanEntityUsage(tr, nested, usageByStyle, usedInBlock, usedInAttribute: false);
        }
    }

    private static void MarkUsage(
        Dictionary<ObjectId, FontStyleUsage> usageByStyle,
        ObjectId styleId,
        bool usedInBlock,
        bool usedInAttribute
    )
    {
        if (styleId.IsNull)
        {
            return;
        }

        if (!usageByStyle.TryGetValue(styleId, out var usage))
        {
            usage = new FontStyleUsage();
            usageByStyle[styleId] = usage;
        }

        usage.IsUsed = true;
        usage.UsedInBlock |= usedInBlock;
        usage.UsedInAttribute |= usedInAttribute;
    }

    private void TryMarkUsage(
        Dictionary<ObjectId, FontStyleUsage> usageByStyle,
        Func<ObjectId> styleIdAccessor,
        bool usedInBlock,
        bool usedInAttribute,
        string context
    )
    {
        if (!TryRead(styleIdAccessor, context, out var styleId))
        {
            return;
        }

        MarkUsage(usageByStyle, styleId, usedInBlock, usedInAttribute);
    }

    private FontCompatibilityMatch? ResolveCompatibilityMatch(TextStyleTableRecord styleRecord)
    {
        var bigfontName = NormalizeFontFileName(styleRecord.BigFontFileName ?? string.Empty);
        if (TryGetCompatibilityReplacement(bigfontName, out var bigfontReplacement))
        {
            return new FontCompatibilityMatch("bigfont", bigfontName, bigfontReplacement.Trim());
        }

        var fontName = NormalizeFontFileName(styleRecord.FileName ?? string.Empty);
        if (TryGetCompatibilityReplacement(fontName, out var replacement))
        {
            var kind = DetectKind(styleRecord.FileName ?? string.Empty, string.Empty);
            return new FontCompatibilityMatch(kind, fontName, replacement.Trim());
        }

        return null;
    }

    private bool TryGetCompatibilityReplacement(string fontName, out string replacement)
    {
        replacement = string.Empty;
        var normalized = NormalizeFontFileName(fontName);
        if (string.IsNullOrWhiteSpace(normalized))
        {
            return false;
        }

        foreach (var candidateName in BuildShxCandidateNames(normalized.ToLowerInvariant()))
        {
            if (_task.FontCompatibilityReplacements.TryGetValue(candidateName, out var mapped)
                && !string.IsNullOrWhiteSpace(mapped))
            {
                replacement = mapped;
                return true;
            }
        }

        return false;
    }

    private bool IsStyleMissing(TextStyleTableRecord styleRecord, Database db)
    {
        var fontName = (styleRecord.FileName ?? string.Empty).Trim();
        var bigfontName = (styleRecord.BigFontFileName ?? string.Empty).Trim();

        if (!string.IsNullOrWhiteSpace(bigfontName) && !IsFontResourceAvailable(bigfontName, db))
        {
            return true;
        }

        if (string.IsNullOrWhiteSpace(fontName))
        {
            return false;
        }

        return !IsFontResourceAvailable(fontName, db);
    }

    private static bool IsEmptyFontStyle(TextStyleTableRecord styleRecord)
    {
        return string.IsNullOrWhiteSpace(styleRecord.FileName)
            && string.IsNullOrWhiteSpace(styleRecord.BigFontFileName);
    }

    private bool HasEmptyStyleReplacement()
    {
        return _task.EmptyStyleReplacement.TryGetValue("font", out var fontName)
                && !string.IsNullOrWhiteSpace(fontName)
            || _task.EmptyStyleReplacement.TryGetValue("bigfont", out var bigfontName)
                && !string.IsNullOrWhiteSpace(bigfontName);
    }

    private bool ApplyEmptyStyleReplacement(
        TextStyleTableRecord styleRecord,
        BridgeResultEnvelope result
    )
    {
        _task.EmptyStyleReplacement.TryGetValue("font", out var fontName);
        _task.EmptyStyleReplacement.TryGetValue("bigfont", out var bigfontName);
        fontName = (fontName ?? string.Empty).Trim();
        bigfontName = (bigfontName ?? string.Empty).Trim();
        if (string.IsNullOrWhiteSpace(fontName) && string.IsNullOrWhiteSpace(bigfontName))
        {
            result.Errors.Add($"FONT_EMPTY_STYLE_REPLACEMENT_MISSING:{styleRecord.Name}");
            return false;
        }

        if (!string.IsNullOrWhiteSpace(fontName))
        {
            styleRecord.FileName = fontName;
            if (IsTrueTypeFont(fontName))
            {
                TryUpdateTextStyleFontDescriptor(styleRecord, fontName);
            }
        }

        if (!string.IsNullOrWhiteSpace(bigfontName))
        {
            styleRecord.BigFontFileName = bigfontName;
        }

        return true;
    }

    private int ApplyEmptyStyleEntityReplacements(
        Database db,
        Transaction tr,
        BridgeResultEnvelope result,
        out int patchedStyleCount,
        out int sharedSkippedCount,
        out List<string> sharedStyles
    )
    {
        patchedStyleCount = 0;
        sharedSkippedCount = 0;
        sharedStyles = new List<string>();
        if (!HasEmptyStyleReplacement() || _task.EmptyStyleTargetRegions.Count == 0)
        {
            return 0;
        }

        var usageByStyle = new Dictionary<ObjectId, EmptyStyleUsagePlan>();
        var blockTable = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
        foreach (ObjectId recordId in blockTable)
        {
            if (!TryGetObject(tr, recordId, OpenMode.ForRead, out BlockTableRecord record, "empty_style_layout_record"))
            {
                continue;
            }

            if (!TryRead(() => record.IsLayout, "empty_style_layout_record.IsLayout", out var isLayout) || !isLayout)
            {
                continue;
            }

            CollectEmptyStyleUsageInRecord(
                tr,
                record,
                Matrix3d.Identity,
                usageByStyle,
                depth: 0
            );
        }

        var patchedTextCount = 0;
        foreach (var usage in usageByStyle.Values)
        {
            if (!TryGetObject(
                tr,
                usage.StyleId,
                OpenMode.ForWrite,
                out TextStyleTableRecord styleRecord,
                "empty_style_patch_style"
            ))
            {
                continue;
            }

            EnsureWriteEnabled(styleRecord);
            if (!ApplyEmptyStyleReplacement(styleRecord, result))
            {
                continue;
            }

            patchedStyleCount += 1;
            patchedTextCount += usage.TargetMatchedCount + usage.OutsideTargetCount;
            _trace.Log(
                $"[DOTNET][FONT][EMPTY_STYLE_PATCH] style={usage.StyleName} target={usage.TargetMatchedCount} outside={usage.OutsideTargetCount}"
            );
        }

        sharedSkippedCount = sharedStyles.Count;
        return patchedTextCount;
    }

    private void CollectEmptyStyleUsageInRecord(
        Transaction tr,
        BlockTableRecord record,
        Matrix3d worldTransform,
        Dictionary<ObjectId, EmptyStyleUsagePlan> usageByStyle,
        int depth
    )
    {
        if (depth > 12)
        {
            return;
        }

        foreach (ObjectId entityId in record)
        {
            if (!TryGetObject(tr, entityId, OpenMode.ForRead, out Entity entity, "empty_style_entity"))
            {
                continue;
            }

            if (entity is BlockReference blockReference)
            {
                CollectEmptyStyleUsageInBlockReference(
                    tr,
                    blockReference,
                    worldTransform,
                    usageByStyle,
                    depth + 1
                );
                continue;
            }

            RegisterEmptyStyleUsage(tr, entity, worldTransform, usageByStyle);
        }
    }

    private void CollectEmptyStyleUsageInBlockReference(
        Transaction tr,
        BlockReference blockReference,
        Matrix3d parentTransform,
        Dictionary<ObjectId, EmptyStyleUsagePlan> usageByStyle,
        int depth
    )
    {
        try
        {
            foreach (ObjectId attributeId in blockReference.AttributeCollection.Cast<ObjectId>().ToList())
            {
                if (!TryGetObject(
                    tr,
                    attributeId,
                    OpenMode.ForRead,
                    out AttributeReference attributeReference,
                    "empty_style_block_attribute"
                ))
                {
                    continue;
                }

                RegisterEmptyStyleUsage(tr, attributeReference, parentTransform, usageByStyle);
            }
        }
        catch (Exception ex)
        {
            RegisterSkippedObject("empty_style_block_reference.AttributeCollection", ex);
        }

        if (!TryRead(() => blockReference.BlockTableRecord, "empty_style_block_reference.BlockTableRecord", out var blockRecordId))
        {
            return;
        }

        if (!TryGetObject(tr, blockRecordId, OpenMode.ForRead, out BlockTableRecord record, "empty_style_block_definition"))
        {
            return;
        }

        if (TryRead(() => record.IsFromExternalReference, "empty_style_block_definition.IsFromExternalReference", out var isXref) && isXref)
        {
            return;
        }

        var childTransform = parentTransform * blockReference.BlockTransform;
        CollectEmptyStyleUsageInRecord(tr, record, childTransform, usageByStyle, depth);
    }

    private void RegisterEmptyStyleUsage(
        Transaction tr,
        Entity entity,
        Matrix3d worldTransform,
        Dictionary<ObjectId, EmptyStyleUsagePlan> usageByStyle
    )
    {
        if (!TryGetTextStyleId(entity, out var styleId) || styleId.IsNull)
        {
            return;
        }

        if (!TryGetObject(tr, styleId, OpenMode.ForRead, out TextStyleTableRecord styleRecord, "empty_style_source_style"))
        {
            return;
        }

        if (!IsEmptyFontStyle(styleRecord))
        {
            return;
        }

        if (!usageByStyle.TryGetValue(styleId, out var usage))
        {
            usage = new EmptyStyleUsagePlan(styleId, styleRecord.Name ?? string.Empty);
            usageByStyle[styleId] = usage;
        }

        var text = GetEntityText(entity);
        if (TryMatchEmptyStyleRegion(entity, worldTransform, text, out _))
        {
            usage.TargetMatchedCount += 1;
        }
        else
        {
            usage.OutsideTargetCount += 1;
        }
    }

    private bool TryMatchEmptyStyleRegion(
        Entity entity,
        Matrix3d worldTransform,
        string text,
        out BridgeEmptyStyleTargetRegion? matchedRegion
    )
    {
        matchedRegion = null;
        if (string.IsNullOrWhiteSpace(text))
        {
            return false;
        }

        if (!TryGetWorldCenter(entity, worldTransform, out var center))
        {
            return false;
        }

        foreach (var region in _task.EmptyStyleTargetRegions)
        {
            if (!PointInside(region.BBox, center))
            {
                continue;
            }

            if (!ShouldReplaceEmptyStyleText(region.FieldKey, text))
            {
                continue;
            }

            matchedRegion = region;
            return true;
        }

        return false;
    }

    private static bool TryGetTextStyleId(Entity entity, out ObjectId styleId)
    {
        styleId = ObjectId.Null;
        switch (entity)
        {
            case AttributeReference attributeReference:
                styleId = attributeReference.TextStyleId;
                return true;
            case AttributeDefinition attributeDefinition:
                styleId = attributeDefinition.TextStyleId;
                return true;
            case DBText dbText:
                styleId = dbText.TextStyleId;
                return true;
            case MText mText:
                styleId = mText.TextStyleId;
                return true;
            default:
                return false;
        }
    }

    private static string GetEntityText(Entity entity)
    {
        return entity switch
        {
            AttributeReference attributeReference => attributeReference.TextString ?? string.Empty,
            AttributeDefinition attributeDefinition => attributeDefinition.TextString ?? string.Empty,
            DBText dbText => dbText.TextString ?? string.Empty,
            MText mText => mText.Contents ?? string.Empty,
            _ => string.Empty,
        };
    }

    private static bool TryGetWorldCenter(Entity entity, Matrix3d transform, out Point3d center)
    {
        center = Point3d.Origin;
        try
        {
            var extents = entity.GeometricExtents;
            extents.TransformBy(transform);
            center = new Point3d(
                (extents.MinPoint.X + extents.MaxPoint.X) / 2.0,
                (extents.MinPoint.Y + extents.MaxPoint.Y) / 2.0,
                (extents.MinPoint.Z + extents.MaxPoint.Z) / 2.0
            );
            return true;
        }
        catch
        {
            if (TryGetEntityReferencePoint(entity, out var point))
            {
                center = point.TransformBy(transform);
                return true;
            }
        }

        return false;
    }

    private static bool TryGetEntityReferencePoint(Entity entity, out Point3d point)
    {
        point = Point3d.Origin;
        switch (entity)
        {
            case AttributeReference attributeReference:
                point = attributeReference.Position;
                return true;
            case AttributeDefinition attributeDefinition:
                point = attributeDefinition.Position;
                return true;
            case DBText dbText:
                point = dbText.Position;
                return true;
            case MText mText:
                point = mText.Location;
                return true;
            default:
                return false;
        }
    }

    private static bool PointInside(BridgeBBox bbox, Point3d point)
    {
        return point.X >= bbox.Xmin
            && point.X <= bbox.Xmax
            && point.Y >= bbox.Ymin
            && point.Y <= bbox.Ymax;
    }

    private static bool ShouldReplaceEmptyStyleText(string fieldKey, string text)
    {
        var normalized = Regex.Replace(text ?? string.Empty, @"\s+", string.Empty).Trim();
        if (string.IsNullOrWhiteSpace(normalized))
        {
            return false;
        }

        var field = (fieldKey ?? string.Empty).Trim().ToLowerInvariant();
        if (field == "page_info")
        {
            return Regex.IsMatch(normalized, @"[0-9Xx]");
        }

        if (field == "external_code")
        {
            var compact = normalized.Replace(".", string.Empty).Replace("-", string.Empty);
            if (compact.Equals("DOCNO", StringComparison.OrdinalIgnoreCase)
                || compact.Equals("NO", StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            return Regex.IsMatch(compact, @"^[A-Za-z0-9]+$");
        }

        if (field == "internal_code")
        {
            return Regex.IsMatch(normalized, @"^[A-Za-z0-9-]+$")
                && Regex.IsMatch(normalized, @"[0-9]");
        }

        return Regex.IsMatch(normalized, @"[A-Za-z0-9]");
    }

    private static string TruncateTraceText(string text)
    {
        var normalized = Regex.Replace(text ?? string.Empty, @"\s+", " ").Trim();
        return normalized.Length <= 40 ? normalized : normalized.Substring(0, 40);
    }

    private static void TryWrite(Action action)
    {
        try
        {
            action();
        }
        catch
        {
            // Preserve best-effort clone creation across legacy styles.
        }
    }

    private bool IsFontResourceAvailable(string fontName, Database db)
    {
        var normalized = Path.GetFileName(fontName).Trim().ToLowerInvariant();
        if (string.IsNullOrWhiteSpace(normalized))
        {
            return true;
        }

        if (Path.IsPathRooted(fontName) && File.Exists(fontName))
        {
            return true;
        }

        var extension = Path.GetExtension(normalized).ToLowerInvariant();
        if (extension == ".shx" || string.IsNullOrWhiteSpace(extension))
        {
            if (ExistsInAutoCADFontDirs(normalized))
            {
                return true;
            }
        }

        if (extension is ".ttf" or ".ttc" or ".otf")
        {
            if (_installedFontFiles.Contains(normalized))
            {
                return true;
            }

            foreach (var alias in ResolveTrueTypeFileAliases(normalized))
            {
                if (_installedFontFiles.Contains(alias))
                {
                    return true;
                }
            }

            var family = Path.GetFileNameWithoutExtension(normalized);
            if (_installedFamilies.Contains(family))
            {
                return true;
            }
        }

        try
        {
            var resolved = HostApplicationServices.Current.FindFile(fontName, db, FindFileHint.Default);
            if (!string.IsNullOrWhiteSpace(resolved) && File.Exists(resolved))
            {
                return true;
            }
        }
        catch
        {
            // Fall through to missing
        }

        return false;
    }

    private static IEnumerable<string> ResolveTrueTypeFileAliases(string normalizedFontName)
    {
        if (TrueTypeFileAliases.TryGetValue(normalizedFontName, out var aliases))
        {
            foreach (var alias in aliases)
            {
                yield return alias;
            }
        }
    }

    private bool ExistsInAutoCADFontDirs(string normalizedFontName)
    {
        if (_autocadFontDirs.Count == 0)
        {
            return false;
        }

        foreach (var candidateName in BuildShxCandidateNames(normalizedFontName))
        {
            foreach (var fontsDir in _autocadFontDirs)
            {
                if (File.Exists(Path.Combine(fontsDir, candidateName)))
                {
                    return true;
                }
            }
        }

        return false;
    }

    private static Dictionary<string, object> BuildMissingFontPayload(
        TextStyleTableRecord styleRecord,
        FontStyleUsage usage
    )
    {
        var fontName = (styleRecord.FileName ?? string.Empty).Trim();
        var bigfontName = (styleRecord.BigFontFileName ?? string.Empty).Trim();
        return new Dictionary<string, object>
        {
            ["style_name"] = styleRecord.Name,
            ["font_name"] = fontName,
            ["bigfont_name"] = bigfontName,
            ["kind"] = DetectKind(fontName, bigfontName),
            ["used_in_block"] = usage.UsedInBlock || usage.UsedInAttribute,
        };
    }

    private static string DetectKind(string fontName, string bigfontName)
    {
        if (!string.IsNullOrWhiteSpace(bigfontName))
        {
            return "bigfont";
        }

        var extension = Path.GetExtension(fontName).ToLowerInvariant();
        if (extension is ".ttf" or ".ttc" or ".otf")
        {
            return "ttf";
        }

        if (extension == ".shx" || (!string.IsNullOrWhiteSpace(fontName) && !fontName.Contains(".")))
        {
            return "shx";
        }

        return "unknown";
    }

    private static bool IsTrueTypeFont(string fontName)
    {
        var extension = Path.GetExtension(fontName).ToLowerInvariant();
        return extension is ".ttf" or ".ttc" or ".otf";
    }

    private static Dictionary<string, BridgeReplacementTarget> BuildReplacementTargetMap(
        IEnumerable<BridgeReplacementTarget> targets
    )
    {
        var result = new Dictionary<string, BridgeReplacementTarget>(StringComparer.OrdinalIgnoreCase);
        foreach (var target in targets)
        {
            var styleName = (target.StyleName ?? string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(styleName))
            {
                continue;
            }

            result[styleName] = target;
        }

        return result;
    }

    private static IEnumerable<string> BuildShxCandidateNames(string normalizedFontName)
    {
        if (string.IsNullOrWhiteSpace(normalizedFontName))
        {
            yield break;
        }

        yield return normalizedFontName;
        if (string.IsNullOrWhiteSpace(Path.GetExtension(normalizedFontName)))
        {
            yield return normalizedFontName + ".shx";
        }
    }

    private static string NormalizeFontFileName(string fontName)
    {
        var normalized = (fontName ?? string.Empty).Trim();
        if (string.IsNullOrWhiteSpace(normalized))
        {
            return string.Empty;
        }

        return Path.GetFileName(normalized).Trim();
    }

    private string ResolveReplacementFont(string kind)
    {
        var normalized = (kind ?? string.Empty).Trim().ToLowerInvariant();
        if (_task.ReplacementFonts.TryGetValue(normalized, out var mapped) && !string.IsNullOrWhiteSpace(mapped))
        {
            return mapped.Trim();
        }

        if (!string.IsNullOrWhiteSpace(_task.ReplacementFont))
        {
            return _task.ReplacementFont.Trim();
        }

        return string.Empty;
    }

    private static void EnsureWriteEnabled(DBObject obj)
    {
        if (!obj.IsWriteEnabled)
        {
            obj.UpgradeOpen();
        }
    }

    private static HashSet<string> LoadInstalledFontFiles()
    {
        var fontsDir = Environment.GetFolderPath(Environment.SpecialFolder.Fonts);
        if (string.IsNullOrWhiteSpace(fontsDir) || !Directory.Exists(fontsDir))
        {
            return new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        }

        var results = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var path in Directory.EnumerateFiles(fontsDir))
        {
            var name = Path.GetFileName(path);
            var extension = Path.GetExtension(name).ToLowerInvariant();
            if (string.IsNullOrWhiteSpace(name) || (extension != ".ttf" && extension != ".ttc" && extension != ".otf"))
            {
                continue;
            }

            results.Add(name.ToLowerInvariant());
        }

        return results;
    }

    private static HashSet<string> LoadInstalledFontFamilies()
    {
        var results = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        try
        {
            var collection = new InstalledFontCollection();
            foreach (var family in collection.Families)
            {
                results.Add(family.Name);
            }
        }
        catch
        {
            // ignore; file-name based lookup still works
        }

        return results;
    }

    private static Dictionary<string, string> LoadInstalledFamilyMap()
    {
        var results = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        try
        {
            var collection = new InstalledFontCollection();
            foreach (var family in collection.Families)
            {
                if (!string.IsNullOrWhiteSpace(family.Name))
                {
                    results[family.Name] = family.Name;
                }
            }
        }
        catch
        {
            // ignore; file-name based lookup still works
        }

        return results;
    }

    private static List<string> LoadAutoCADFontDirs()
    {
        var results = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        void AddDir(string raw)
        {
            var value = (raw ?? string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(value))
            {
                return;
            }

            foreach (var part in value.Split(new[] { ';' }, StringSplitOptions.RemoveEmptyEntries))
            {
                var dir = part.Trim();
                if (string.IsNullOrWhiteSpace(dir) || !Directory.Exists(dir) || !seen.Add(dir))
                {
                    continue;
                }

                results.Add(dir);
            }
        }

        AddDir(Environment.GetEnvironmentVariable("FANBAN_AUTOCAD_FONTS_DIR") ?? string.Empty);

        var installDir = Environment.GetEnvironmentVariable("FANBAN_AUTOCAD_INSTALL_DIR") ?? string.Empty;
        if (!string.IsNullOrWhiteSpace(installDir))
        {
            AddDir(Path.Combine(installDir, "Fonts"));
        }

        return results;
    }

    private sealed class FontStyleUsage
    {
        public bool IsUsed { get; set; }
        public bool UsedInBlock { get; set; }
        public bool UsedInAttribute { get; set; }
    }

    private sealed class EmptyStyleUsagePlan
    {
        public EmptyStyleUsagePlan(ObjectId styleId, string styleName)
        {
            StyleId = styleId;
            StyleName = string.IsNullOrWhiteSpace(styleName) ? "<unnamed>" : styleName;
        }

        public ObjectId StyleId { get; }
        public string StyleName { get; }
        public int TargetMatchedCount { get; set; }
        public int OutsideTargetCount { get; set; }
    }

    private sealed class FontCompatibilityMatch
    {
        public FontCompatibilityMatch(string kind, string sourceFont, string replacementFont)
        {
            Kind = kind;
            SourceFont = sourceFont;
            ReplacementFont = replacementFont;
        }

        public string Kind { get; }
        public string SourceFont { get; }
        public string ReplacementFont { get; }
    }

    private bool TryGetObject<T>(
        Transaction tr,
        ObjectId objectId,
        OpenMode openMode,
        out T obj,
        string context
    ) where T : DBObject
    {
        obj = null!;
        if (!IsUsableObjectId(objectId))
        {
            RegisterSkippedObject(context, null);
            return false;
        }

        try
        {
            var dbObject = tr.GetObject(objectId, openMode, false) as T;
            if (dbObject == null)
            {
                RegisterSkippedObject(context, null);
                return false;
            }

            obj = dbObject;
            return true;
        }
        catch (Exception ex)
        {
            RegisterSkippedObject(context, ex);
            return false;
        }
    }

    private bool TryRead<T>(Func<T> reader, string context, out T value)
    {
        value = default!;
        try
        {
            value = reader();
            return true;
        }
        catch (Exception ex)
        {
            RegisterSkippedObject(context, ex);
            return false;
        }
    }

    private void RegisterSkippedObject(string context, Exception? ex)
    {
        _skippedInvalidObjectCount += 1;
        var detail = ex == null ? "invalid_or_missing" : ex.Message;
        _trace.Log($"[DOTNET][FONT][WARN] skip {context}: {detail}");
    }

    private void TryUpdateTextStyleFontDescriptor(
        TextStyleTableRecord styleRecord,
        string replacementFont
    )
    {
        try
        {
            var typeFace = ResolveTypeFaceName(replacementFont);
            if (string.IsNullOrWhiteSpace(typeFace))
            {
                return;
            }

            var existing = styleRecord.Font;
            styleRecord.Font = new FontDescriptor(
                typeFace,
                existing.Bold,
                existing.Italic,
                existing.CharacterSet,
                existing.PitchAndFamily
            );
            _trace.Log($"[DOTNET][FONT][TYPEFACE] style={styleRecord.Name} typeface={typeFace}");
        }
        catch (Exception ex)
        {
            _trace.Log($"[DOTNET][FONT][WARN] update typeface failed style={styleRecord.Name} err={ex.Message}");
        }
    }

    private string ResolveTypeFaceName(string replacementFont)
    {
        var stem = Path.GetFileNameWithoutExtension((replacementFont ?? string.Empty).Trim());
        if (string.IsNullOrWhiteSpace(stem))
        {
            return string.Empty;
        }

        if (_installedFamilyMap.TryGetValue(stem, out var family))
        {
            return family;
        }

        return stem;
    }

    private void TryRegenActiveDocument()
    {
        try
        {
            var doc = Application.DocumentManager.MdiActiveDocument;
            doc?.Editor?.Regen();
            _trace.Log("[DOTNET][FONT][REGEN] active document regenerated");
        }
        catch (Exception ex)
        {
            _trace.Log($"[DOTNET][FONT][WARN] regen failed: {ex.Message}");
        }
    }

    private static bool IsUsableObjectId(ObjectId objectId)
    {
        return !objectId.IsNull && objectId.IsValid && !objectId.IsErased;
    }
}
