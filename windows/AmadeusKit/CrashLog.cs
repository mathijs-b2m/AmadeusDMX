// What went wrong, kept: an app that dies before its window shows leaves only a code in Windows' event log.
namespace AmadeusKit;

public static class CrashLog
{
    /// %LOCALAPPDATA%\<app>\logs\crash.log (the newest at the end).
    public static string FileFor(string app) =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), app, "logs", "crash.log");

    public static void Write(string app, Exception e, string where)
    {
        try
        {
            var file = FileFor(app);
            Directory.CreateDirectory(Path.GetDirectoryName(file)!);
            File.AppendAllText(file, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {where}\n{e}\n\n");
        }
        catch (Exception x) when (x is IOException or UnauthorizedAccessException) { }
    }

    /// A log of its own beside the crash log (logs\name), replaced each time.
    public static void Save(string app, string name, IEnumerable<string> lines)
    {
        try
        {
            var file = Path.Combine(Path.GetDirectoryName(FileFor(app))!, name);
            Directory.CreateDirectory(Path.GetDirectoryName(file)!);
            File.WriteAllLines(file, lines);
        }
        catch (Exception x) when (x is IOException or UnauthorizedAccessException) { }
    }
}
