// A DJ software Amadeus Link reads itself, all the way to the engine: Mixxx's SysEx in, the kit's reader, the
// plugin's packet, LinkNet, and the engine's own receiver (amadeus/show/link.py RemoteListener) on the other end,
// which fetches the track and lists the deck as Link read it. Skipped without the engine's Python (check.sh finds it).
using System.Diagnostics;
using System.Globalization;
using AmadeusKit.DJ;
using Microsoft.Data.Sqlite;
using Xunit.Abstractions;

namespace AmadeusKit.Tests;

public class ReaderLinkTests(ITestOutputHelper output)
{
    static readonly byte[] DeckMessage = [240, 125, 68, 76, 1, 1, 2, 15, 4, 0, 4, 12, 51, 0, 8, 74, 81, 0, 2, 88, 68, 64, 62, 71, 104, 0, 7, 92,
                                          36, 102, 50, 0, 77, 247];

    [Fact]
    public async Task MixxxReachesTheEnginesReceiver()
    {
        if (LinkTests.EnginePython() is not { } python) { output.WriteLine("no engine Python: skipped"); return; }
        var root = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../.."));
        using var w = new TempWorkspace();
        w.Write("Music/Artist - Title.mp3", "not really music");
        var file = Path.Combine(w.Root, "Music", "Artist - Title.mp3");
        var settings = Path.Combine(w.Root, "Mixxx");
        Directory.CreateDirectory(settings);
        using (var c = new SqliteConnection($"Data Source={Path.Combine(settings, "mixxxdb.sqlite")};Pooling=False"))
        {
            c.Open();
            using var cmd = c.CreateCommand();
            cmd.CommandText = """
                CREATE TABLE library (id INTEGER, artist TEXT, title TEXT, bpm REAL, samplerate INTEGER, duration REAL, location INTEGER, mixxx_deleted INTEGER);
                CREATE TABLE track_locations (id INTEGER, location TEXT);
                INSERT INTO track_locations VALUES (1, $file);
                INSERT INTO library VALUES (1, 'Artist', 'Title', 126.5, 44100, $len, 1, 0);
                """;
            cmd.Parameters.AddWithValue("$file", file);
            cmd.Parameters.AddWithValue("$len", 18_000_000 / 2.0 / 44100);
            cmd.ExecuteNonQuery();
        }
        var reader = new MixxxReader(null, settings: settings, resolver: new Resolver([Path.Combine(w.Root, "Music")]));

        using var net = new LinkNet { Code = "1357", Advertise = null };
        var served = 0;
        net.OnServed = () => Interlocked.Increment(ref served);
        net.StartService(0, "test");
        while (net.ServicePort == 0) await Task.Delay(10);
        var script = $$"""
            import sys, time
            from pathlib import Path
            from amadeus.show.link import RemoteListener
            r = RemoteListener("127.0.0.1", {{net.ServicePort}}, "1357", Path(sys.argv[1]) / "cache")
            print("paired", flush=True)
            end = time.time() + 10
            while time.time() < end and not r.decks:
                time.sleep(0.05)
            print("decks", [(d.deck, d.title, d.artist, round(d.length, 2), d.bpm, round(d.vol, 3)) for d in r.decks.values()], flush=True)
            """;
        var psi = new ProcessStartInfo(python) { WorkingDirectory = root, RedirectStandardOutput = true, RedirectStandardError = true };
        psi.ArgumentList.Add("-c");
        psi.ArgumentList.Add(script);
        psi.ArgumentList.Add(w.Root);
        psi.Environment["AMADEUS_DATA"] = w.Root;
        using var p = Process.Start(psi)!;
        string? line;
        do line = await p.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(30));
        while (line is not null && line != "paired");
        if (line is null && (await p.StandardError.ReadToEndAsync()).Contains("ModuleNotFoundError"))
        {
            output.WriteLine("the engine's Python lacks its packages: skipped");
            return;
        }
        Assert.Equal("paired", line);
        // the pump Link runs (LinkServer.SetSoftware): Mixxx's script 50 times a second, the decks passed on
        var feeding = Task.Run(async () =>
        {
            var start = Clock.Monotonic();
            for (var i = 0; i < 400 && !p.HasExited; i++)
            {
                var now = Clock.Monotonic();
                reader.Message(DeckMessage, now);
                var decks = reader.Decks(now);
                if (decks.Count > 0) net.Send(Packet.Make(reader.App, decks, now, start));
                await Task.Delay(20);
            }
        });
        string? result;
        do result = await p.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(15));
        while (result is not null && !result.StartsWith("decks", StringComparison.Ordinal));
        await feeding;
        if (!p.HasExited) p.Kill();
        output.WriteLine(await p.StandardError.ReadToEndAsync());
        var len = Math.Round(18_000_000 / 2.0 / 44100, 2).ToString(CultureInfo.InvariantCulture);
        Assert.Equal($"decks [(2, 'Title', 'Artist', {len}, 126.5, 0.8)]", result);
        Assert.True(served > 0);  // the engine fetched the track Mixxx played
    }
}
