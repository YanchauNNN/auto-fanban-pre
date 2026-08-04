using System;
using System.IO;
using Autodesk.AutoCAD.DatabaseServices;

namespace Module5CadBridge;

internal sealed class DwgToDxfExporter
{
    private readonly BridgeTask _task;
    private readonly BridgeTraceLogger _trace;

    public DwgToDxfExporter(BridgeTask task, BridgeTraceLogger trace)
    {
        _task = task;
        _trace = trace;
    }

    public void Execute(Database database, BridgeResultEnvelope result)
    {
        if (string.IsNullOrWhiteSpace(_task.OutputDxf))
        {
            throw new InvalidOperationException("output_dxf is required");
        }

        var outputPath = Path.GetFullPath(_task.OutputDxf);
        var outputDir = Path.GetDirectoryName(outputPath);
        if (!string.IsNullOrWhiteSpace(outputDir))
        {
            Directory.CreateDirectory(outputDir);
        }

        var version = ResolveVersion(_task.DxfVersion);
        var precision = Math.Max(0, Math.Min(16, _task.DxfPrecision));
        _trace.Log(
            $"[DOTNET][DWG_TO_DXF] output={outputPath} version={version} precision={precision}"
        );
        database.DxfOut(outputPath, precision, version);

        if (!File.Exists(outputPath))
        {
            throw new IOException($"DxfOut completed without output: {outputPath}");
        }

        result.AdditionalData["output_dxf"] = outputPath;
        result.AdditionalData["dxf_version"] = version.ToString();
        result.AdditionalData["dxf_precision"] = precision;
        _trace.Log($"[DOTNET][DWG_TO_DXF] completed output={outputPath}");
    }

    private static DwgVersion ResolveVersion(string rawVersion)
    {
        if (
            !string.IsNullOrWhiteSpace(rawVersion)
            && Enum.TryParse(rawVersion.Trim(), true, out DwgVersion parsed)
        )
        {
            return parsed;
        }

        return DwgVersion.AC1032;
    }
}
