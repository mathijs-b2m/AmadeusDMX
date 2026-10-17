// AmadeusLink: a VirtualDJ 8 plugin that streams the live mix state to Amadeus DMX.
//
// Load it as a MASTER sound effect. It does not touch the audio. A background thread polls
// VirtualDJ (VDJScript queries) 25 times per second and sends one small JSON packet per poll
// over UDP to 127.0.0.1:9123:
//
//   {"t":<ms since plugin start>,"master":<deck>,
//    "decks":[{"deck":1,"file":"/path.mp3","pos":<s>,"len":<s>,"play":1,"bpm":128.0,
//              "bpm0":126.0,"vol":<0..1 fader*xfader>}, ...]}
//
// The query load is kept low on purpose (VDJScript queries share VirtualDJ's internals): only the
// decks that exist, 4 fast values per deck per poll, and the slowly changing ones (file, length,
// original BPM) twice per second. The receiver extrapolates the position between packets.
//
// The VirtualDJ SDK headers (vdjPlugin8.h, vdjDsp8.h) are not included in this repository;
// build.sh (macOS) and build.ps1 (Windows) download them from virtualdj.com.
//
// One source for both systems: a bundle for macOS (PluginsMacArm/SoundEffect/AmadeusLink.bundle), a DLL for
// 64-bit Windows (Plugins64\SoundEffect\AmadeusLink.dll). Only the socket calls differ (Winsock on Windows).

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN  // as vdjPlugin8.h has it: windows.h without the COM headers (DllGetClassObject)
#include <winsock2.h>        // before windows.h, which vdjPlugin8.h includes
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
#endif

#include "vdjDsp8.h"

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>

#ifndef _WIN32
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace {
#ifdef _WIN32
using Socket = SOCKET;
const Socket kNoSocket = INVALID_SOCKET;
void CloseSocket(Socket s) { closesocket(s); }
#else
using Socket = int;
const Socket kNoSocket = -1;
void CloseSocket(Socket s) { close(s); }
#endif

constexpr int kPort = 9123;
constexpr int kPollMs = 40;       // 25 packets per second
constexpr int kSlowEvery = 12;    // file/length/original BPM every 12th poll (~0.5 s)
constexpr int kMaxDecks = 4;

std::string json_escape(const char* s) {
    std::string out;
    for (; *s; ++s) {
        unsigned char c = static_cast<unsigned char>(*s);
        if (c == '"' || c == '\\') { out += '\\'; out += static_cast<char>(c); }
        else if (c < 0x20) { char buf[8]; snprintf(buf, sizeof buf, "\\u%04x", c); out += buf; }
        else out += static_cast<char>(c);
    }
    return out;
}
}  // namespace

class AmadeusLink : public IVdjPluginDsp8 {
public:
    HRESULT VDJ_API OnLoad() override { return S_OK; }

    HRESULT VDJ_API OnGetPluginInfo(TVdjPluginInfo8* info) override {
        info->PluginName = "AmadeusLink";
        info->Author = "Amadeus DMX";
        info->Description = "Streams the live mix state to Amadeus DMX (UDP 9123). Use as a master effect.";
        info->Version = "1.1";
        info->Flags = 0;
        info->Bitmap = nullptr;
        return S_OK;
    }

    HRESULT VDJ_API OnStart() override {
        if (running_.exchange(true)) return S_OK;
#ifdef _WIN32
        WSADATA wsa;
        winsock_ = WSAStartup(MAKEWORD(2, 2), &wsa) == 0;
#endif
        sock_ = socket(AF_INET, SOCK_DGRAM, 0);
        memset(&dest_, 0, sizeof dest_);
        dest_.sin_family = AF_INET;
        dest_.sin_port = htons(kPort);
        dest_.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        start_ = std::chrono::steady_clock::now();
        worker_ = std::thread([this] { Loop(); });
        return S_OK;
    }

    HRESULT VDJ_API OnStop() override {
        Shutdown();
        return S_OK;
    }

    // Leave the sound untouched.
    HRESULT VDJ_API OnProcessSamples(float* /*buffer*/, int /*nb*/) override { return S_OK; }

    ULONG VDJ_API Release() override {
        Shutdown();
        delete this;
        return 0;
    }

private:
    double Num(const std::string& cmd) {
        double v = 0;
        return GetInfo(cmd.c_str(), &v) == S_OK ? v : 0.0;
    }

    std::string Str(const std::string& cmd) {
        char buf[2048] = {0};
        if (GetStringInfo(cmd.c_str(), buf, sizeof buf) != S_OK) return "";
        return buf;
    }

    struct Slow { std::string file; double len = 0, bpm0 = 0; };

    void Loop() {
        Slow slow[kMaxDecks + 1];
        int decks = 2;
        for (long n = 0; running_; ++n) {
            const auto tick = std::chrono::steady_clock::now();
            const double ms = std::chrono::duration<double, std::milli>(tick - start_).count();
            if (n % kSlowEvery == 0) {  // rarely changing values: deck count, file, length, original BPM
                const int reported = static_cast<int>(Num("get_decks"));
                decks = reported >= 1 && reported <= kMaxDecks ? reported : 2;
                for (int d = 1; d <= decks; ++d) {
                    const std::string p = "deck " + std::to_string(d) + " ";
                    slow[d].file = Str(p + "get_filepath");
                    slow[d].len = slow[d].file.empty() ? 0 : Num(p + "get_songlength");
                    slow[d].bpm0 = slow[d].file.empty() ? 0 : Num(p + "get_bpm absolute");
                }
            }
            std::string msg = "{\"t\":" + std::to_string(ms) +
                              ",\"master\":" + std::to_string(static_cast<int>(Num("get_activedeck"))) + ",\"decks\":[";
            bool first = true;
            for (int d = 1; d <= decks; ++d) {
                if (slow[d].file.empty()) continue;
                const std::string p = "deck " + std::to_string(d) + " ";
                char buf[384];
                snprintf(buf, sizeof buf,
                         "{\"deck\":%d,\"pos\":%.4f,\"len\":%.3f,\"play\":%d,\"bpm\":%.3f,\"bpm0\":%.3f,"
                         "\"vol\":%.4f,\"file\":\"",
                         d, Num(p + "get_position") * slow[d].len, slow[d].len, Num(p + "play") > 0.5 ? 1 : 0,
                         Num(p + "get_bpm"), slow[d].bpm0, Num(p + "get_volume"));
                msg += (first ? "" : ",") + std::string(buf) + json_escape(slow[d].file.c_str()) + "\"}";
                first = false;
            }
            msg += "]}";
            if (sock_ != kNoSocket)
                sendto(sock_, msg.data(), static_cast<int>(msg.size()), 0, reinterpret_cast<sockaddr*>(&dest_),
                       sizeof dest_);
            std::this_thread::sleep_until(tick + std::chrono::milliseconds(kPollMs));
        }
    }

    void Shutdown() {
        if (!running_.exchange(false)) return;
        if (worker_.joinable()) worker_.join();
        if (sock_ != kNoSocket) CloseSocket(sock_);
        sock_ = kNoSocket;
#ifdef _WIN32
        if (winsock_) WSACleanup();
        winsock_ = false;
#endif
    }

    std::atomic<bool> running_{false};
    std::thread worker_;
    Socket sock_ = kNoSocket;
#ifdef _WIN32
    bool winsock_ = false;
#endif
    sockaddr_in dest_{};
    std::chrono::steady_clock::time_point start_;
};

extern "C" VDJ_EXPORT HRESULT VDJ_API DllGetClassObject(const GUID& rclsid, const GUID& riid, void** ppObject) {
    if (memcmp(&rclsid, &CLSID_VdjPlugin8, sizeof(GUID)) == 0 &&
        memcmp(&riid, &IID_IVdjPluginDsp8, sizeof(GUID)) == 0) {
        *ppObject = new AmadeusLink();
        return S_OK;
    }
    return CLASS_E_CLASSNOTAVAILABLE;
}
