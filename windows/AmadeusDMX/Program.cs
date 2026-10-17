// The entry point: WinUI's generated Main is switched off (DISABLE_XAML_GENERATED_MAIN, no XAML), so the app
// starts here, with a SynchronizationContext on the UI thread (the models post their updates to it). One Amadeus
// DMX at a time, as on the Mac: a second start shows the first one's window (two would fight over the engine).
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.Windows.AppLifecycle;

namespace AmadeusDMX;

public static class Program
{
    [STAThread]
    public static int Main(string[] args)
    {
        if (RenderSelfTest.Requested(args)) return RenderSelfTest.Run();   // the 3D stage, offscreen, into PNGs in %TEMP%
        WinRT.ComWrappersSupport.InitializeComWrappers();
        var main = AppInstance.FindOrRegisterForKey("main");
        if (!main.IsCurrent)
        {
            // hand the activation to the one running (off the UI thread: it waits for the other process)
            var activation = AppInstance.GetCurrent().GetActivatedEventArgs();
            Task.Run(() => main.RedirectActivationToAsync(activation).AsTask()).Wait();
            return 0;
        }
        Application.Start(p =>
        {
            SynchronizationContext.SetSynchronizationContext(new DispatcherQueueSynchronizationContext(DispatcherQueue.GetForCurrentThread()));
            _ = new App();
        });
        return 0;
    }
}
