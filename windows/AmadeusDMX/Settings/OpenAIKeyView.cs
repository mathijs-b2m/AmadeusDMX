// The OpenAI key for the AI director: which key the engine uses, and entering, checking or removing your own.
// Settings › Director and the wizard's engine step share it. The key goes into Windows Credential Manager only
// (mac/Sources/AmadeusDMX/Settings/OpenAIKeyView.swift).
using System.Net.Http.Headers;

namespace AmadeusDMX;

public sealed class OpenAIKeyView(AppModel model)
{
    static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(10) };

    readonly PasswordBox _entry = new() { PlaceholderText = "Paste your key: sk-…" };
    KeySource _source = KeySource.Current(Keychain.OpenAIKey, model.Workspace);
    (bool Ok, string Text)? _check;
    bool _checking;
    string? _note;
    readonly ContentControl _inUse = Host(), _warning = Host(), _buttons = Host(), _result = Host();

    static ContentControl Host() => new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };

    string Trimmed => _entry.Password.Trim();

    public FrameworkElement Build()
    {
        _entry.PasswordChanged += (_, _) => { _check = null; _note = null; Refresh(); };
        _entry.KeyDown += (_, e) => { if (e.Key == Windows.System.VirtualKey.Enter) { Save(); e.Handled = true; } };
        // the field stays put (it keeps its focus while you type); the parts around it follow
        var root = UI.VStack(10, _inUse, _entry, _warning, _buttons, _result);
        root.Loaded += (_, _) => { _source = KeySource.Current(Keychain.OpenAIKey, model.Workspace); Refresh(); };
        Refresh();
        return root;
    }

    void Refresh()
    {
        var t = Trimmed;
        var save = UI.Button("Save", Save).Disabled(!t.StartsWith("sk-", StringComparison.Ordinal));
        if (t.StartsWith("sk-", StringComparison.Ordinal)) save.Prominent();
        var check = UI.Button(_checking ? "Checking…" : "Check Key", () => _ = Verify())
            .Disabled(_checking || (t.Length == 0 && _source.Where == KeySource.Kind.None));
        _inUse.Content = InUse();
        _warning.Content = t.Length > 0 && !t.StartsWith("sk-", StringComparison.Ordinal)
            ? Form.Note("exclamationmark.triangle", "OpenAI keys start with sk-", Tint.Orange) : null;
        _buttons.Content = UI.HStack(8,
            save,
            check,
            _source.Where == KeySource.Kind.Stored ? UI.Button("Remove", Remove).Foreground(Tint.Red) : null,
            UI.Spacer(),
            UI.Link("Get a key", () => Dialogs.OpenURL("https://platform.openai.com/api-keys")).Font(Font.Callout));
        _result.Content = UI.VStack(6,
            _check is { } c ? Form.Note(c.Ok ? "checkmark.circle.fill" : "xmark.octagon.fill", c.Text, c.Ok ? Tint.Green : Tint.Red) : null,
            _note is { } n ? UI.Text(n, Font.Callout).Secondary().Wrap() : null);
    }

    UIElement InUse() => _source.Where switch
    {
        KeySource.Kind.Stored => Form.Note("key.fill", $"In use: your key {KeySource.Masked(_source.Key)}, from Windows Credential Manager", null, Font.Body),
        KeySource.Kind.EnvFile => Form.Note("doc.text", "In use: the key in the engine folder's .env. A key saved here is used instead.", null, Font.Body),
        _ => Form.Note("key", "No key: the rule-based director lights the show. Add a key to let the AI decide.", null, Font.Body),
    };

    void Save()
    {
        if (!Trimmed.StartsWith("sk-", StringComparison.Ordinal)) return;
        Keychain.OpenAIKey = Trimmed;
        _entry.Password = "";
        Changed("Saved.");
        _ = Verify(Keychain.OpenAIKey);
    }

    void Remove()
    {
        Keychain.OpenAIKey = null;
        Changed(model.Workspace?.HasEnvKey == true ? "Removed. The engine folder's .env key is used again." : "Removed.");
    }

    void Changed(string text)
    {
        _source = KeySource.Current(Keychain.OpenAIKey, model.Workspace);
        _check = null;
        _ = model.RestartSetupService();  // the setup page shows which directors can run: the new key
        _note = text + (model.EngineRunning ? " The running show keeps the old key until it is started again." : "");
        Refresh();
    }

    /// Asks OpenAI whether it accepts the key (the one typed, else the one in use): lists the models, nothing more.
    async Task Verify(string? given = null)
    {
        var key = given ?? (Trimmed.Length == 0 ? (_source.Where == KeySource.Kind.Stored ? _source.Key : null) : Trimmed);
        if (key is null) { _check = (false, "The .env key is checked when the engine uses it."); Refresh(); return; }
        _checking = true;
        Refresh();
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Get, "https://api.openai.com/v1/models");
            req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", key);
            using var resp = await Http.SendAsync(req);
            _check = (int)resp.StatusCode switch
            {
                200 => (true, "OpenAI accepts this key."),
                401 => (false, "OpenAI doesn't accept this key (wrong, revoked, or from another account)."),
                429 => (true, "The key works, but its quota or rate limit is reached for now."),
                var code => (false, $"OpenAI answered {code}. Try again later."),
            };
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
        {
            _check = (false, $"Couldn't reach OpenAI: {e.Message}");
        }
        _checking = false;
        Refresh();
    }
}
