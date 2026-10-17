// The AmadeusLink plugin for VirtualDJ (vdj/): where VirtualDJ looks for it, whether ours is there, putting it
// there. Amadeus DMX installs it from the engine folder; Amadeus Link carries its own copy (a DJ laptop has no
// engine). Both copies are the same build, so "up to date" is the same bytes.
namespace AmadeusKit;

public static class VirtualDJPlugin
{
    public enum Status { NotInstalled, UpToDate, Outdated }

    /// Where VirtualDJ (64-bit, Windows) loads sound effects from: Plugins64\SoundEffect in its home folder
    /// (Documents\VirtualDJ, or %LOCALAPPDATA%\VirtualDJ where Documents is on a network share).
    public static string Installed => Path.Combine(DJ.VirtualDJStreams.Home(), "Plugins64", "SoundEffect", "AmadeusLink.dll");

    /// The installed plugin against the one this app would install.
    public static Status StatusComparedTo(string? bundled, string? installed = null)
    {
        installed ??= Installed;
        if (!File.Exists(installed)) return Status.NotInstalled;
        if (bundled is null || Files.ReadBytes(bundled) is not { } ours) return Status.UpToDate;
        return Files.ReadBytes(installed) is { } there && there.AsSpan().SequenceEqual(ours) ? Status.UpToDate : Status.Outdated;
    }

    /// Copies the plugin into VirtualDJ's folder (replacing an older one). VirtualDJ loads it at its next start;
    /// while VirtualDJ runs, it holds the old one and the copy fails (quit VirtualDJ first).
    public static void Install(string bundled, string? installed = null)
    {
        installed ??= Installed;
        Directory.CreateDirectory(Path.GetDirectoryName(installed)!);
        try { File.Copy(bundled, installed, overwrite: true); }
        catch (IOException e) when (File.Exists(installed))
        {
            throw new IOException("VirtualDJ is using the plugin: quit VirtualDJ, then install it again.", e);
        }
    }
}
