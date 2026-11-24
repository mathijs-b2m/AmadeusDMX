// The LED wall's resolution, as its processor maps it (mac/.../Rig/Editor/Inspectors.swift, ScreenPixelsRow): it sets
// the wall's shape (and the animations' layout). Typed in pixels, or worked out from its panels.
namespace AmadeusDMX;

public static class ScreenPixelsRow
{
    static readonly int[] PanelSizes = [64, 96, 104, 112, 128, 144, 160, 168, 176, 192, 208, 256];

    public static FrameworkElement Build(RigEditorModel editor)
    {
        var following = false;   // values set from the document aren't the user's
        NumberBox Field(string placeholder, Func<(int W, int H)?, int?> get, Action<int> set)
        {
            var box = new NumberBox
            {
                PlaceholderText = placeholder, Minimum = 1, Maximum = 100_000, SmallChange = 1, Width = 76,
                SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Hidden,
                NumberFormatter = new Windows.Globalization.NumberFormatting.DecimalFormatter { FractionDigits = 0, IsGrouped = false },
            };
            box.ValueChanged += (b, e) =>
            {
                if (following || double.IsNaN(e.NewValue)) return;
                var v = Math.Max(1, (int)Math.Round(e.NewValue, MidpointRounding.AwayFromZero));
                if (v != get(editor.Doc.ScreenPixels)) set(v);
            };
            box.Bind(editor, nameof(RigEditorModel.Version), b =>
            {
                following = true;
                try { b.Value = get(editor.Doc.ScreenPixels) is { } v ? v : double.NaN; }
                finally { following = false; }
            });
            return box;
        }
        var w = Field(L("W"), p => p?.W, v => editor.SetScreenPixels((v, editor.Doc.ScreenPixels?.H ?? Math.Max(1, v * 9 / 16))));
        var h = Field(L("H"), p => p?.H, v => editor.SetScreenPixels((editor.Doc.ScreenPixels?.W ?? Math.Max(1, v * 16 / 9), v)));

        // from its panels: how many across and high, and one panel's pixels
        int cols = 6, rows = 3, panel = editor.ScreenPanelPx ?? 128;
        var set = UI.Button("", () => { });
        void Label() => set.Content = L("Set {0} × {1}", cols * panel, rows * panel);
        set.Click += (_, _) => editor.SetScreenPixels((cols * panel, rows * panel), panel);
        Label();
        var panelPicker = UI.Picker(PanelSizes.Contains(panel) ? PanelSizes : [.. PanelSizes, panel], panel, p => $"{p} px", p => { panel = p; Label(); });
        var flyout = new Flyout
        {
            Content = UI.VStack(10,
                Form.Stepper(cols, 1, 64, n => L("{0} panels across", n), n => { cols = n; Label(); }),
                Form.Stepper(rows, 1, 64, n => L("{0} panels high", n), n => { rows = n; Label(); }),
                Form.Row(L("Panel"), panelPicker),
                set).Frame(width: 260),
        };
        var fromPanels = UI.IconButton("square.grid.3x2", L("From its panels: how many across and high, and one panel's pixels"), () => { }).Flyout(flyout);

        var fields = UI.HStack(4, w, UI.Text("×").Secondary(), h, fromPanels);
        fields.Alignment = 0.5;
        var row = UI.HStack(8, UI.Text(L("LED wall pixels")).Wrap().Grow(), fields);
        row.Alignment = 0.5;
        return row.Bind(editor, nameof(RigEditorModel.Version), r => r.Tooltip(editor.Doc.ScreenPixels is null
            ? L("Not given: the wall is 16:9. Its pixels give it its shape, and the LED Wall Output and the hang sheet use them.")
            : L("The wall's resolution as its LED processor maps it: its shape follows")));
    }
}
