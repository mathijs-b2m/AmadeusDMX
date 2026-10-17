// Reading JSON the way the Swift decoders do (System.Text.Json's JsonElement underneath). Swift's rules, kept here:
//   decode(…)          a required field: missing, null or the wrong type fails the whole message
//   decodeIfPresent(…) missing or null is nil; the wrong type still fails the whole message
//   try? …             anything wrong is nil (the field is left out, the message survives)
// Numbers: an Int field takes 3 or 3.0 but not 3.5; a Bool is only true/false (never 0/1), like JSONDecoder.
using System.Globalization;
using System.Text;
using System.Text.Json;

namespace AmadeusKit;

internal static class J
{
    static JsonException Wrong(string what, JsonElement e) => new($"expected {what}, got {e.ValueKind}");

    // MARK: one value

    public static double Double(JsonElement e) =>
        e.ValueKind == JsonValueKind.Number ? e.GetDouble() : throw Wrong("a number", e);

    public static float Float(JsonElement e) => (float)Double(e);

    public static int Int(JsonElement e)
    {
        if (e.ValueKind != JsonValueKind.Number) throw Wrong("an integer", e);
        if (e.TryGetInt32(out var i)) return i;
        var d = e.GetDouble();
        return d == Math.Floor(d) && d >= int.MinValue && d <= int.MaxValue ? (int)d : throw Wrong("an integer", e);
    }

    public static long Long(JsonElement e)
    {
        if (e.ValueKind != JsonValueKind.Number) throw Wrong("an integer", e);
        if (e.TryGetInt64(out var i)) return i;
        var d = e.GetDouble();
        return d == Math.Floor(d) ? (long)d : throw Wrong("an integer", e);
    }

    public static string String(JsonElement e) =>
        e.ValueKind == JsonValueKind.String ? e.GetString()! : throw Wrong("a string", e);

    public static bool Bool(JsonElement e) => e.ValueKind switch
    {
        JsonValueKind.True => true,
        JsonValueKind.False => false,
        _ => throw Wrong("true or false", e),
    };

    public static T[] Array<T>(JsonElement e, Func<JsonElement, T> item)
    {
        if (e.ValueKind != JsonValueKind.Array) throw Wrong("an array", e);
        var out_ = new T[e.GetArrayLength()];
        var i = 0;
        foreach (var x in e.EnumerateArray()) out_[i++] = item(x);
        return out_;
    }

    public static Func<JsonElement, T[]> ArrayOf<T>(Func<JsonElement, T> item) => e => Array(e, item);

    public static Dictionary<string, T> Dict<T>(JsonElement e, Func<JsonElement, T> value)
    {
        if (e.ValueKind != JsonValueKind.Object) throw Wrong("an object", e);
        var d = new Dictionary<string, T>();
        foreach (var p in e.EnumerateObject()) d[p.Name] = value(p.Value);
        return d;
    }

    public static Func<JsonElement, Dictionary<string, T>> DictOf<T>(Func<JsonElement, T> value) => e => Dict(e, value);

    /// A value that may be null (Swift `T?` inside an array: `[String?]`).
    public static Func<JsonElement, T?> OrNull<T>(Func<JsonElement, T> f) where T : class =>
        e => e.ValueKind == JsonValueKind.Null ? null : f(e);

    // MARK: fields of an object

    static JsonElement Object(JsonElement o) => o.ValueKind == JsonValueKind.Object ? o : throw Wrong("an object", o);

    static bool Present(JsonElement o, string key, out JsonElement v) =>
        Object(o).TryGetProperty(key, out v) && v.ValueKind != JsonValueKind.Null;

    /// `decode`: the field must be there.
    public static T Req<T>(JsonElement o, string key, Func<JsonElement, T> f) =>
        Present(o, key, out var v) ? f(v) : throw new JsonException($"missing \"{key}\"");

    /// `decodeIfPresent` for a value type: null when missing or null.
    public static T? Val<T>(JsonElement o, string key, Func<JsonElement, T> f) where T : struct =>
        Present(o, key, out var v) ? f(v) : null;

    /// `decodeIfPresent` for a reference type.
    public static T? Ref<T>(JsonElement o, string key, Func<JsonElement, T> f) where T : class =>
        Present(o, key, out var v) ? f(v) : null;

    public static bool Has(JsonElement o, string key) => Object(o).TryGetProperty(key, out _);

    /// `try?`: anything wrong is the default.
    public static T? Try<T>(Func<T> f)
    {
        try { return f(); }
        catch (Exception e) when (e is JsonException or InvalidOperationException or FormatException or KeyNotFoundException
                                       or IndexOutOfRangeException) { return default; }
    }

    // MARK: documents

    /// Parses and decodes; nil when it isn't JSON or doesn't decode (`try? JSONDecoder().decode`).
    public static T? Decode<T>(ReadOnlySpan<byte> utf8, Func<JsonElement, T> f) where T : class
    {
        try
        {
            var reader = new Utf8JsonReader(utf8, new JsonReaderOptions { AllowTrailingCommas = false });
            using var doc = JsonDocument.ParseValue(ref reader);
            return f(doc.RootElement);
        }
        catch (Exception e) when (e is JsonException or InvalidOperationException or FormatException) { return null; }
    }

    /// Like Decode, but the error goes on (`try JSONDecoder().decode`).
    public static T DecodeOrThrow<T>(ReadOnlySpan<byte> utf8, Func<JsonElement, T> f)
    {
        var reader = new Utf8JsonReader(utf8);
        using var doc = JsonDocument.ParseValue(ref reader);
        return f(doc.RootElement);
    }

    /// A JSON document's root, kept after the document is gone.
    public static JsonElement ParseElement(ReadOnlySpan<byte> utf8)
    {
        var reader = new Utf8JsonReader(utf8);
        using var doc = JsonDocument.ParseValue(ref reader);
        return doc.RootElement.Clone();
    }

    public static byte[] Utf8(string s) => Encoding.UTF8.GetBytes(s);

    public static string Num(double v) => v.ToString("R", CultureInfo.InvariantCulture);
}
