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
}
