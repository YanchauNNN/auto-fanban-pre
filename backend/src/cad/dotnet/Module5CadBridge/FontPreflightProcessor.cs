using System;
using System.Collections.Generic;
using System.Drawing.Text;
using System.IO;
using System.Linq;
using Autodesk.AutoCAD.DatabaseServices;

namespace Module5CadBridge;

internal sealed class FontPreflightProcessor
{
    private readonly BridgeTask _task;
    private readonly BridgeTraceLogger _trace;
    private readonly HashSet<string> _installedFontFiles;
    private readonly HashSet<string> _installedFamilies;

    public FontPreflightProcessor(BridgeTask task, BridgeTraceLogger trace)
    {
        _task = task;
        _trace = trace;
        _installedFontFiles = LoadInstalledFontFiles();
        _installedFamilies = LoadInstalledFontFamilies();
    }

    public void Execute(BridgeResultEnvelope result)
    {
        using var db = new Database(false, true);
        db.ReadDwgFile(_task.SourceDxf, FileShare.ReadWrite, true, string.Empty);
        db.CloseInput(true);

        Dictionary<ObjectId, FontStyleUsage> usageByStyle;
        var missingFonts = new List<Dictionary<string, object>>();
        var replacedStyleCount = 0;
        var detectedStyleCount = 0;
        var replaceMissing = _task.WorkflowStage.Equals("font_replace_missing", StringComparison.OrdinalIgnoreCase);

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

                if (!IsStyleMissing(styleRecord, db))
                {
                    continue;
                }

                missingFonts.Add(BuildMissingFontPayload(styleRecord, usage));
                if (!replaceMissing)
                {
                    continue;
                }

                if (string.IsNullOrWhiteSpace(_task.ReplacementFont))
                {
                    result.Errors.Add("FONT_REPLACEMENT_FONT_MISSING");
                    continue;
                }

                EnsureWriteEnabled(styleRecord);
                styleRecord.FileName = _task.ReplacementFont;
                styleRecord.BigFontFileName = string.Empty;
                replacedStyleCount += 1;
                _trace.Log(
                    $"[DOTNET][FONT][REPLACE] style={styleRecord.Name} replacement={_task.ReplacementFont}"
                );
            }

            tr.Commit();
        }

        if (replaceMissing)
        {
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
                db.SaveAs(_task.OutputDwg, DwgVersion.Current);
            }
        }

        result.AdditionalData["schema_version"] = "font-preflight-result@1.0";
        result.AdditionalData["filename"] = Path.GetFileName(_task.SourceDxf);
        result.AdditionalData["status"] = missingFonts.Count > 0 ? "missing_fonts" : "ok";
        result.AdditionalData["detected_style_count"] = detectedStyleCount;
        result.AdditionalData["missing_style_count"] = missingFonts.Count;
        result.AdditionalData["missing_fonts"] = missingFonts;
        result.AdditionalData["font_replacement_applied"] = replaceMissing && replacedStyleCount > 0;
        result.AdditionalData["replacement_font"] = string.IsNullOrWhiteSpace(_task.ReplacementFont)
            ? string.Empty
            : _task.ReplacementFont;
        result.AdditionalData["replaced_style_count"] = replacedStyleCount;
        _trace.Log(
            $"[DOTNET][FONT] status={result.AdditionalData["status"]} detected={detectedStyleCount} missing={missingFonts.Count} replaced={replacedStyleCount}"
        );
    }

    private Dictionary<ObjectId, FontStyleUsage> CollectStyleUsage(Database db, Transaction tr)
    {
        var usageByStyle = new Dictionary<ObjectId, FontStyleUsage>();
        var blockTable = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
        foreach (ObjectId recordId in blockTable)
        {
            if (!(tr.GetObject(recordId, OpenMode.ForRead) is BlockTableRecord record) || !record.IsLayout)
            {
                continue;
            }

            foreach (ObjectId entityId in record)
            {
                if (!(tr.GetObject(entityId, OpenMode.ForRead, false) is Entity entity))
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
                MarkUsage(usageByStyle, attributeDefinition.TextStyleId, true, true);
                return;
            case AttributeReference attributeReference:
                MarkUsage(usageByStyle, attributeReference.TextStyleId, true, true);
                return;
            case DBText dbText:
                MarkUsage(usageByStyle, dbText.TextStyleId, usedInBlock, usedInAttribute);
                return;
            case MText mText:
                MarkUsage(usageByStyle, mText.TextStyleId, usedInBlock, usedInAttribute);
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
        foreach (ObjectId attributeId in blockReference.AttributeCollection)
        {
            if (attributeId.IsNull || attributeId.IsErased)
            {
                continue;
            }

            if (tr.GetObject(attributeId, OpenMode.ForRead, false) is AttributeReference attributeReference)
            {
                MarkUsage(usageByStyle, attributeReference.TextStyleId, true, true);
            }
        }

        if (!(tr.GetObject(blockReference.BlockTableRecord, OpenMode.ForRead) is BlockTableRecord record))
        {
            return;
        }

        if (record.IsFromExternalReference)
        {
            _trace.Log($"[DOTNET][FONT][INFO] skip xref block={record.Name}");
            return;
        }

        foreach (ObjectId nestedId in record)
        {
            if (!(tr.GetObject(nestedId, OpenMode.ForRead, false) is Entity nested))
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
        if (extension is ".ttf" or ".ttc" or ".otf")
        {
            if (_installedFontFiles.Contains(normalized))
            {
                return true;
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

    private sealed class FontStyleUsage
    {
        public bool IsUsed { get; set; }
        public bool UsedInBlock { get; set; }
        public bool UsedInAttribute { get; set; }
    }
}
