// Windows Firewall: does it let a program in on the networks this computer is on? An install for you alone adds no
// rules (README "Windows Firewall"), so Windows asks the first time a program listens. Cancel that, or allow only
// Private networks, and Windows writes inbound *Block* rules for the program: on a gig network that Windows calls
// Public, Amadeus Link can't be paired (TCP 7123), or the engine never hears the DJ laptop's decks (UDP). Nothing
// says so: the pairing times out, the link stays down. This finds those rules, and makes the allow rules (as the
// installer does for everyone) once the user says yes to Windows's administrator prompt.
// The rules are read through an IFirewallRules so the logic is tested on a Mac; on Windows, HNetCfg.FwPolicy2.
using System.Diagnostics;

namespace AmadeusKit;

[Flags]
public enum NetProfile { None = 0, Domain = 1, Private = 2, Public = 4 }

public enum NetProtocol { Any, Tcp, Udp }

/// One inbound rule, as much of it as matters here.
public sealed record FirewallRule(string Program, bool Allow, bool Enabled, NetProfile Profiles, NetProtocol Protocol, string LocalPorts);

public interface IFirewallRules
{
    /// The profiles of the networks this computer is on now (one per connected network kind).
    NetProfile Active { get; }
    /// Whether the firewall is on for a profile.
    bool IsOn(NetProfile profile);
    /// The inbound rules that name a program.
    IReadOnlyList<FirewallRule> Inbound();
}

public static class Firewall
{
    /// What the firewall does with a program on the active networks: blocked, and on which profile (the first
    /// with a block rule: block rules win over allow rules). Without any rule Windows asks, which it shows itself.
    public sealed record Verdict(bool Blocked, NetProfile Profile)
    {
        public static readonly Verdict Open = new(false, NetProfile.None);
    }

    /// Checks `programs` (any of them may be the one that listens) for `protocol` and `port` (null: any port).
    public static Verdict Check(IFirewallRules fw, IReadOnlyCollection<string> programs, NetProtocol protocol, int? port)
    {
        var rules = fw.Inbound().Where(r => r.Enabled && programs.Any(p => SamePath(p, r.Program))
                                            && Covers(r.Protocol, protocol) && CoversPort(r.LocalPorts, port)).ToList();
        foreach (var profile in new[] { NetProfile.Public, NetProfile.Private, NetProfile.Domain })
        {
            if (!fw.Active.HasFlag(profile) || !fw.IsOn(profile)) continue;
            if (rules.Any(r => !r.Allow && r.Profiles.HasFlag(profile))) return new Verdict(true, profile);
        }
        return Verdict.Open;
    }

    static bool Covers(NetProtocol rule, NetProtocol wanted) => rule == NetProtocol.Any || wanted == NetProtocol.Any || rule == wanted;

    /// "*", "7123", "7000-7200,9123" (the firewall's own forms; named sets like "RPC" never match).
    internal static bool CoversPort(string ports, int? port)
    {
        if (port is not { } p || ports.Length == 0 || ports == "*") return true;
        foreach (var part in ports.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries))
        {
            var dash = part.IndexOf('-');
            if (dash > 0 && int.TryParse(part[..dash], out var lo) && int.TryParse(part[(dash + 1)..], out var hi))
            {
                if (lo <= p && p <= hi) return true;
            }
            else if (int.TryParse(part, out var one) && one == p) return true;
        }
        return false;
    }

    static bool SamePath(string a, string b) =>
        string.Equals(Normal(a), Normal(b), StringComparison.OrdinalIgnoreCase);

    static string Normal(string path)
    {
        var p = System.Environment.ExpandEnvironmentVariables(path.Trim().Trim('"')).Replace('/', '\\');
        try { return Path.GetFullPath(p); }
        catch (Exception e) when (e is ArgumentException or NotSupportedException or PathTooLongException) { return p; }
    }

    public static string Name(NetProfile p) => p switch
    {
        NetProfile.Public => "public", NetProfile.Private => "private", NetProfile.Domain => "domain", _ => "",
    };

    /// The commands that let a program in from the local network, on every profile: its inbound rules (the
    /// block rules Windows wrote) go, an allow rule per protocol (and port) comes. `rule`: the name the
    /// installer uses, so an upgrade or uninstall replaces or removes these too.
    public static IReadOnlyList<string> AllowCommands(string rule, IReadOnlyCollection<string> programs,
                                                       IReadOnlyList<(NetProtocol Protocol, int? Port)> openings)
    {
        var commands = new List<string>();
        foreach (var program in programs)
            commands.Add($"advfirewall firewall delete rule name=all dir=in program=\"{program}\"");
        foreach (var program in programs)
            foreach (var (protocol, port) in openings)
                commands.Add($"advfirewall firewall add rule name=\"{rule}\" dir=in action=allow "
                             + $"protocol={(protocol == NetProtocol.Tcp ? "TCP" : protocol == NetProtocol.Udp ? "UDP" : "any")} "
                             + (port is { } p ? $"localport={p} " : "")
                             + $"remoteip=localsubnet profile=any program=\"{program}\"");
        return commands;
    }

    /// Runs `AllowCommands` as administrator (Windows's prompt). True when they ran; false when the user said no
    /// or a command failed.
    public static async Task<bool> Allow(IReadOnlyList<string> commands)
    {
        if (!OperatingSystem.IsWindows() || commands.Count == 0) return false;
        var netsh = Path.Combine(System.Environment.SystemDirectory, "netsh.exe");
        // one prompt for all: cmd runs them in turn, and stops at the first that fails (a delete that finds
        // nothing fails too, so those don't count)
        var script = string.Join(" & ", commands.Select(c => c.StartsWith("advfirewall firewall delete", StringComparison.Ordinal)
                                                            ? $"\"{netsh}\" {c} >nul"
                                                            : $"\"{netsh}\" {c} >nul || exit /b 1"));
        try
        {
            using var p = Process.Start(new ProcessStartInfo("cmd.exe", $"/d /s /c \"{script}\"")
            {
                UseShellExecute = true, Verb = "runas", WindowStyle = ProcessWindowStyle.Hidden,
            });
            if (p is null) return false;
            await p.WaitForExitAsync();
            return p.ExitCode == 0;
        }
        catch (System.ComponentModel.Win32Exception)  // the user said no
        {
            return false;
        }
    }

    /// This computer's firewall (Windows), nil elsewhere or when it can't be read.
    public static IFirewallRules? ThisComputer() => OperatingSystem.IsWindows() ? WindowsFirewall.Open() : null;
}

/// HNetCfg.FwPolicy2 (the firewall's COM object, what netsh and the Control Panel use), read only.
[System.Runtime.Versioning.SupportedOSPlatform("windows")]
sealed class WindowsFirewall : IFirewallRules
{
    readonly dynamic _policy;

    WindowsFirewall(object policy) => _policy = policy;

    public static WindowsFirewall? Open()
    {
        try
        {
            return Type.GetTypeFromProgID("HNetCfg.FwPolicy2") is { } t && Activator.CreateInstance(t) is { } o ? new WindowsFirewall(o) : null;
        }
        catch (Exception e) when (e is System.Runtime.InteropServices.COMException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    public NetProfile Active => (NetProfile)(int)_policy.CurrentProfileTypes;

    public bool IsOn(NetProfile profile)
    {
        try { return (bool)_policy.FirewallEnabled[(int)profile]; }
        catch (Exception e) when (e is Microsoft.CSharp.RuntimeBinder.RuntimeBinderException or System.Runtime.InteropServices.COMException)
        {
            return true;  // can't tell: as if on (a block rule found still says why)
        }
    }

    public IReadOnlyList<FirewallRule> Inbound()
    {
        var list = new List<FirewallRule>();
        foreach (dynamic r in _policy.Rules)
        {
            if ((int)r.Direction != 1) continue;  // NET_FW_RULE_DIR_IN
            if (r.ApplicationName is not string program || program.Length == 0) continue;
            var protocol = (int)r.Protocol switch { 6 => NetProtocol.Tcp, 17 => NetProtocol.Udp, 256 => NetProtocol.Any, _ => (NetProtocol?)null };
            if (protocol is null) continue;  // ICMP and the like: not what a program listens on
            list.Add(new FirewallRule(program, (int)r.Action == 1, (bool)r.Enabled, (NetProfile)((int)r.Profiles & 7),
                                      protocol.Value, r.LocalPorts as string ?? "*"));
        }
        return list;
    }
}

/// The firewall's verdict on one program, looked at again every so often (the computer may join another network),
/// and the way to let it in. For the windows: `BlockedOn` is the profile it's kept out on, null while it isn't.
public sealed class FirewallWatch : Observable, IDisposable
{
    NetProfile? _blockedOn;
    bool _allowing;
    string? _note;

    public NetProfile? BlockedOn { get => _blockedOn; private set => Set(ref _blockedOn, value); }
    public bool Allowing { get => _allowing; private set => Set(ref _allowing, value); }
    /// After an allow that didn't happen: why ("" never; null while there's nothing to say).
    public string? Note { get => _note; private set => Set(ref _note, value); }

    readonly string _rule;
    readonly IReadOnlyCollection<string> _programs;
    readonly IReadOnlyList<(NetProtocol Protocol, int? Port)> _openings;
    readonly Func<IFirewallRules?> _open;
    readonly UIThread _ui;
    CancellationTokenSource? _loop;

    /// `rule`: the installer's rule name; `openings`: what the program must be let in for (the first is checked).
    public FirewallWatch(string rule, IReadOnlyCollection<string> programs, IReadOnlyList<(NetProtocol, int?)> openings,
                         Func<IFirewallRules?>? open = null, SynchronizationContext? context = null)
    {
        _rule = rule;
        _programs = programs;
        _openings = openings;
        _open = open ?? Firewall.ThisComputer;
        _ui = new UIThread(context ?? SynchronizationContext.Current);
    }

    /// Looks now and then every `every` until stopped (off the UI thread: reading the rules takes a moment).
    public void Start(TimeSpan every)
    {
        Stop();
        var cts = _loop = new CancellationTokenSource();
        _ = Task.Run(async () =>
        {
            using var timer = new PeriodicTimer(every);
            try
            {
                do Look(cts);
                while (await timer.WaitForNextTickAsync(cts.Token).ConfigureAwait(false));
            }
            catch (OperationCanceledException) { }
        });
    }

    public void Stop()
    {
        _loop?.Cancel();
        _loop = null;
        _ui.Post(() => BlockedOn = null);
    }

    /// Looks once (on the calling thread), and posts what it saw (`from`: the loop that looks, none once stopped).
    public void Look() => Look(null);

    void Look(CancellationTokenSource? from)
    {
        NetProfile? blocked = null;
        try
        {
            if (_open() is { } fw && Firewall.Check(fw, _programs, _openings[0].Protocol, _openings[0].Port) is { Blocked: true } v)
                blocked = v.Profile;
        }
        catch (Exception e) when (e is not OutOfMemoryException)
        {
            // the rules can't be read (a policy, a broken COM registration): say nothing rather than something wrong
        }
        _ui.Post(() => { if (from is null || from == _loop) BlockedOn = blocked; });
    }

    /// Lets the program in (Windows asks for an administrator first), then looks again.
    public async Task Allow()
    {
        if (Allowing) return;
        Allowing = true;
        Note = null;
        var ok = await Firewall.Allow(Firewall.AllowCommands(_rule, _programs, _openings));
        Allowing = false;
        if (!ok) Note = "Windows Firewall wasn't changed. Allowing needs an administrator.";
        await Task.Run(Look);
    }

    public void Dispose() => _loop?.Cancel();
}
