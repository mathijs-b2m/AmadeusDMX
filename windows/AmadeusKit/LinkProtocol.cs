// Amadeus Link's protocol (v1), the parts both ends must get byte for byte the same: the pairing proof, the
// session key, the packet signature and the file request's auth (amadeus/show/link.py is the other end;
// docs/protocols.md section 3).
//
//   proof       = HMAC-SHA256(code, "pair" s c), hex          c, s: the two nonces (16 random bytes, hex)
//   session key = HMAC-SHA256(code, "key" s c)
//   packet      = json "|" hex(first 16 bytes of HMAC(key, json)),  json = {"s": seq, "ts": ns, "d": plugin packet}
//   file auth   = HMAC(key, "file" path), hex
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;

namespace AmadeusKit;

public static class LinkProtocol
{
    public const int Version = 1;
    public const string ServiceType = "_amadeuslink._tcp";
    /// Where Amadeus Link listens for lighting computers (TCP) and for the DJ software's packets (UDP, 127.0.0.1).
    public const int ServicePort = 7123;
    public const int PluginPort = 9123;

    /// HMAC-SHA256 of the parts one after the other (link.py `_h`).
    public static byte[] Hmac(ReadOnlySpan<byte> key, params string[] parts)
    {
        using var h = IncrementalHash.CreateHMAC(HashAlgorithmName.SHA256, key);
        foreach (var p in parts) h.AppendData(Encoding.UTF8.GetBytes(p));
        return h.GetHashAndReset();
    }

    public static byte[] Hmac(string code, params string[] parts) => Hmac(Encoding.UTF8.GetBytes(code), parts);

    public static byte[] Hmac(ReadOnlySpan<byte> key, ReadOnlySpan<byte> data) => HMACSHA256.HashData(key, data);

    /// What the lighting computer proves it knows the code with.
    public static string Proof(string code, string s, string c) => Hex(Hmac(code, "pair", s, c));

    public static byte[] SessionKey(string code, string s, string c) => Hmac(code, "key", s, c);

    /// A packet's signature: the first 16 bytes of HMAC(key, payload), hex.
    public static string Sign(ReadOnlySpan<byte> key, ReadOnlySpan<byte> payload) => Hex(Hmac(key, payload).AsSpan(0, 16));

    /// A file request's auth.
    public static string FileAuth(ReadOnlySpan<byte> key, string path) => Hex(Hmac(key, "file", path));

    /// {"s":seq,"ts":ns,"d":<the plugin's packet, as it came>}
    public static byte[] Payload(long seq, long ts, ReadOnlySpan<byte> plugin)
    {
        var head = Encoding.UTF8.GetBytes($"{{\"s\":{seq},\"ts\":{ts},\"d\":");
        var out_ = new byte[head.Length + plugin.Length + 1];
        head.CopyTo(out_, 0);
        plugin.CopyTo(out_.AsSpan(head.Length));
        out_[^1] = (byte)'}';
        return out_;
    }

    /// payload "|" signature: one UDP datagram.
    public static byte[] Signed(ReadOnlySpan<byte> key, ReadOnlySpan<byte> payload)
    {
        var sig = Encoding.ASCII.GetBytes(Sign(key, payload));
        var out_ = new byte[payload.Length + 1 + sig.Length];
        payload.CopyTo(out_);
        out_[payload.Length] = (byte)'|';
        sig.CopyTo(out_, payload.Length + 1);
        return out_;
    }

    /// The payload of a signed packet, nil when the signature isn't right (as link.py reads it: up to the last "|").
    public static byte[]? Verify(ReadOnlySpan<byte> key, ReadOnlySpan<byte> packet)
    {
        var bar = packet.LastIndexOf((byte)'|');
        if (bar <= 0) return null;
        var payload = packet[..bar];
        var want = Encoding.ASCII.GetBytes(Sign(key, payload));
        return CryptographicOperations.FixedTimeEquals(want, packet[(bar + 1)..]) ? payload.ToArray() : null;
    }

    public static string RandomHex(int bytes = 16) => Hex(RandomNumberGenerator.GetBytes(bytes));

    /// A new 4-digit pairing code.
    public static string NewCode() => RandomNumberGenerator.GetInt32(0, 10000).ToString("D4");

    public static string Hex(ReadOnlySpan<byte> b) => Convert.ToHexStringLower(b);

    /// This computer's clock for packets, in nanoseconds (monotonic, like the Mac's uptime clock).
    public static long Now() => (long)(Stopwatch.GetTimestamp() * (1e9 / Stopwatch.Frequency));
}
