// The DMX trace (amadeus/dmx/trace.py): every value that goes out to the lights, as it changes. The engine writes
// it to a file while a flag file exists; this switches the flag and follows the file's end.
using System.Text;

namespace AmadeusKit;

public sealed class DMXTrace
{
    public string Data { get; }
    public string Flag { get; }
    public string Log { get; }
    public bool IsOn { get; private set; }

    /// How many lines are kept to look back in (the file keeps them all).
    public const int Kept = 20_000;
    /// Further behind than this (the page was away, or the file is old): skip to the end.
    public const long Behind = 2 << 20;

    readonly List<EngineProcess.LogLine> _lines = [];
    /// The lines, as log lines (their time is in their own text, to the millisecond: `Date` is not used).
    public IReadOnlyList<EngineProcess.LogLine> Lines => _lines;
    /// The lines or the switch changed.
    public event Action? Changed;

    long _offset;
    byte[] _partial = [];
    int _nextId;

    public DMXTrace(string data)
    {
        Data = data;
        Flag = Path.Combine(data, ".cache", "dmx-trace");
        Log = Path.Combine(data, ".cache", "dmx-trace.log");
        IsOn = File.Exists(Flag);
    }

    /// The engine's own notes ("# … trace on"), not a value.
    public static bool IsNote(EngineProcess.LogLine line) => line.Text.StartsWith('#');

    /// Switches the trace on or off: a running engine follows within half a second.
    public void Set(bool on)
    {
        try
        {
            if (on)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(Flag)!);
                File.WriteAllBytes(Flag, []);
            }
            else File.Delete(Flag);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
        IsOn = File.Exists(Flag);
        Changed?.Invoke();
    }

    /// Empties the trace: the file too (the engine goes on writing at its start).
    public void Clear()
    {
        try { if (File.Exists(Log)) File.WriteAllBytes(Log, []); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
        _lines.Clear();
        _offset = 0;
        _partial = [];
        Changed?.Invoke();
    }

    /// Reads what the engine wrote since the last time. `read: false` only follows the switch.
    public void Poll(bool read = true)
    {
        var changed = false;
        var on = File.Exists(Flag);
        if (on != IsOn) { IsOn = on; changed = true; }
        if (read && Read()) changed = true;
        if (changed) Changed?.Invoke();
    }

    bool Read()
    {
        byte[] data;
        var skipped = false;
        try
        {
            // the engine keeps writing (and may start the file over) while this reads
            using var f = new FileStream(Log, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            var size = f.Length;
            if (size < _offset) { _offset = 0; _partial = []; }  // started over (cleared, or full)
            if (size - _offset > Behind) { _offset = size - Behind; _partial = []; skipped = true; }
            if (size <= _offset) return false;
            f.Seek(_offset, SeekOrigin.Begin);
            data = new byte[size - _offset];
            f.ReadExactly(data);
            _offset = size;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return false; }
        byte[] all = [.. _partial, .. data];
        var end = Array.LastIndexOf(all, (byte)'\n');
        if (end < 0) { _partial = all; return false; }
        _partial = all[(end + 1)..];
        var text = Encoding.UTF8.GetString(all, 0, end).Split('\n', StringSplitOptions.RemoveEmptyEntries);
        IEnumerable<string> fresh = skipped ? text.Skip(1) : text;  // cut in the middle of a line
        if (skipped) _lines.Clear();
        var before = _lines.Count;
        foreach (var line in fresh) _lines.Add(new(_nextId++, default, line.TrimEnd('\r'), false));
        if (_lines.Count > Kept) _lines.RemoveRange(0, _lines.Count - Kept);
        return skipped || _lines.Count != before || fresh.Any();
    }
}
