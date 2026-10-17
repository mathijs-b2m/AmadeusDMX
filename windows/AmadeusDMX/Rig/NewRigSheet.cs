// New Rig…: a rig from a template, with a sketch of each (mac/Sources/AmadeusDMX/Rig/NewRigSheet.swift).
// A placeholder until it is ported: Present is what the window calls when AppModel.ShowNewRig turns on.
namespace AmadeusDMX;

public static class NewRigSheet
{
    public static async void Present(AppModel model, MainWindow window)
    {
        if (window.Root is null) { model.ShowNewRig = false; return; }
        await new ContentDialog
        {
            XamlRoot = window.Root,
            Title = "New Rig",
            Content = UI.Text("This sheet is being ported from the Mac app.").Wrap(),
            CloseButtonText = "Cancel",
        }.ShowAsync();
        model.ShowNewRig = false;
    }
}
