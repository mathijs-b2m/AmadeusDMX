// The entry point: WinUI's generated Main is switched off (DISABLE_XAML_GENERATED_MAIN, no XAML). One Amadeus Link
// at a time: a second start shows the first one's window (it holds the ports).
using Microsoft.UI.Dispatching;
using Microsoft.Windows.AppLifecycle;

namespace AmadeusLink;

public static class Program
{
    [STAThread]
    public static int Main(string[] args)
    {
        WinRT.ComWrappersSupport.InitializeComWrappers();
        var main = AppInstance.FindOrRegisterForKey("main");
        if (!main.IsCurrent)
        {
            // hand the activation to the one running (off the UI thread: it waits for the other process)
            var activation = AppInstance.GetCurrent().GetActivatedEventArgs();
            Task.Run(() => main.RedirectActivationToAsync(activation).AsTask()).Wait();
            return 0;
        }
        Microsoft.UI.Xaml.Application.Start(p =>
        {
            SynchronizationContext.SetSynchronizationContext(new DispatcherQueueSynchronizationContext(DispatcherQueue.GetForCurrentThread()));
            _ = new App();
        });
        return 0;
    }
}
