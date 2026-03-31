using System;
using Autodesk.AutoCAD.DatabaseServices;

namespace Module5CadBridge;

internal static class SafeCadAccess
{
    public static bool TryGetObject<T>(
        Transaction tr,
        ObjectId objectId,
        OpenMode openMode,
        BridgeTraceLogger trace,
        string context,
        out T? obj,
        bool openErased = false
    ) where T : DBObject
    {
        obj = null;
        if (!IsUsableObjectId(objectId))
        {
            trace.Log($"[DOTNET][WARN] skip {context}: invalid_object_id");
            return false;
        }

        try
        {
            var dbObject = tr.GetObject(objectId, openMode, openErased) as T;
            if (dbObject == null)
            {
                trace.Log($"[DOTNET][WARN] skip {context}: missing_or_wrong_type");
                return false;
            }

            obj = dbObject;
            return true;
        }
        catch (System.Exception ex)
        {
            trace.Log($"[DOTNET][WARN] skip {context}: {ex.GetType().Name}:{ex.Message}");
            return false;
        }
    }

    public static bool TryRead<T>(
        Func<T> reader,
        BridgeTraceLogger trace,
        string context,
        out T value
    )
    {
        try
        {
            value = reader();
            return true;
        }
        catch (System.Exception ex)
        {
            trace.Log($"[DOTNET][WARN] skip {context}: {ex.GetType().Name}:{ex.Message}");
            value = default!;
            return false;
        }
    }

    public static bool IsUsableObjectId(ObjectId objectId)
    {
        return !objectId.IsNull && !objectId.IsErased && !objectId.IsEffectivelyErased;
    }
}
