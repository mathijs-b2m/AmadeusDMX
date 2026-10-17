// DNS-SD (Bonjour's service discovery) with Windows's own: dnsapi.dll's DnsServiceBrowse / DnsServiceResolve /
// DnsServiceRegister (Windows 10 and later; no Bonjour to install). Amadeus DMX browses for Amadeus Link; Amadeus
// Link advertises itself. The callbacks come on a thread of Windows's: callers post to their UI thread.
using System.Net;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace AmadeusKit;

[SupportedOSPlatform("windows")]
static unsafe class DnsApi
{
    public const uint DNS_QUERY_REQUEST_VERSION1 = 1;
    public const int DNS_REQUEST_PENDING = 9506;
    public const ushort DNS_TYPE_PTR = 12;

    [StructLayout(LayoutKind.Sequential)]
    public struct BrowseRequest
    {
        public uint Version, InterfaceIndex;
        public IntPtr QueryName;
        public IntPtr Callback;      // void (DWORD status, PVOID context, PDNS_RECORD records)
        public IntPtr Context;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct ResolveRequest
    {
        public uint Version, InterfaceIndex;
        public IntPtr QueryName;
        public IntPtr Callback;      // void (DWORD status, PVOID context, PDNS_SERVICE_INSTANCE instance)
        public IntPtr Context;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct RegisterRequest
    {
        public uint Version, InterfaceIndex;
        public IntPtr ServiceInstance;
        public IntPtr Callback;      // void (DWORD status, PVOID context, PDNS_SERVICE_INSTANCE instance)
        public IntPtr Context;
        public IntPtr Credentials;
        public int UnicastEnabled;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct Cancel { public IntPtr Reserved; }

    // DNS_RECORDW (x64): pNext 0, pName 8, wType 16, wDataLength 18, Flags 20, dwTtl 24, dwReserved 28, Data 32
    public static IntPtr Next(IntPtr r) => Marshal.ReadIntPtr(r, 0);
    public static ushort Type(IntPtr r) => (ushort)Marshal.ReadInt16(r, 16);
    public static uint Ttl(IntPtr r) => (uint)Marshal.ReadInt32(r, 24);
    public static string? PtrTarget(IntPtr r) => Marshal.PtrToStringUni(Marshal.ReadIntPtr(r, 32));

    // DNS_SERVICE_INSTANCE (x64): pszInstanceName 0, pszHostName 8, ip4Address 16, ip6Address 24, wPort 32
    public static string? InstanceHost(IntPtr i) => Marshal.PtrToStringUni(Marshal.ReadIntPtr(i, 8));
    public static ushort InstancePort(IntPtr i) => (ushort)Marshal.ReadInt16(i, 32);
    public static IPAddress? InstanceIPv4(IntPtr i) =>
        Marshal.ReadIntPtr(i, 16) is var p && p != IntPtr.Zero ? new IPAddress((uint)Marshal.ReadInt32(p)) : null;

    [DllImport("dnsapi.dll")] public static extern int DnsServiceBrowse(ref BrowseRequest request, ref Cancel cancel);
    [DllImport("dnsapi.dll")] public static extern int DnsServiceBrowseCancel(ref Cancel cancel);
    [DllImport("dnsapi.dll")] public static extern int DnsServiceResolve(ref ResolveRequest request, ref Cancel cancel);
    [DllImport("dnsapi.dll")] public static extern int DnsServiceResolveCancel(ref Cancel cancel);
    [DllImport("dnsapi.dll")] public static extern int DnsServiceRegister(ref RegisterRequest request, IntPtr cancel);
    [DllImport("dnsapi.dll")] public static extern int DnsServiceDeRegister(ref RegisterRequest request, IntPtr cancel);
    [DllImport("dnsapi.dll")] public static extern void DnsServiceFreeInstance(IntPtr instance);
    [DllImport("dnsapi.dll")] public static extern void DnsRecordListFree(IntPtr records, int freeType);

    [DllImport("dnsapi.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr DnsServiceConstructInstance(string serviceName, string hostName, IntPtr ip4, IntPtr ip6, ushort port,
                                                            ushort priority, ushort weight, uint propertiesCount, IntPtr keys, IntPtr values);
}

/// Browses with DnsServiceBrowse. An instance goes away with its goodbye (TTL 0) or when its TTL runs out.
[SupportedOSPlatform("windows")]
public sealed unsafe class DnsSdBrowser : IServiceBrowser
{
    public event Action<IReadOnlyCollection<string>>? Changed;
    public event Action<bool>? Searching;

    readonly Dictionary<string, DateTime> _seen = [];
    readonly Lock _lock = new();
    DnsApi.Cancel _cancel;
    GCHandle _self;
    IntPtr _query;
    string _suffix = "";
    bool _on;

    public void Start(string type)
    {
        lock (_lock)
        {
            if (_on) return;
            _suffix = "." + type + ".local";
            // both live as long as the browser: Windows may still call back with them after a cancel
            if (_query == IntPtr.Zero) _query = Marshal.StringToHGlobalUni(type + ".local");
            if (!_self.IsAllocated) _self = GCHandle.Alloc(this);
            var req = new DnsApi.BrowseRequest
            {
                Version = DnsApi.DNS_QUERY_REQUEST_VERSION1,
                QueryName = _query,
                Callback = (IntPtr)(delegate* unmanaged<uint, IntPtr, IntPtr, void>)&OnBrowse,
                Context = GCHandle.ToIntPtr(_self),
            };
            _on = DnsApi.DnsServiceBrowse(ref req, ref _cancel) == DnsApi.DNS_REQUEST_PENDING;
        }
        Searching?.Invoke(_on);
    }

    public void Stop()
    {
        lock (_lock)
        {
            if (!_on) return;
            DnsApi.DnsServiceBrowseCancel(ref _cancel);
            _on = false;
            _seen.Clear();
        }
        Searching?.Invoke(false);
    }

    [UnmanagedCallersOnly]
    static void OnBrowse(uint status, IntPtr context, IntPtr records)
    {
        var self = (DnsSdBrowser)GCHandle.FromIntPtr(context).Target!;
        try { self.Browsed(status, records); }
        finally { if (records != IntPtr.Zero) DnsApi.DnsRecordListFree(records, 1); }
    }

    void Browsed(uint status, IntPtr records)
    {
        IReadOnlyCollection<string> names;
        lock (_lock)
        {
            if (!_on) return;  // cancelled: the last callback
            var now = DateTime.UtcNow;
            for (var r = records; r != IntPtr.Zero; r = DnsApi.Next(r))
            {
                if (DnsApi.Type(r) != DnsApi.DNS_TYPE_PTR || DnsApi.PtrTarget(r) is not { } target) continue;
                var name = target.EndsWith(_suffix, StringComparison.OrdinalIgnoreCase) ? target[..^_suffix.Length] : target;
                var ttl = DnsApi.Ttl(r);
                if (ttl == 0) _seen.Remove(name); else _seen[name] = now.AddSeconds(Math.Max(ttl, 120));
            }
            foreach (var gone in _seen.Where(p => p.Value < now).Select(p => p.Key).ToList()) _seen.Remove(gone);
            names = _seen.Keys.ToList();
        }
        Changed?.Invoke(names);
    }
}

/// Resolving a found instance to where it listens, and advertising one (Amadeus Link).
[SupportedOSPlatform("windows")]
public static class DnsSd
{
    sealed class Pending
    {
        public readonly TaskCompletionSource<(string Host, IPAddress? Address, int Port)?> Done =
            new(TaskCreationOptions.RunContinuationsAsynchronously);
    }

    /// "DJ laptop" of `_amadeuslink._tcp` → its host name, IPv4 address and port (nil: not found in time).
    public static async Task<(string Host, IPAddress? Address, int Port)?> Resolve(string name, string type, TimeSpan timeout)
    {
        var pending = new Pending();
        var handle = GCHandle.Alloc(pending);
        var query = Marshal.StringToHGlobalUni($"{name}.{type}.local");
        var cancel = new DnsApi.Cancel();
        try
        {
            if (!StartResolve(query, handle, ref cancel)) return null;
            var first = await Task.WhenAny(pending.Done.Task, Task.Delay(timeout));
            if (first != pending.Done.Task)
            {
                DnsApi.DnsServiceResolveCancel(ref cancel);
                await Task.WhenAny(pending.Done.Task, Task.Delay(1000));  // the cancel ends with a last callback
            }
            return pending.Done.Task.IsCompletedSuccessfully ? pending.Done.Task.Result : null;
        }
        finally
        {
            if (pending.Done.Task.IsCompleted) { handle.Free(); Marshal.FreeHGlobal(query); }
            // else Windows may still call back: leave both (a few bytes) rather than risk a freed handle
        }
    }

    static unsafe bool StartResolve(IntPtr query, GCHandle handle, ref DnsApi.Cancel cancel)
    {
        var req = new DnsApi.ResolveRequest
        {
            Version = DnsApi.DNS_QUERY_REQUEST_VERSION1,
            QueryName = query,
            Callback = (IntPtr)(delegate* unmanaged<uint, IntPtr, IntPtr, void>)&OnResolved,
            Context = GCHandle.ToIntPtr(handle),
        };
        return DnsApi.DnsServiceResolve(ref req, ref cancel) == DnsApi.DNS_REQUEST_PENDING;
    }

    [UnmanagedCallersOnly]
    static void OnResolved(uint status, IntPtr context, IntPtr instance)
    {
        var pending = (Pending)GCHandle.FromIntPtr(context).Target!;
        if (status == 0 && instance != IntPtr.Zero && DnsApi.InstanceHost(instance) is { } host)
            pending.Done.TrySetResult((host, DnsApi.InstanceIPv4(instance), DnsApi.InstancePort(instance)));
        else
            pending.Done.TrySetResult(null);
        if (instance != IntPtr.Zero) DnsApi.DnsServiceFreeInstance(instance);
    }

    /// Advertises `name` (`type`, on `port`) until the returned object is disposed.
    public static IDisposable? Register(string name, string type, int port)
    {
        var host = Dns.GetHostName() + ".local";
        var instance = DnsApi.DnsServiceConstructInstance($"{name}.{type}.local", host, IntPtr.Zero, IntPtr.Zero, (ushort)port, 0, 0, 0,
                                                           IntPtr.Zero, IntPtr.Zero);
        if (instance == IntPtr.Zero) return null;
        var reg = new Registration(instance);
        return reg.Start() ? reg : null;
    }

    sealed unsafe class Registration(IntPtr instance) : IDisposable
    {
        DnsApi.RegisterRequest _req;
        GCHandle _self;
        bool _on;

        public bool Start()
        {
            _self = GCHandle.Alloc(this);
            _req = new DnsApi.RegisterRequest
            {
                Version = DnsApi.DNS_QUERY_REQUEST_VERSION1,
                ServiceInstance = instance,
                Callback = (IntPtr)(delegate* unmanaged<uint, IntPtr, IntPtr, void>)&OnRegistered,
                Context = GCHandle.ToIntPtr(_self),
            };
            _on = DnsApi.DnsServiceRegister(ref _req, IntPtr.Zero) == DnsApi.DNS_REQUEST_PENDING;
            if (!_on) { _self.Free(); DnsApi.DnsServiceFreeInstance(instance); }
            return _on;
        }

        public void Dispose()
        {
            if (!_on) return;
            _on = false;
            DnsApi.DnsServiceDeRegister(ref _req, IntPtr.Zero);
            // the instance and the handle are kept: Windows calls back once more for the deregistration
        }

        [UnmanagedCallersOnly]
        static void OnRegistered(uint status, IntPtr context, IntPtr result)
        {
            if (result != IntPtr.Zero) DnsApi.DnsServiceFreeInstance(result);  // a copy for us: ours to free
        }
    }
}
