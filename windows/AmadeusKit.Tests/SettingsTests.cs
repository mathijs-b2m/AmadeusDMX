// The app's own settings (UserDefaults' counterpart), the credentials, and the rules for updates.
using AmadeusKit;

namespace AmadeusKit.Tests;

public class SettingsTests
{
    [Fact]
    public void DefaultsAreSavedAndTheCommandLineWins()
    {
        using var t = new TempWorkspace();
        var file = Path.Combine(t.Root, "settings.json");
        var d = new Defaults(file, []);
        Assert.Null(d.String("section"));
        Assert.False(d.Bool("wizard"));
        d.Set("section", "rig");
        d.Set("playFrom", 12.5);
        d.Set("muted", true);
        var again = new Defaults(file, ["AmadeusDMX.exe", "-section", "sets", "-startLive", "YES", "-n", "3"]);
        Assert.Equal("sets", again.String("section"));
        Assert.Equal(12.5, again.Double("playFrom"));
        Assert.True(again.Bool("muted"));
        Assert.True(again.Bool("startLive"));
        Assert.Equal(3, again.Integer("n"));
        Assert.Null(again.BoolIfSet("sendArtNet"));
        again.Remove("muted");
        Assert.False(new Defaults(file, []).Bool("muted"));
        Assert.Equal("rig", new Defaults(file, []).String("section"));  // the command line is never saved
    }

    [Fact]
    public void CredentialsCanBeWrittenReadAndDeleted()
    {
        const string service = "io.github.amadeusdmx.tests";
        Credentials.Write(service, "KEY", "sk-test");
        Assert.Equal("sk-test", Credentials.Read(service, "KEY"));
        Credentials.Write(service, "KEY", "");
        Assert.Null(Credentials.Read(service, "KEY"));
    }

    sealed class FakeUpdater : IUpdater
    {
        public bool CanCheck { get; set; } = true;
        public bool ChecksAutomatically { get; set; }
        public bool InstallsAutomatically { get; set; }
        public DateTimeOffset? LastChecked => null;
        public int Checks;
        public void CheckForUpdates() => Checks++;
        public int Refreshes, Installs, Cancels;
        public void Refresh() => Refreshes++;
        public void InstallNewest() => Installs++;
        public void CancelInstall() => Cancels++;
        public event Action? CanCheckChanged;
        public void Change(bool can) { CanCheck = can; CanCheckChanged?.Invoke(); }
    }

    [Fact]
    public void UpdatesNeverInterruptAShow()
    {
        var busy = true;
        var backend = new FakeUpdater();
        var u = new Updates(backend, new Defaults(null, [])) { IsBusy = () => busy };
        Assert.True(u.IsAvailable);
        Assert.False(u.MayCheck(inBackground: true));
        Assert.True(u.MayCheck(inBackground: false));  // you asked: it checks
        var installed = 0;
        Assert.True(u.ShouldPostponeInstall(() => installed++));
        Assert.True(u.WaitingForIdle);
        busy = false;
        u.BecameIdle();
        Assert.Equal(1, installed);
        Assert.False(u.WaitingForIdle);
        u.BecameIdle();
        Assert.Equal(1, installed);
        Assert.False(u.ShouldPostponeInstall(() => installed++));
        backend.Change(false);
        Assert.False(u.CanCheck);
        Assert.False(new Updates(null).IsAvailable);
    }

    [Fact]
    public void UpdatesAskOnTheSecondLaunchOnce()
    {
        var defaults = new Defaults(null, []);
        var backend = new FakeUpdater();
        Assert.False(new Updates(backend, defaults).ShouldAskToCheckAutomatically());
        var second = new Updates(backend, defaults);
        Assert.True(second.ShouldAskToCheckAutomatically());
        second.Answer(true);
        Assert.True(backend.ChecksAutomatically);
        Assert.False(new Updates(backend, defaults).ShouldAskToCheckAutomatically());
        Assert.False(new Updates(null, new Defaults(null, [])).ShouldAskToCheckAutomatically());
    }

    [Fact]
    public void UpdatesShowTheNewestAndInstallItWithOneClick()
    {
        var now = DateTimeOffset.UnixEpoch;
        var backend = new FakeUpdater();
        var u = new Updates(backend, new Defaults(null, []), () => now);
        Assert.Equal(UpdateState.Unknown, u.State);
        u.Refresh();
        Assert.Equal(UpdateState.Checking, u.State);
        Assert.Equal(1, backend.Refreshes);
        u.Refresh(force: true);  // one at a time
        Assert.Equal(1, backend.Refreshes);
        u.InstallNewest();  // nothing found yet: nothing to install
        Assert.Equal(0, backend.Installs);

        u.Report(UpdateState.UpToDate, "1.0.5");
        Assert.Equal("1.0.5", u.Newest);
        u.Refresh();  // checked a moment ago
        Assert.Equal(1, backend.Refreshes);
        now += TimeSpan.FromMinutes(6);
        u.Refresh();
        Assert.Equal(2, backend.Refreshes);

        u.Report(UpdateState.Available, "1.0.6");
        u.InstallNewest();
        Assert.Equal(1, backend.Installs);
        Assert.Equal(UpdateState.Downloading, u.State);
        Assert.Equal("1.0.6", u.Newest);
        u.Refresh(force: true);  // never while it downloads
        Assert.Equal(2, backend.Refreshes);
        var redraws = 0;
        u.PropertyChanged += (_, _) => redraws++;
        u.Report(UpdateState.Downloading, "1.0.6", 0.500);
        u.Report(UpdateState.Downloading, "1.0.6", 0.503);  // a chunk: not worth a redraw
        Assert.Equal(0.5, u.Progress);
        u.Report(UpdateState.Downloading, "1.0.6", 0.51);
        Assert.Equal(0.51, u.Progress);
        Assert.True(redraws <= 2);
        u.CancelInstall();
        Assert.Equal(1, backend.Cancels);

        // installing during a show waits, and says which version waits
        var busy = true;
        u.IsBusy = () => busy;
        Assert.True(u.ShouldPostponeInstall(() => { }));
        Assert.Equal(UpdateState.Installing, u.State);
        Assert.Equal("1.0.6", u.Newest);

        var none = new Updates(null, new Defaults(null, []));
        none.Refresh();
        none.InstallNewest();
        Assert.Equal(UpdateState.Unknown, none.State);
        Assert.False(string.IsNullOrEmpty(none.Version));
    }
}
