// "Start with a DJ laptop": VirtualDJ runs on another computer with Amadeus Link; pick it, type its code.
using System.ComponentModel;

namespace AmadeusDMX;

public sealed class DJLinkSheet(AppModel model)
{
    string? _chosen;
    string _code = "";
    readonly Stack _list = UI.VStack(6);
    ContentDialog? _dialog;

    /// Opens the sheet over the window (the toolbar's Start menu: "Start with a DJ Laptop…").
    public static async void Present(AppModel model, MainWindow window)
    {
        if (window.Root is null) return;
        await new DJLinkSheet(model).Show(window.Root);
    }

    async Task Show(XamlRoot root)
    {
        var dialog = new ContentDialog
        {
            XamlRoot = root,
            Content = Build(),
            PrimaryButtonText = "Connect and Start",  // the default button: Enter
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
            IsPrimaryButtonEnabled = false,
        };
        dialog.Resources["ContentDialogMaxWidth"] = 600.0;
        _dialog = dialog;
        void Found(object? s, PropertyChangedEventArgs e)
        {
            if (e.PropertyName is null or nameof(LinkBrowser.Found)) Changed();
        }
        model.Djs.PropertyChanged += Found;
        model.Djs.Start();
        Changed();
        try
        {
            if (await dialog.ShowAsync() == ContentDialogResult.Primary && _chosen is { } dj && PairingCode.CanConnect(dj, _code))
                model.StartLive(dj: dj, code: _code);
        }
        finally
        {
            model.Djs.PropertyChanged -= Found;
            model.Djs.Stop();
        }
    }

    FrameworkElement Build()
    {
        var header = UI.HStack(12,
            UI.Icon("laptopcomputer.and.arrow.down", Theme.Size(Font.LargeTitle) + 6).Foreground(Tint.Accent),
            UI.VStack(2,
                UI.Text("Start with a DJ Laptop", Font.Title2).Leading(),
                UI.Text("The DJ software runs on the DJ’s laptop with Amadeus Link switched on. The show here follows that mix.", Font.Callout)
                    .Secondary().Wrap().Leading()).Grow());

        var code = UI.Field("0000", _code, _ => { });
        code.FontSize = Theme.Size(Font.Title3);
        code.Width = 90;
        code.MaxLength = 4;
        code.TextChanged += (_, _) =>
        {
            var clean = PairingCode.Clean(code.Text);
            if (clean != code.Text)
            {
                var at = Math.Min(code.SelectionStart, clean.Length);
                code.Text = clean;
                code.SelectionStart = at;
            }
            _code = clean;
            Enable();
        };

        return UI.VStack(16,
            header,
            UI.Section("Nearby DJs", UI.Card(_list, padding: 10, corner: 8)),
            UI.HStack(8,
                UI.Text("Pairing code"),
                code,
                UI.Text("as shown in Amadeus Link on the DJ laptop", Font.Caption).Secondary()).Leading()
        ).Frame(width: 520);
    }

    /// The DJs nearby changed (or the choice did): the list again.
    void Changed()
    {
        _chosen = PairingCode.AutoChoose(_chosen, model.Djs.Found);
        _list.Children.Clear();
        if (model.Djs.Found.Count == 0)
            _list.Children.Add(UI.HStack(8,
                UI.Spinner(14),
                UI.Text("Looking… Is Amadeus Link switched on on the DJ laptop, on the same network?", Font.Callout).Secondary().Wrap()).Margin(0, 6, 0, 6));
        foreach (var dj in model.Djs.Found)
        {
            var row = new Button
            {
                Content = UI.HStack(8,
                    UI.Icon(_chosen == dj.Name ? "largecircle.fill.circle" : "circle").Foreground(Tint.Accent),
                    UI.Icon("laptopcomputer"),
                    UI.Text(dj.Name),
                    UI.Spacer()),
                HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
            }.Borderless();
            row.Padding = new Thickness(0, 3, 0, 3);
            var name = dj.Name;
            row.Click += (_, _) => { _chosen = name; Changed(); };
            _list.Children.Add(row);
        }
        Enable();
    }

    void Enable()
    {
        if (_dialog is not null) _dialog.IsPrimaryButtonEnabled = PairingCode.CanConnect(_chosen, _code);
    }
}
