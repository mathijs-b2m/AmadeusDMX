// The engine page: the engine's log (mac/Sources/AmadeusDMX/Engine/EngineView.swift). For now its last line; the
// full log view is being ported.
namespace AmadeusDMX;

public sealed class EngineView(AppModel model)
{
    public FrameworkElement Build() =>
        UI.VStack(12,
            UI.Text("Engine", Font.Title2),
            UI.Text("", Font.Mono).Selectable().Wrap()
                .Bind(model.Engine, nameof(EngineProcess.LastLine), t => t.Text = model.Engine.LastLine.Length == 0 ? "No output yet." : model.Engine.LastLine)
        ).Padding(20);
}
