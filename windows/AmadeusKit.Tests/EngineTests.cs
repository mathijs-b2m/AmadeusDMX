// The engine supervisor with a stand-in for Python (a shell script that prints like the engine and stops on
// Ctrl-C), and the live feed against a WebSocket server of the test's own.
using System.Net;
using System.Net.WebSockets;
using System.Text;
using AmadeusKit;

namespace AmadeusKit.Tests;

public class EngineTests
{
    static async Task Until(Func<bool> done, double seconds = 10)
    {
        var end = DateTime.UtcNow.AddSeconds(seconds);
        while (!done() && DateTime.UtcNow < end) await Task.Delay(20);
        Assert.True(done(), "timed out");
    }

    [Fact]
    public async Task StartsLogsAndStopsCleanly()
    {
        if (OperatingSystem.IsWindows()) return;  // the stand-in is a shell script (Windows runs the real engine)
        using var t = new TempWorkspace().Engine();
        File.WriteAllText(Workspace.VenvPython(t.Root), """
            #!/bin/sh
            trap 'echo "KeyboardInterrupt"; exit 130' INT
            echo "args: $*"
            echo "Live mode on port 8765"
            printf 'half a line'
            printf ' and the rest\r\n'
            echo "an error here" 1>&2
            while true; do sleep 0.05; done
            """);
        Defaults.Standard = new Defaults(null, []);
        var engine = new EngineProcess("test");
        var lines = new List<string>();
        engine.OnLine = lines.Add;
        engine.Start(t.Ws, ["live", "--set", "x"], new Dictionary<string, string> { ["X"] = "1" }, readyWhen: "Live mode");
        Assert.True(engine.IsRunning);
        await Until(() => engine.State == EngineState.Running);
        await Until(() => engine.Log.Any(l => l.Text == "half a line and the rest"));
        Assert.Contains(engine.Log, l => l.Text == "args: -m amadeus live --set x");
        Assert.Equal("$ amadeus live --set x", engine.Log[0].Text);
        await Until(() => engine.Log.Any(l => l.IsError && l.Text == "an error here"));
        Assert.NotNull(engine.Pid);
        await engine.StopGracefully();
        await Until(() => engine.State == EngineState.Stopped);
        Assert.Equal("engine stopped", engine.LastLine);
        Assert.Null(engine.Pid);
        Assert.Contains("engine stopped", lines);
    }

    [Fact]
    public async Task AFailedEngineSaysWhy()
    {
        if (OperatingSystem.IsWindows()) return;
        using var t = new TempWorkspace().Engine();
        File.WriteAllText(Workspace.VenvPython(t.Root), "#!/bin/sh\necho 'Traceback: ValueError: no such set' 1>&2\nexit 1\n");
        var engine = new EngineProcess("test");
        engine.Start(t.Ws, ["live"]);
        await Until(() => engine.State.Kind == EngineStateKind.Failed);
        Assert.Equal("Traceback: ValueError: no such set", engine.State.Reason);
        Assert.Equal("engine exited with code 1", engine.LastLine);
    }

    [Fact]
    public void AMissingPythonFailsAtOnce()
    {
        using var t = new TempWorkspace();
        var engine = new EngineProcess("test");
        engine.Start(t.Ws, ["live"]);
        Assert.Equal(EngineStateKind.Failed, engine.State.Kind);
        Assert.StartsWith("could not start", engine.LastLine);
    }

    [Fact]
    public async Task TheFeedFollowsTheEngine()
    {
        var port = FreePort();
        using var http = new HttpListener();
        http.Prefixes.Add($"http://127.0.0.1:{port}/");
        http.Start();
        var received = new TaskCompletionSource<string>();
        var paths = new List<string>();
        var server = Task.Run(async () =>
        {
            while (http.IsListening)
            {
                HttpListenerContext ctx;
                try { ctx = await http.GetContextAsync(); } catch { return; }
                paths.Add(ctx.Request.Url!.AbsolutePath);
                var ws = (await ctx.AcceptWebSocketAsync(null)).WebSocket;
                await ws.SendAsync(Encoding.UTF8.GetBytes("""{"type": "hello", "track": "Deck 1: song.mp3", "bpm": 126}"""), WebSocketMessageType.Text, true, default);
                var buf = new byte[4096];
                _ = Task.Run(async () =>
                {
                    var r = await ws.ReceiveAsync(buf, default);
                    received.TrySetResult(Encoding.UTF8.GetString(buf, 0, r.Count));
                });
                for (var i = 0; i < 400 && ws.State == WebSocketState.Open; i++)
                {
                    var frame = FormattableString.Invariant($$"""{"type": "frame", "t": {{i * 0.025}}, "phrase": {{i / 40}}, "fx": [[1, 1, 0, 0, 0, 0.5, 0.5]], "decks": [{"deck": 1, "track": "song", "vol": 1, "play": true, "ready": true}]}""");
                    try { await ws.SendAsync(Encoding.UTF8.GetBytes(frame), WebSocketMessageType.Text, true, default); }
                    catch (WebSocketException) { break; }
                    await Task.Delay(25);
                }
            }
        });
        var feed = new LiveFeed(new Uri($"ws://127.0.0.1:{port}"));
        var changed = new List<string>();
        feed.PropertyChanged += (_, e) => { lock (changed) changed.Add(e.PropertyName!); };
        feed.Start();
        await Until(() => feed.Hello is not null && feed.LatestFrame is not null);
        Assert.Equal(FeedState.Connected, feed.State);
        Assert.Equal("song", feed.Hello!.Title);
        Assert.True(feed.IsReceiving);
        Assert.NotNull(feed.LatestFullFrame);
        await Until(() => feed.Decks.Count == 1 && feed.Phrase >= 1, 15);
        feed.Send(new { type = "arc", knob = new { intensity = 0.7 } });
        Assert.Equal("""{"type":"arc","knob":{"intensity":0.7}}""", await received.Task.WaitAsync(TimeSpan.FromSeconds(5)));
        await Until(() => feed.Fps > 10, 5);
        // Perform mode: the lite feed
        feed.Lite = true;
        Assert.Null(feed.LatestFrame);  // never a stale full frame for the renderer
        await Until(() => paths.Contains("/lite"));
        feed.Stop();
        Assert.Equal(FeedState.Idle, feed.State);
        lock (changed) Assert.Contains(nameof(LiveFeed.Hello), changed);
        http.Stop();
    }

    static int FreePort()
    {
        var l = new System.Net.Sockets.TcpListener(IPAddress.Loopback, 0);
        l.Start();
        var port = ((IPEndPoint)l.LocalEndpoint).Port;
        l.Stop();
        return port;
    }
}
