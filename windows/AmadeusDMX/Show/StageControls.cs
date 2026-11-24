// Camera presets, flying through the room, the LED wall scene, zones, haze and exposure.
namespace AmadeusDMX;

public sealed class StageControls(StageSettings stage, AppModel model)
{
    public FrameworkElement Build()
    {
        var hint = ShowUI.Glass(UI.Text(L("WASD move · Q/E down/up · drag to look · Shift faster · Esc lands"), Font.Caption).Secondary(), padding: 0, corner: 14);
        hint.Padding = new Thickness(12, 8, 12, 8);
        hint.Bind(stage, nameof(StageSettings.Fly), h => h.Visible(stage.Fly));

        var row = UI.HStack(8, hint);
        foreach (var (raw, symbol) in StageSettings.Presets)
            row.Children.Add(Glassy(UI.IconButton(symbol, StageSettings.PresetTitle(raw), () => stage.Preset = raw), () => stage.Preset == raw, nameof(StageSettings.Preset)));
        row.Children.Add(Glassy(UI.IconButton("figure.walk.motion",
            L("Fly through the room (F): WASD or arrows move, Q/E down/up, drag to look around, scroll or pinch to move, Shift faster. Without flying: WASD still walks, +/− zoom."),
            () => stage.Fly = !stage.Fly), () => stage.Fly, nameof(StageSettings.Fly)));
        row.Children.Add(Glassy(UI.IconButton("cube.transparent", StageRoom.Help, () => StageRoom.Shared.On = !StageRoom.Shared.On),
            () => StageRoom.Shared.On, nameof(StageRoom.On), StageRoom.Shared));

        var wall = new Button { Padding = new Thickness(8, 6, 8, 6) }.Tooltip(L("LED wall: the director's choice, or try one scene; and the LED Wall Output"));
        var wallMenu = new MenuFlyout();
        wallMenu.Opening += (_, _) =>
        {
            wallMenu.Items.Clear();
            var hasWall = model.StageInput()?.Screen ?? false;   // without one, only the output
            foreach (var (raw, title, symbol) in StageSettings.WallScenes)
            {
                var item = UI.Choice(title, "wall", stage.WallScene == raw, () => stage.WallScene = raw, symbol);
                item.IsEnabled = hasWall;
                wallMenu.Items.Add(item);
            }
            wallMenu.Items.Add(UI.Separator());
            wallMenu.Items.Add(UI.Item(L("LED Wall Output…"), () => LEDWallOutputWindow.Open(model), "rectangle.on.rectangle"));
        };
        wall.Flyout = wallMenu;
        wall.Bind(stage, nameof(StageSettings.WallScene), b => b.Content = UI.Icon(stage.WallScene == "auto" ? "tv" : stage.WallSymbol, 14));
        row.Children.Add(wall);

        row.Children.Add(Glassy(UI.IconButton("square.dashed", L("Show the zones: where beams may (not) go"), () => model.ShowZones = !model.ShowZones),
                                () => model.ShowZones, nameof(AppModel.ShowZones), model));

        var haze = UI.Slider(stage.Haze, 0, 1.5, v => stage.Haze = v);
        haze.Header = L("Haze");
        var exposure = UI.Slider(stage.Exposure, 0.4, 2, v => stage.Exposure = v);
        exposure.Header = L("Exposure");
        var orbit = UI.Check(L("Slow orbit"), stage.AutoOrbit, v => stage.AutoOrbit = v);
        var look = new Flyout
        {
            Content = UI.VStack(12, haze, exposure, orbit).Frame(width: 260),
            Placement = Microsoft.UI.Xaml.Controls.Primitives.FlyoutPlacementMode.Top,
        };
        look.Opening += (_, _) =>
        {
            haze.SetValueQuietly(stage.Haze);
            exposure.SetValueQuietly(stage.Exposure);
            orbit.IsChecked = stage.AutoOrbit;
        };
        row.Children.Add(UI.IconButton("cloud.fog", L("Haze and exposure"), () => { }).Flyout(look));
        return row;
    }

    /// A glass button that is prominent while `on` (SwiftUI's `.glassProminent` against `.glass`).
    Button Glassy(Button b, Func<bool> on, string property, System.ComponentModel.INotifyPropertyChanged? owner = null)
    {
        var plain = b.Style;
        return b.Bind(owner ?? stage, property, x =>
        {
            if (on()) x.Prominent(); else x.Style = plain;
        });
    }
}
