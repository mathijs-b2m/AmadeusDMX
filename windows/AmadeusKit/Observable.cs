// The C# side of Swift's @Observable: a model raises PropertyChanged when a property changes, and the views
// (UI.Bind) follow it. Models are touched on the UI thread only, like @MainActor ones; work done elsewhere (the
// feed's receiver, the engine's output) is posted to the SynchronizationContext the model was made on.
using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace AmadeusKit;

public abstract class Observable : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;

    /// Sets a backing field and tells the views, if the value changed. Returns whether it did.
    protected bool Set<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return false;
        field = value;
        Changed(name);
        return true;
    }

    /// A property changed (also one computed from others: `Changed(nameof(ShowState))`).
    protected void Changed([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));

    protected void Changed(params string[] names)
    {
        foreach (var n in names) Changed(n);
    }
}

/// Runs work on the thread a model belongs to: its SynchronizationContext, or at once when it has none (tests).
public sealed class UIThread(SynchronizationContext? context)
{
    /// The context of the thread that makes the model (the UI thread in the apps).
    public static UIThread Current() => new(SynchronizationContext.Current);

    public SynchronizationContext? Context { get; } = context;

    public void Post(Action action)
    {
        if (Context is null || SynchronizationContext.Current == Context) action();
        else Context.Post(_ => action(), null);
    }
}
