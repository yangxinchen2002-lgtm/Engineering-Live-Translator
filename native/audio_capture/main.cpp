#include <windows.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <mmdeviceapi.h>
#include <ks.h>
#include <ksmedia.h>
#include <sddl.h>
#include <wrl.h>
#include <wrl/implements.h>
#include <atomic>
#include <array>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <thread>
#include "protocol.h"
#include "packet_queue.h"
#include "source_policy.h"

using Microsoft::WRL::ComPtr;
using namespace std::chrono_literals;
std::string escape_json(const std::string& s);

struct Handle {
    HANDLE h = nullptr;
    explicit Handle(HANDLE v = nullptr) : h(v) {}
    ~Handle() { if (h && h != INVALID_HANDLE_VALUE) CloseHandle(h); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    operator HANDLE() const { return h; }
};
struct CoMemory { void* p = nullptr; ~CoMemory() { CoTaskMemFree(p); } };
struct LocalMemory { void* p = nullptr; ~LocalMemory() { if (p) LocalFree(p); } };
void check(HRESULT hr, const char* operation) {
    if (FAILED(hr)) {
        std::ostringstream s;
        s << operation << " HRESULT=0x" << std::hex << static_cast<uint32_t>(hr);
        throw std::runtime_error(s.str());
    }
}
void wincheck(BOOL ok, const char* operation) {
    if (!ok) check(HRESULT_FROM_WIN32(GetLastError()), operation);
}
HANDLE event_handle(bool manual = true) {
    HANDLE h = CreateEventW(nullptr, manual, FALSE, nullptr);
    wincheck(h != nullptr, "CreateEvent");
    return h;
}
struct ComApartment {
    ComApartment() { check(CoInitializeEx(nullptr, COINIT_MULTITHREADED), "CoInitializeEx"); }
    ~ComApartment() { CoUninitialize(); }
};

// The callback and params own their lifetime even if activation times out.
class Activation final : public Microsoft::WRL::RuntimeClass<
    Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>,
    Microsoft::WRL::FtmBase, IActivateAudioInterfaceCompletionHandler> {
public:
    Handle done{event_handle()};
    AUDIOCLIENT_ACTIVATION_PARAMS params{};
    PROPVARIANT prop{};
    HRESULT result = E_PENDING;
    ComPtr<IAudioClient> client;
    STDMETHOD(ActivateCompleted)(IActivateAudioInterfaceAsyncOperation* op) override {
        ComPtr<IUnknown> unknown;
        HRESULT activated = E_FAIL;
        result = op->GetActivateResult(&activated, &unknown);
        if (SUCCEEDED(result)) result = activated;
        if (SUCCEEDED(result)) result = unknown.As(&client);
        SetEvent(done);
        return S_OK;
    }
};

// Overlapped I/O always completes/cancels before its stack OVERLAPPED is destroyed.
DWORD transfer(HANDLE pipe, void* data, DWORD size, bool write, HANDLE stop, DWORD timeout) {
    Handle ready{event_handle()};
    OVERLAPPED ov{};
    ov.hEvent = ready;
    DWORD n = 0;
    BOOL ok = write ? WriteFile(pipe, data, size, &n, &ov) : ReadFile(pipe, data, size, &n, &ov);
    if (!ok && GetLastError() != ERROR_IO_PENDING) wincheck(FALSE, write ? "WriteFile" : "ReadFile");
    if (!ok) {
        HANDLE events[] = {ready, stop};
        const auto wait = WaitForMultipleObjects(stop ? 2 : 1, events, FALSE, timeout);
        if (wait != WAIT_OBJECT_0) {
            CancelIoEx(pipe, &ov);
            GetOverlappedResult(pipe, &ov, &n, TRUE);
            throw std::runtime_error(wait == WAIT_TIMEOUT ? "pipe_io_timeout" : "pipe_io_cancelled");
        }
        wincheck(GetOverlappedResult(pipe, &ov, &n, TRUE), "GetOverlappedResult");
    }
    if (!n) throw std::runtime_error("pipe_closed");
    return n;
}
void read_exact(HANDLE pipe, void* data, DWORD size, HANDLE stop, DWORD timeout) {
    auto* b = static_cast<uint8_t*>(data);
    DWORD offset = 0;
    while (offset < size) offset += transfer(pipe, b + offset, size - offset, false, stop, timeout);
}
elt::Header read_control(HANDLE pipe, uint64_t sequence, HANDLE stop, DWORD timeout) {
    uint32_t n = 0;
    read_exact(pipe, &n, 4, stop, timeout);
    if (n != sizeof(elt::Header) + 2) throw std::runtime_error("invalid_control_length");
    std::vector<uint8_t> data(n);
    read_exact(pipe, data.data(), n, stop, timeout);
    return elt::decode_control(data, sequence);
}

struct Outbox {
    // Single producer (capture/main), single consumer (pipe writer).
    // No mutex, pipe I/O or consumer wait on the capture path.
    elt::PacketQueue queue;
    std::atomic<bool> finished{false};
    Handle ready{event_handle(false)};
    std::atomic<int>& fault;
    HANDLE stop;
    Outbox(std::atomic<int>& f, HANDLE s) : fault(f), stop(s) {}
    bool push(elt::Message m) {
        if (!queue.push(std::move(m))) {
            fault.store(3); SetEvent(stop); return false;
        }
        SetEvent(ready);
        return true;
    }
    size_t depth() const { return queue.depth(); }
    void finish() { finished.store(true); SetEvent(ready); }
    void write_loop(HANDLE pipe) {
        try {
            uint64_t seq = 0;
            for (;;) {
                elt::Message m;
                if (!queue.pop(m)) {
                    if (finished.load()) return;
                    WaitForSingleObject(ready, 250);
                    continue;
                }
                auto data = elt::encode(std::move(m), seq++);
                size_t offset = 0;
                while (offset < data.size()) offset += transfer(pipe, data.data() + offset,
                    static_cast<DWORD>(data.size() - offset), true, nullptr, 2000);
            }
        } catch (const std::exception& e) {
            std::cerr << "{\"pipe_writer_error\":\"" << escape_json(e.what()) << "\"}\n";
            fault.store(2); SetEvent(stop);
        }
    }
};

uint64_t filetime_value(FILETIME ft) { return uint64_t(ft.dwHighDateTime) << 32 | ft.dwLowDateTime; }

void capture(DWORD pid, uint64_t created, HANDLE target, HANDLE stop, Outbox& out, elt::Source source_kind) {
    ComApartment apartment; // All client operations and releases occur in this MTA.
    FILETIME c{}, e{}, k{}, u{};
    wincheck(GetProcessTimes(target, &c, &e, &k, &u), "GetProcessTimes");
    if (filetime_value(c) != created || WaitForSingleObject(target, 0) != WAIT_TIMEOUT)
        throw std::runtime_error("target_identity_changed");
    auto activation = Microsoft::WRL::Make<Activation>();
    if (!activation) throw std::bad_alloc();
    activation->params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
    activation->params.ProcessLoopbackParams.TargetProcessId = pid;
    activation->params.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;
    activation->prop.vt = VT_BLOB;
    activation->prop.blob.cbSize = sizeof(activation->params);
    activation->prop.blob.pBlobData = reinterpret_cast<BYTE*>(&activation->params);
    ComPtr<IActivateAudioInterfaceAsyncOperation> operation;
    check(ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, __uuidof(IAudioClient),
        &activation->prop, activation.Get(), &operation), "ActivateAudioInterfaceAsync");
    HANDLE activate_events[] = {activation->done, stop, target};
    DWORD activated = WaitForMultipleObjects(3, activate_events, FALSE, 10000);
    if (activated == WAIT_OBJECT_0 + 1) return;
    if (activated == WAIT_OBJECT_0 + 2) throw std::runtime_error("target_exited_during_activation");
    if (activated != WAIT_OBJECT_0) throw std::runtime_error("activation_timeout_or_wait_failure");
    check(activation->result, "GetActivateResult");
    ComPtr<IAudioClient> client = activation->client;
    WAVEFORMATEX* returned = nullptr;
    const HRESULT mix_result = client->GetMixFormat(&returned);
    CoMemory mix_memory{returned};
    // Some virtual process-loopback clients do not implement GetMixFormat.
    // Explicitly negotiate the sample's PCM format in that case; never label it a queried mix format.
    WAVEFORMATEX negotiated{};
    bool fallback = mix_result == E_NOTIMPL;
    if (fallback) {
        negotiated.wFormatTag = WAVE_FORMAT_PCM;
        negotiated.nChannels = 2; negotiated.nSamplesPerSec = 44100;
        negotiated.wBitsPerSample = 16; negotiated.nBlockAlign = 4;
        negotiated.nAvgBytesPerSec = 176400;
        returned = &negotiated;
        out.push(elt::event(elt::Status, "{\"state\":\"format_negotiation\",\"reason\":\"GetMixFormat_E_NOTIMPL\",\"requested\":\"44100_stereo_s16\"}"));
    } else check(mix_result, "GetMixFormat");
    if (!returned) throw std::runtime_error("null_mix_format");
    const auto& fmt = *returned;
    uint16_t format = 0, valid_bits = fmt.wBitsPerSample;
    uint32_t mask = 0;
    WORD tag = fmt.wFormatTag;
    if (tag == WAVE_FORMAT_EXTENSIBLE) {
        if (fmt.cbSize < sizeof(WAVEFORMATEXTENSIBLE) - sizeof(WAVEFORMATEX))
            throw std::runtime_error("invalid_extensible_format");
        auto* ext = reinterpret_cast<WAVEFORMATEXTENSIBLE*>(returned);
        valid_bits = ext->Samples.wValidBitsPerSample;
        mask = ext->dwChannelMask;
        if (IsEqualGUID(ext->SubFormat, KSDATAFORMAT_SUBTYPE_PCM)) tag = WAVE_FORMAT_PCM;
        else if (IsEqualGUID(ext->SubFormat, KSDATAFORMAT_SUBTYPE_IEEE_FLOAT)) tag = WAVE_FORMAT_IEEE_FLOAT;
    }
    if (tag == WAVE_FORMAT_PCM) {
        if (fmt.wBitsPerSample == 16) format = elt::S16;
        if (fmt.wBitsPerSample == 24) format = elt::S24;
        if (fmt.wBitsPerSample == 32) format = elt::S32;
    } else if (tag == WAVE_FORMAT_IEEE_FLOAT && fmt.wBitsPerSample == 32) format = elt::F32;
    if (!format || !valid_bits || valid_bits > fmt.wBitsPerSample ||
        (format == elt::F32 && valid_bits != 32) || fmt.nChannels == 0 || fmt.nChannels > 32 ||
        fmt.nSamplesPerSec < 8000 || fmt.nSamplesPerSec > 384000 ||
        fmt.nBlockAlign != fmt.nChannels * fmt.wBitsPerSample / 8)
        throw std::runtime_error("unsupported_capture_format");
    check(client->Initialize(AUDCLNT_SHAREMODE_SHARED,
        AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK |
        (fallback ? AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY : 0),
        0, 0, returned, nullptr), "IAudioClient_Initialize");
    ComPtr<IAudioCaptureClient> source;
    check(client->GetService(IID_PPV_ARGS(&source)), "GetService_IAudioCaptureClient");
    Handle samples{event_handle(false)};
    check(client->SetEventHandle(samples), "SetEventHandle");
    check(client->Start(), "IAudioClient_Start");
    struct StopClient {
        IAudioClient* client;
        bool active = true;
        ~StopClient() {
            if (active) {
                HRESULT hr = client->Stop();
                if (FAILED(hr)) std::cerr << "{\"cleanup_error\":\"IAudioClient_Stop\",\"hresult\":" << static_cast<uint32_t>(hr) << "}\n";
            }
        }
    } stop_client{client.Get()};
    std::ostringstream description;
    description << "{\"state\":\"started\",\"signal\":\"unverified\",\"source\":\"" << elt::source_name(source_kind)
        << "\",\"scope\":\"process_tree\",\"rate\":" << fmt.nSamplesPerSec
        << ",\"channels\":" << fmt.nChannels << ",\"format\":" << format
        << ",\"valid_bits\":" << valid_bits << ",\"channel_mask\":" << mask
        << ",\"format_source\":\"" << (fallback ? "Initialize_accepted" : "GetMixFormat") << "\"}";
    if (!out.push(elt::event(elt::Status, description.str()))) throw std::runtime_error("outbox_overflow");
    uint64_t count = 0;
    auto last_status = std::chrono::steady_clock::now();
    HANDLE waits[] = {stop, target, samples};
    while (true) {
        const DWORD w = WaitForMultipleObjects(3, waits, FALSE, 250);
        if (w == WAIT_OBJECT_0) break;
        if (w == WAIT_OBJECT_0 + 1) throw std::runtime_error("target_exited_select_again_for_new_PID");
        if (w == WAIT_FAILED) wincheck(FALSE, "WaitForMultipleObjects");
        if (w != WAIT_TIMEOUT && w != WAIT_OBJECT_0 + 2) throw std::runtime_error("unexpected_capture_wait");
        UINT32 available = 0;
        check(source->GetNextPacketSize(&available), "GetNextPacketSize");
        while (available) {
            if (WaitForSingleObject(stop, 0) == WAIT_OBJECT_0) break;
            BYTE* data = nullptr;
            UINT32 n = 0;
            DWORD flags = 0;
            UINT64 position = 0, timestamp = 0;
            check(source->GetBuffer(&data, &n, &flags, &position, &timestamp), "GetBuffer");
            struct Release {
                IAudioCaptureClient* source; UINT32 frames; bool active = true;
                ~Release() {
                    if (active) {
                        HRESULT hr = source->ReleaseBuffer(frames);
                        if (FAILED(hr)) std::cerr << "{\"cleanup_error\":\"ReleaseBuffer\",\"hresult\":" << static_cast<uint32_t>(hr) << "}\n";
                    }
                }
            } release{source.Get(), n};
            if (flags & AUDCLNT_BUFFERFLAGS_TIMESTAMP_ERROR) throw std::runtime_error("WASAPI_timestamp_error");
            if ((flags & AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY) && count)
                throw std::runtime_error("WASAPI_data_discontinuity_audio_incomplete");
            const auto bytes = static_cast<size_t>(n) * fmt.nBlockAlign;
            if (bytes > elt::max_body - sizeof(elt::Header) || n == 0) throw std::runtime_error("invalid_audio_packet_size");
            elt::Message m;
            auto& h = m.header;
            h.kind = elt::Audio; h.rate = fmt.nSamplesPerSec; h.channels = fmt.nChannels;
            h.format = format; h.frames = n; h.timestamp = timestamp; h.first_sample = count;
            h.flags = flags; h.valid_bits = valid_bits; h.channel_mask = mask;
            m.payload.resize(bytes, 0);
            if (!(flags & AUDCLNT_BUFFERFLAGS_SILENT)) {
                if (!data) throw std::runtime_error("null_audio_buffer");
                std::memcpy(m.payload.data(), data, bytes);
            }
            const HRESULT release_result = source->ReleaseBuffer(n);
            release.active = false;
            check(release_result, "ReleaseBuffer");
            if (!out.push(std::move(m))) throw std::runtime_error("outbox_overflow_audio_incomplete");
            count += n;
            check(source->GetNextPacketSize(&available), "GetNextPacketSize");
        }
        if (std::chrono::steady_clock::now() - last_status >= 1s) {
            if (!out.push(elt::event(elt::Status, "{\"state\":\"running\",\"input_samples\":" + std::to_string(count)
                + ",\"queue_packets\":" + std::to_string(out.depth()) + ",\"queue_bytes\":" + std::to_string(out.queue.payload_bytes()) + "}")))
                throw std::runtime_error("outbox_overflow");
            last_status = std::chrono::steady_clock::now();
        }
    }
    const HRESULT stop_result = client->Stop();
    stop_client.active = false;
    check(stop_result, "IAudioClient_Stop");
}

std::string escape_json(const std::string& s) {
    std::string result;
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') result += '\\';
        if (c >= 32 && c < 127) result += static_cast<char>(c);
        else result += '?';
    }
    return result;
}

void run(const std::wstring& name, DWORD pid, uint64_t created, elt::Source source_kind) {
    if (name.rfind(L"\\\\.\\pipe\\ELT-", 0) != 0 || name.size() != 45 ||
        name.find_first_not_of(L"0123456789abcdef", 13) != std::wstring::npos)
        throw std::runtime_error("invalid_private_pipe_name");
    Handle target{OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, pid)};
    wincheck(target.h != nullptr, "OpenProcess_target");
    wchar_t executable[32768]{};
    DWORD length = 32768;
    wincheck(QueryFullProcessImageNameW(target, 0, executable, &length), "QueryFullProcessImageName");
    const std::wstring path(executable);
    if (!elt::source_matches(source_kind, path))
        throw std::runtime_error("target_executable_does_not_match_selected_source");

    HANDLE token_raw = nullptr;
    wincheck(OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token_raw), "OpenProcessToken");
    Handle token{token_raw};
    DWORD size = 0;
    GetTokenInformation(token, TokenUser, nullptr, 0, &size);
    std::vector<uint8_t> info(size);
    wincheck(GetTokenInformation(token, TokenUser, info.data(), size, &size), "GetTokenInformation");
    LocalMemory sid;
    wincheck(ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(info.data())->User.Sid,
        reinterpret_cast<LPWSTR*>(&sid.p)), "ConvertSidToStringSid");
    std::wstring acl = L"D:P(A;;GA;;;" + std::wstring(static_cast<wchar_t*>(sid.p)) + L")";
    LocalMemory security;
    wincheck(ConvertStringSecurityDescriptorToSecurityDescriptorW(acl.c_str(), SDDL_REVISION_1,
        reinterpret_cast<PSECURITY_DESCRIPTOR*>(&security.p), nullptr), "ConvertStringSecurityDescriptor");
    SECURITY_ATTRIBUTES sa{sizeof(sa), security.p, FALSE};
    Handle pipe{CreateNamedPipeW(name.c_str(), PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
        PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS, 1, 65536, 65536, 0, &sa)};
    wincheck(pipe.h != INVALID_HANDLE_VALUE, "CreateNamedPipe");
    Handle connected{event_handle()};
    OVERLAPPED ov{}; ov.hEvent = connected;
    if (!ConnectNamedPipe(pipe, &ov)) {
        const auto err = GetLastError();
        if (err == ERROR_IO_PENDING) {
            if (WaitForSingleObject(connected, 10000) != WAIT_OBJECT_0) {
                CancelIoEx(pipe, &ov); DWORD ignored = 0;
                GetOverlappedResult(pipe, &ov, &ignored, TRUE);
                throw std::runtime_error("pipe_connect_timeout");
            }
            DWORD ignored = 0;
            wincheck(GetOverlappedResult(pipe, &ov, &ignored, TRUE), "ConnectNamedPipe_result");
        } else if (err != ERROR_PIPE_CONNECTED) check(HRESULT_FROM_WIN32(err), "ConnectNamedPipe");
    }
    if (read_control(pipe, 0, nullptr, 10000).kind != elt::Start) throw std::runtime_error("START_required");
    Handle stop{event_handle()};
    std::atomic<int> fault{0};
    Outbox out{fault, stop};
    std::thread reader([&] {
        try {
            for (uint64_t seq = 1;; ++seq) {
                auto h = read_control(pipe, seq, stop, INFINITE);
                if (h.kind == elt::Stop) { SetEvent(stop); return; }
                if (h.kind != elt::Status) throw std::runtime_error("invalid_control_state");
                // STATUS is answered by the capture thread's next heartbeat (< 1.25 s).
            }
        } catch (const std::exception& e) {
            if (WaitForSingleObject(stop, 0) != WAIT_OBJECT_0) {
                std::cerr << "{\"control_reader_error\":\"" << escape_json(e.what()) << "\"}\n";
                fault.store(1); SetEvent(stop);
            }
        }
    });
    std::thread writer;
    try { writer = std::thread([&] { out.write_loop(pipe); }); }
    catch (...) { SetEvent(stop); reader.join(); throw; }
    std::string error;
    try { capture(pid, created, target, stop, out, source_kind); }
    catch (const std::exception& e) { error = e.what(); }
    SetEvent(stop);
    reader.join();
    if (fault.load()) error += " transport_fault=" + std::to_string(fault.load()) + " audio_incomplete";
    if (error.empty()) out.push(elt::event(elt::Status, "{\"state\":\"stopped\"}"));
    else out.push(elt::event(elt::Error, "{\"error\":\"" + escape_json(error) + "\"}"));
    out.finish();
    writer.join();
    if (fault.load() && error.empty()) error = "transport_fault=" + std::to_string(fault.load()) + " audio_incomplete";
    if (!error.empty()) throw std::runtime_error(error);
}

int wmain(int argc, wchar_t** argv) {
    try {
        if ((argc != 7 && argc != 9) || std::wstring(argv[1]) != L"--pipe" || std::wstring(argv[3]) != L"--pid" ||
            std::wstring(argv[5]) != L"--created" || (argc == 9 && std::wstring(argv[7]) != L"--source"))
            throw std::runtime_error("usage: elt_capture --pipe NAME --pid PID --created FILETIME [--source vlc|chrome|edge|process]");
        const auto source_kind = argc == 9 ? elt::parse_source(argv[8]) : elt::Source::vlc;
        size_t used = 0;
        auto pid = std::stoull(argv[4], &used);
        if (used != wcslen(argv[4]) || !pid || pid > MAXDWORD) throw std::runtime_error("invalid_PID");
        auto created = std::stoull(argv[6], &used);
        if (used != wcslen(argv[6]) || !created) throw std::runtime_error("invalid_creation_time");
        run(argv[2], static_cast<DWORD>(pid), created, source_kind);
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "{\"error\":\"" << escape_json(e.what()) << "\"}\n";
        return 1;
    }
}
