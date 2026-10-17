// Secrets (the OpenAI key) in Windows Credential Manager, the Keychain's counterpart: never in a file. One generic
// credential per service and account ("io.github.amadeusdmx.app/OPENAI_API_KEY"). Off Windows (tests) they are
// kept in memory only.
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Text;

namespace AmadeusKit;

public static class Credentials
{
    static readonly Dictionary<string, string> Memory = [];
    static readonly Lock MemoryLock = new();

    static string Target(string service, string account) => $"{service}/{account}";

    public static string? Read(string service, string account)
    {
        var target = Target(service, account);
        if (!OperatingSystem.IsWindows()) lock (MemoryLock) return Memory.GetValueOrDefault(target);
        return Win32.Read(target);
    }

    /// Saves it (nil or "": deletes it).
    public static void Write(string service, string account, string? value)
    {
        var target = Target(service, account);
        if (string.IsNullOrEmpty(value)) { Delete(service, account); return; }
        if (!OperatingSystem.IsWindows()) { lock (MemoryLock) Memory[target] = value; return; }
        Win32.Write(target, account, value);
    }

    public static void Delete(string service, string account)
    {
        var target = Target(service, account);
        if (!OperatingSystem.IsWindows()) { lock (MemoryLock) Memory.Remove(target); return; }
        Win32.CredDeleteW(target, CRED_TYPE_GENERIC, 0);
    }

    const uint CRED_TYPE_GENERIC = 1;
    const uint CRED_PERSIST_LOCAL_MACHINE = 2;  // this user on this computer (not roaming)

    [SupportedOSPlatform("windows")]
    static class Win32
    {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct CREDENTIAL
        {
            public uint Flags;
            public uint Type;
            public string TargetName;
            public string? Comment;
            public long LastWritten;
            public uint CredentialBlobSize;
            public IntPtr CredentialBlob;
            public uint Persist;
            public uint AttributeCount;
            public IntPtr Attributes;
            public string? TargetAlias;
            public string? UserName;
        }

        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool CredWriteW(ref CREDENTIAL credential, uint flags);

        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool CredReadW(string target, uint type, uint flags, out IntPtr credential);

        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool CredDeleteW(string target, uint type, uint flags);

        [DllImport("advapi32.dll")]
        static extern void CredFree(IntPtr buffer);

        public static string? Read(string target)
        {
            if (!CredReadW(target, CRED_TYPE_GENERIC, 0, out var p)) return null;
            try
            {
                var c = Marshal.PtrToStructure<CREDENTIAL>(p);
                if (c.CredentialBlob == IntPtr.Zero || c.CredentialBlobSize == 0) return null;
                var bytes = new byte[c.CredentialBlobSize];
                Marshal.Copy(c.CredentialBlob, bytes, 0, bytes.Length);
                return Encoding.UTF8.GetString(bytes);
            }
            finally { CredFree(p); }
        }

        public static void Write(string target, string account, string value)
        {
            var bytes = Encoding.UTF8.GetBytes(value);
            var blob = Marshal.AllocHGlobal(bytes.Length);
            try
            {
                Marshal.Copy(bytes, 0, blob, bytes.Length);
                var c = new CREDENTIAL
                {
                    Type = CRED_TYPE_GENERIC, TargetName = target, UserName = account, CredentialBlob = blob,
                    CredentialBlobSize = (uint)bytes.Length, Persist = CRED_PERSIST_LOCAL_MACHINE,
                };
                CredWriteW(ref c, 0);
            }
            finally { Marshal.FreeHGlobal(blob); }
        }
    }
}
