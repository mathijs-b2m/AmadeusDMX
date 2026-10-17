// The entry point: WinUI's generated Main is switched off (DISABLE_XAML_GENERATED_MAIN, no XAML). One Amadeus Link
// at a time: a second start shows the first one's window (it holds the ports). The mutex
// AmadeusLink.SingleInstance (this session's and the Global one) tells the installer Link runs (Inno Setup's
// AppMutex: it asks to quit Link before replacing it).
using Microsoft.UI.Dispatching;
using Microsoft.Windows.AppLifecycle;

namespace AmadeusLink;

public static class Program
{
    public const string MutexName = "AmadeusLink.SingleInstance";

    [STAThread]
    public static int Main(string[] args)
    {
        using var local = new Mutex(false, MutexName);
        using var global = GlobalMutex();
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
        GC.KeepAlive(local);
        return 0;
    }

    static Mutex? GlobalMutex()
    {
        try { return new Mutex(false, @"Global\" + MutexName); }
        catch (Exception e) when (e is UnauthorizedAccessException or IOException or WaitHandleCannotBeOpenedException) { return null; }
    }
}
