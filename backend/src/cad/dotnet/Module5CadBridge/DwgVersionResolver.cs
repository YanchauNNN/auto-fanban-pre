using System;
using System.Collections.Generic;
using Autodesk.AutoCAD.DatabaseServices;

namespace Module5CadBridge;

internal static class DwgVersionResolver
{
    private static readonly Dictionary<string, string> HeaderToEnumName =
        new(StringComparer.OrdinalIgnoreCase)
        {
            ["AC1009"] = "AC1009",
            ["AC1012"] = "AC1012",
            ["AC1014"] = "AC1014",
            ["AC1015"] = "AC1015",
            ["AC1018"] = "AC1800",
            ["AC1021"] = "AC1021",
            ["AC1024"] = "AC1024",
            ["AC1027"] = "AC1027",
            ["AC1032"] = "AC1032",
        };

    public static DwgVersion Resolve(string sourceHeaderCode, DwgVersion fallback)
    {
        var normalized = (sourceHeaderCode ?? string.Empty).Trim();
        if (normalized.Length == 0)
        {
            return fallback;
        }

        if (!HeaderToEnumName.TryGetValue(normalized, out var enumName))
        {
            return fallback;
        }

        return Enum.TryParse(enumName, ignoreCase: true, out DwgVersion resolved)
            ? resolved
            : fallback;
    }
}
