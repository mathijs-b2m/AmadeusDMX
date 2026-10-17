// Start with a DJ laptop (Amadeus Link): the nearby DJs, the pairing code (mac/Sources/AmadeusDMX/Show/DJLinkSheet.swift).
// A placeholder until it is ported: Present is what the toolbar calls.
namespace AmadeusDMX;

public static class DJLinkSheet
{
    public static async void Present(AppModel model, MainWindow window)
    {
        if (window.Root is null) return;
        await new ContentDialog
        {
            XamlRoot = window.Root,
            Title = "Start with a DJ Laptop",
            Content = UI.Text("This sheet is being ported from the Mac app.").Wrap(),
            CloseButtonText = "Cancel",
        }.ShowAsync();
    }
}
