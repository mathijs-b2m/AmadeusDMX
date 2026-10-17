// The stage's GPU time per frame, from Direct3D 11 timestamp queries (Metal: the command buffer's gpuStartTime and
// gpuEndTime). A few sets of queries in a ring: a frame's result is read when the GPU has it, never waited for.
using System.Runtime.InteropServices;
using Vortice.Direct3D11;

namespace AmadeusDMX;

sealed class GpuTimer : IDisposable
{
    sealed record Set(ID3D11Query Disjoint, ID3D11Query Start, ID3D11Query End);

    [StructLayout(LayoutKind.Sequential)]
    struct DisjointData { public ulong Frequency; public int Disjoint; }   // D3D11_QUERY_DATA_TIMESTAMP_DISJOINT

    readonly Set[] _sets;
    int _next, _pending;

    public GpuTimer(ID3D11Device device, int depth = 5)
    {
        _sets = Enumerable.Range(0, depth).Select(_ => new Set(
            device.CreateQuery(new QueryDescription(QueryType.TimestampDisjoint)),
            device.CreateQuery(new QueryDescription(QueryType.Timestamp)),
            device.CreateQuery(new QueryDescription(QueryType.Timestamp)))).ToArray();
    }

    public void Begin(ID3D11DeviceContext ctx)
    {
        if (_pending == _sets.Length) return;   // all in flight: skip this frame's measurement
        var s = _sets[_next];
        ctx.Begin(s.Disjoint);
        ctx.End(s.Start);
    }

    public void End(ID3D11DeviceContext ctx)
    {
        if (_pending == _sets.Length) return;
        var s = _sets[_next];
        ctx.End(s.End);
        ctx.End(s.Disjoint);
        _next = (_next + 1) % _sets.Length;
        _pending++;
    }

    /// The oldest measured frame's GPU time (seconds), when it is ready.
    public unsafe double? Read(ID3D11DeviceContext ctx)
    {
        if (_pending == 0) return null;
        var s = _sets[(_next - _pending + _sets.Length) % _sets.Length];
        DisjointData d;
        ulong t0, t1;
        if (ctx.GetData(s.Disjoint, (IntPtr)(&d), (uint)sizeof(DisjointData), AsyncGetDataFlags.DoNotFlush).Code != 0) return null;
        if (ctx.GetData(s.Start, (IntPtr)(&t0), sizeof(ulong), AsyncGetDataFlags.DoNotFlush).Code != 0) return null;
        if (ctx.GetData(s.End, (IntPtr)(&t1), sizeof(ulong), AsyncGetDataFlags.DoNotFlush).Code != 0) return null;
        _pending--;
        if (d.Disjoint != 0 || d.Frequency == 0 || t1 < t0) return null;   // the clock changed meanwhile: no valid time
        return (t1 - t0) / (double)d.Frequency;
    }

    public void Dispose()
    {
        foreach (var s in _sets) { s.Disjoint.Dispose(); s.Start.Dispose(); s.End.Dispose(); }
    }
}
