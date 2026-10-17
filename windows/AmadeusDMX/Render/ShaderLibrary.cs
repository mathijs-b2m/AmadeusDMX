// The stage's shaders: HLSL embedded in the app (Render/Shaders), compiled at startup with D3DCompiler (part of
// Windows), the bytecode kept in %LOCALAPPDATA%\Amadeus DMX\cache\shaders under a hash of the source, entry point,
// profile and flags, so later starts skip the compiler. Metal compiled Shaders.swift at runtime the same way.
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using Vortice.D3DCompiler;
using Vortice.Direct3D;

namespace AmadeusDMX;

public static class ShaderLibrary
{
    const string Prefix = "AmadeusDMX.Render.Shaders.";
    const ShaderFlags Flags = ShaderFlags.OptimizationLevel3;
    /// Changes when the rules above change (old cache entries are simply never read again).
    const string CacheVersion = "1";

    public static string CacheFolder =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Amadeus DMX", "cache", "shaders");

    static string Resource(string name)
    {
        using var s = Assembly.GetExecutingAssembly().GetManifestResourceStream(Prefix + name)
            ?? throw new FileNotFoundException($"shader {name} is not in the app");
        return new StreamReader(s).ReadToEnd();
    }

    /// A shader file's source, with Common.hlsli pasted in for its #include (no include handler needed).
    public static string Source(string file) =>
        Resource(file).Replace("#include \"Common.hlsli\"", Resource("Common.hlsli"));

    public static string Key(string source, string entry, string profile)
    {
        var h = SHA256.HashData(Encoding.UTF8.GetBytes($"{CacheVersion}\n{(int)Flags}\n{entry}\n{profile}\n{source}"));
        return Convert.ToHexString(h, 0, 16).ToLowerInvariant();
    }

    /// The bytecode for `entry` in `file` ("vs_5_0" / "ps_5_0"), from the cache or compiled now.
    public static byte[] Bytecode(string file, string entry, string profile)
    {
        var source = Source(file);
        var path = Path.Combine(CacheFolder, $"{Key(source, entry, profile)}.cso");
        try
        {
            if (File.Exists(path)) return File.ReadAllBytes(path);
        }
        catch (IOException) { }
        var code = Compile(source, file, entry, profile);
        try
        {
            Directory.CreateDirectory(CacheFolder);
            var tmp = path + "." + Environment.ProcessId + ".tmp";   // whole or not at all: a reader never sees half a file
            File.WriteAllBytes(tmp, code);
            File.Move(tmp, path, overwrite: true);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }  // a cache: never worth failing for
        return code;
    }

    /// Compile with D3DCompiler; a failure throws with the compiler's messages.
    public static byte[] Compile(string source, string name, string entry, string profile)
    {
        Blob? code = null, errors = null;
        // ASCII only: the source goes in as UTF-8 bytes but counted in characters, so a "·" or "–" in a comment
        // cut the end of every shader off ("unexpected end of file"); HLSL itself is ASCII
        source = string.Create(source.Length, source, (span, s) => { for (var i = 0; i < s.Length; i++) span[i] = s[i] < 128 ? s[i] : ' '; });
        try
        {
            var r = Compiler.Compile(source, null!, null!, entry, name, profile, Flags, EffectFlags.None, out code, out errors);
            if (r.Failure || code is null)
                throw new InvalidOperationException($"{name} {entry}: {Text(errors) ?? r.ToString()}");
            var size = (int)(nuint)code.BufferSize;
            var result = new byte[size];
            Marshal.Copy(code.BufferPointer, result, 0, size);
            return result;
        }
        finally
        {
            code?.Dispose();
            errors?.Dispose();
        }
    }

    static string? Text(Blob? b) =>
        b is null ? null : Marshal.PtrToStringAnsi(b.BufferPointer, (int)(nuint)b.BufferSize).TrimEnd('\0', '\n');
}
