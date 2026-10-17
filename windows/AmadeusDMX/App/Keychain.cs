// The OpenAI key, in Windows Credential Manager (it never goes into a file).
namespace AmadeusDMX;

public static class Keychain
{
    const string Service = "io.github.amadeusdmx.app";

    public static string? OpenAIKey
    {
        get => Credentials.Read(Service, "OPENAI_API_KEY");
        set => Credentials.Write(Service, "OPENAI_API_KEY", value);
    }
}
