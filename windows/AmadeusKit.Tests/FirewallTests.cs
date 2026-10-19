// Windows Firewall's verdict on a program, from its rules (a fake firewall here: the rules are what Windows writes
// when its first-listen prompt is cancelled or allowed on Private networks only), the commands that let it in,
// and the interpreter behind a venv's python.exe.
using AmadeusKit;

namespace AmadeusKit.Tests;

public class FirewallTests
{
    const string Link = @"C:\Users\dj\AppData\Local\Programs\Amadeus Link\AmadeusLink.exe";

    sealed class FakeFirewall(NetProfile active, params FirewallRule[] rules) : IFirewallRules
    {
        public NetProfile Off { get; init; }
        public NetProfile Active => active;
        public bool IsOn(NetProfile p) => !Off.HasFlag(p);
        public IReadOnlyList<FirewallRule> Inbound() => rules;
    }

    static FirewallRule Rule(bool allow, NetProfile profiles, NetProtocol protocol = NetProtocol.Tcp, string ports = "*", string program = Link) =>
        new(program, allow, true, profiles, protocol, ports);

    static Firewall.Verdict Check(IFirewallRules fw) => Firewall.Check(fw, [Link], NetProtocol.Tcp, 7123);

    [Fact]
    public void AllowedOnPrivateOnlyIsBlockedOnAPublicNetwork()
    {
        // Windows's prompt with only "Private networks" ticked: an allow rule there, a block rule (TCP and UDP) on Public
        var rules = new[]
        {
            Rule(true, NetProfile.Private), Rule(true, NetProfile.Private, NetProtocol.Udp),
            Rule(false, NetProfile.Public), Rule(false, NetProfile.Public, NetProtocol.Udp),
        };
        Assert.Equal(new Firewall.Verdict(true, NetProfile.Public), Check(new FakeFirewall(NetProfile.Public, rules)));
        Assert.Equal(Firewall.Verdict.Open, Check(new FakeFirewall(NetProfile.Private, rules)));
    }

    [Fact]
    public void ABlockRuleWinsOverAnAllowRule()
    {
        var fw = new FakeFirewall(NetProfile.Public, Rule(true, NetProfile.Public, NetProtocol.Any), Rule(false, NetProfile.Public));
        Assert.True(Check(fw).Blocked);
    }

    [Fact]
    public void OnlyRulesThatApplyCount()
    {
        Assert.False(Check(new FakeFirewall(NetProfile.Public)).Blocked);  // no rule: Windows asks itself
        Assert.False(Check(new FakeFirewall(NetProfile.Public, Rule(false, NetProfile.Public) with { Enabled = false })).Blocked);
        Assert.False(Check(new FakeFirewall(NetProfile.Public, Rule(false, NetProfile.Public, program: @"C:\Other\app.exe"))).Blocked);
        Assert.False(Check(new FakeFirewall(NetProfile.Public, Rule(false, NetProfile.Public, NetProtocol.Udp))).Blocked);  // not TCP
        Assert.False(Check(new FakeFirewall(NetProfile.Public, Rule(false, NetProfile.Public, ports: "80,443"))).Blocked);
        Assert.True(Check(new FakeFirewall(NetProfile.Public, Rule(false, NetProfile.Public, ports: "7000-7200"))).Blocked);
        Assert.True(Check(new FakeFirewall(NetProfile.Public, Rule(false, NetProfile.Public, NetProtocol.Any))).Blocked);
        // the firewall switched off on this profile: nothing is blocked
        Assert.False(Check(new FakeFirewall(NetProfile.Public, Rule(false, NetProfile.Public)) { Off = NetProfile.Public }).Blocked);
    }

    [Fact]
    public void ProgramPathsMatchAsWindowsComparesThem()
    {
        var fw = new FakeFirewall(NetProfile.Public, Rule(false, NetProfile.Public, program: Link.ToUpperInvariant()));
        Assert.True(Check(fw).Blocked);
        var engine = new FakeFirewall(NetProfile.Private | NetProfile.Public,
            Rule(false, NetProfile.Private, NetProtocol.Udp, program: @"C:\Programs\Amadeus DMX\runtime\python.exe"));
        // any of the programs: the venv's launcher or the interpreter it starts
        var v = Firewall.Check(engine, [@"C:\data\python\Scripts\python.exe", @"C:\Programs\Amadeus DMX\runtime\python.exe"], NetProtocol.Udp, null);
        Assert.Equal(new Firewall.Verdict(true, NetProfile.Private), v);
    }

    [Fact]
    public void AllowingReplacesTheProgramsRulesWithTheInstallersOnes()
    {
        var commands = Firewall.AllowCommands("Amadeus Link", [Link], [(NetProtocol.Tcp, 7123), (NetProtocol.Udp, 9123)]);
        Assert.Equal(
        [
            $"advfirewall firewall delete rule name=all dir=in program=\"{Link}\"",
            $"advfirewall firewall add rule name=\"Amadeus Link\" dir=in action=allow protocol=TCP localport=7123 remoteip=localsubnet profile=any program=\"{Link}\"",
            $"advfirewall firewall add rule name=\"Amadeus Link\" dir=in action=allow protocol=UDP localport=9123 remoteip=localsubnet profile=any program=\"{Link}\"",
        ], commands);
        var engine = Firewall.AllowCommands("Amadeus DMX engine", [@"C:\py.exe"], [(NetProtocol.Udp, null)]);
        Assert.Equal("advfirewall firewall add rule name=\"Amadeus DMX engine\" dir=in action=allow protocol=UDP remoteip=localsubnet profile=any program=\"C:\\py.exe\"", engine[1]);
    }

    [Fact]
    public void TheWatchSaysWhereTheProgramIsBlocked()
    {
        var fw = new FakeFirewall(NetProfile.Public, Rule(false, NetProfile.Public));
        using var watch = new FirewallWatch("Amadeus Link", [Link], [(NetProtocol.Tcp, 7123)], () => fw);
        watch.Look();
        Assert.Equal(NetProfile.Public, watch.BlockedOn);
        using var unreadable = new FirewallWatch("Amadeus Link", [Link], [(NetProtocol.Tcp, 7123)], () => throw new InvalidOperationException());
        unreadable.Look();
        Assert.Null(unreadable.BlockedOn);  // can't read the rules: say nothing
    }

    [Fact]
    public void AVenvsPythonListensThroughTheOneItWasMadeFrom()
    {
        using var t = new TempWorkspace();
        Assert.Equal([t.Ws.Python], t.Ws.ListeningPythons());
        t.Write(".venv/pyvenv.cfg", "home = /opt/runtime\ninclude-system-site-packages = true\n");
        Assert.Equal([t.Ws.Python, Path.Combine("/opt/runtime", OperatingSystem.IsWindows() ? "python.exe" : "python3")], t.Ws.ListeningPythons());
    }
}

public class WindowsFirewallTests(Xunit.Abstractions.ITestOutputHelper output)
{
    [Fact]
    public void TheRealFirewallCanBeRead()
    {
        if (!OperatingSystem.IsWindows()) { output.WriteLine("not Windows: skipped"); return; }
        var fw = Firewall.ThisComputer();
        Assert.NotNull(fw);
        var rules = fw.Inbound();
        Assert.NotEmpty(rules);  // Windows comes with many
        output.WriteLine($"active: {fw.Active}, on: {string.Join(",", Enum.GetValues<NetProfile>().Where(p => p != 0 && fw.IsOn(p)))}");
        foreach (var r in rules.Where(r => r.Program.Contains("Amadeus", StringComparison.OrdinalIgnoreCase) || r.Program.EndsWith("python.exe", StringComparison.OrdinalIgnoreCase)))
            output.WriteLine($"{(r.Allow ? "allow" : "block")} {r.Profiles} {r.Protocol} {r.LocalPorts} {r.Program}");
    }
}
