# Amadeus DMX for Windows: how the port is built

The Windows apps are native ports of the Mac apps in `mac/`: same pages, same behaviour, same engine. When in
doubt, the Swift code is the spec: port what it does, file by file, and keep the names (a Swift `RigEditorModel`
becomes a C# `RigEditorModel`), so a change on one side is easy to find on the other.

## Stack

- **.NET 10** (`net10.0` for the shared library, `net10.0-windows10.0.22621.0` for the apps), C# with
  `<Nullable>enable</Nullable>`, file-scoped namespaces.
- **WinUI 3** (Windows App SDK 2.5.1), **unpackaged** (`WindowsPackageType=None`) and self-contained in release
  builds. **No XAML files**: every view is built in C# (see "Views in code" below). This keeps the apps
  compilable on a Mac (`windows/check.sh`), which is where most of the work happens.
- **Direct3D 11** through **Vortice.Windows 3.8.3** (`Vortice.Direct3D11`, `Vortice.DXGI`, `Vortice.D3DCompiler`)
  for the 3D stage, in a `SwapChainPanel`. Shaders are HLSL ports of `mac/Sources/AmadeusDMX/Render/Shaders.swift`,
  compiled at startup with `D3DCompiler` (shipped with Windows).
- **x64 only.** Windows 10 22H2 / Windows 11.

## Layout

```
windows/
  AmadeusWindows.sln
  check.sh                  Mac: compile everything (the apps without the Windows-only packaging steps) + run tests
  make-icons.py             the apps' .ico from docs/logo (the .ico files are committed)
  build.ps1                 Windows: build the apps; -Release puts the engine and its Python inside; -Installer too
  bundle-engine.ps1         Windows: python-build-standalone + requirements-app.txt + the engine (like mac/bundle-engine.sh)
  installer/                Inno Setup scripts for both installers
  AmadeusKit/               net10.0 class library: the port of mac/Sources/AmadeusKit (no WinUI, no Windows APIs
                            unless behind OperatingSystem.IsWindows()), testable on a Mac
  AmadeusKit.Tests/         xUnit, runs on a Mac (`dotnet test`)
  AmadeusDMX/               the app (port of mac/Sources/AmadeusDMX), grouped by feature like the Swift folders
  AmadeusLink/              the DJ laptop's companion (port of mac/Sources/AmadeusLink); it carries the VirtualDJ
                            plugin as vdj\AmadeusLink.dll (AmadeusLink.dll beside the exe is the app itself)
```

## Mac → Windows mapping

| Mac | Windows |
|---|---|
| SwiftUI view | C# class building WinUI controls in code (`Views in code`) |
| `@Observable` / `ObservableObject` model | class implementing `INotifyPropertyChanged` (`AmadeusKit.Observable` base with `Set(ref field, value)`) |
| Metal (`StageRenderer`, `Shaders.swift`) | Direct3D 11 + HLSL (`AmadeusDMX/Render`) |
| Keychain | Windows Credential Manager (`CredWrite`/`CredRead`, P/Invoke) |
| Bonjour (`NWBrowser`, `NWListener`) | `DnsServiceBrowse` / `DnsServiceRegister` (dnsapi.dll, Windows 10+) |
| Sparkle | NetSparkleUpdater (same appcast format, same Ed25519 key) |
| `~/Library/Application Support/Amadeus DMX` | `%LOCALAPPDATA%\Amadeus DMX` (sets, rigs, settings, packs, the cache: big, so not roaming) |
| Accessibility (djay) | UI Automation (djay Pro for Windows) |
| CoreMIDI virtual port (Mixxx) | Windows MIDI Services loopback endpoint, else an existing port such as loopMIDI |
| menu bar extra (Link) | notification-area icon (`Shell_NotifyIcon`) + small window |
| app menu / commands | `MenuBar` in the window's title area + `KeyboardAccelerator`s (⌘ → Ctrl, ⌥ → Alt) |
| `.app` with the engine inside | `C:\Program Files\Amadeus DMX\` with `engine\` and `runtime\` beside the exe |

## Swift → C# in the kit

- `@Observable` class → `Observable` subclass: `public T Prop { get => _p; private set => Set(ref _p, value); }`; a
  computed property is raised with `Changed(nameof(…))` when what it reads changes. Models live on the UI thread;
  work from other threads comes back through `UIThread.Post` (the SynchronizationContext the model was made on).
- Codable structs → records with a static `From(JsonElement)` written with the kit's `J` helpers, which keep
  Swift's rules (`J.Req` = `decode`, `J.Val`/`J.Ref` = `decodeIfPresent`, `J.Try` = `try?`). `JSONValue` is
  Swift's `JSONValue` (immutable, compared by value); `[String: JSONValue]` is `Dictionary<string, JSONValue>`.
- Swift value types that views edit (RigDocument, PlacedFixture, Truss, Zone) are classes here: `Clone()` first.
- `enum … case failed(String)` → `readonly record struct (Kind, Reason)` (EngineState, ShowState).
- `UserDefaults` → `Defaults.Standard` (same keys; `-key value` on the command line overrides, as on the Mac).
  Keychain → `Credentials`. `URL` → `string` paths. Numbers in files and on the wire: always InvariantCulture.

## Views in code

WinUI controls are built with the helpers in `AmadeusDMX/Shared/UI.cs` (read its header first): `UI.VStack` /
`UI.HStack` (SwiftUI's spacing, `UI.Spacer()`, `.Grow()`, `.Fill()`), `UI.Text("…", Font.Headline)`,
`UI.Label(symbol, title)`, `UI.Icon(sfSymbol)` (SF Symbols names, mapped in `Symbols.cs`), `UI.Button`,
`UI.Toggle`, `UI.Picker`, `UI.Segmented`, `UI.MenuButton(label, () => UI.Menu(…))`, `UI.Card`, `UI.Section`,
`UI.Unavailable`; modifiers chain (`.Padding(12).Secondary().Tooltip("…")`); colours are `Tint.Green` etc.
(the Mac's), theme brushes `Theme.Brush("…")`. State: `.Bind(model, nameof(Model.Prop), el => …)` (several:
`[nameof(A), nameof(B)]`; any: `.BindAll`), or `UI.Live(model, () => …)` to rebuild a part when the model changes.
A page is a class with a `Build()` that returns its root `FrameworkElement`. Keep views thin; logic lives in the
models (and in AmadeusKit when it isn't UI). Amadeus Link compiles the same `Shared/` files.

## Rules

- The engine is the same Python package on both systems. Platform differences in Python go behind
  `sys.platform == "win32"` checks in the module that needs them; nothing Mac-only may break on Windows.
- No ban2media traces, no personal names or paths; bundle-like ids are `io.github.amadeusdmx.*`.
- Every string the Mac app shows keeps its wording on Windows, with Windows terms (Settings, Ctrl, File
  Explorer, the notification area).
- Never write into the installed program folder; user data goes to `%LOCALAPPDATA%\Amadeus DMX`.
