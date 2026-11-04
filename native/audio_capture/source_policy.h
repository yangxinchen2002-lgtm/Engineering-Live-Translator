#pragma once
#include <stdexcept>
#include <string_view>

namespace elt {
enum class Source { vlc, chrome, edge, process };

inline Source parse_source(std::wstring_view value) {
    if (value == L"vlc") return Source::vlc;
    if (value == L"chrome") return Source::chrome;
    if (value == L"edge") return Source::edge;
    if (value == L"process") return Source::process;
    throw std::runtime_error("unsupported_audio_source");
}

inline const char* source_name(Source source) {
    switch (source) {
    case Source::vlc: return "vlc";
    case Source::chrome: return "chrome";
    case Source::edge: return "edge";
    case Source::process: return "process";
    }
    throw std::runtime_error("unsupported_audio_source");
}

inline bool source_matches(Source source, std::wstring_view path) {
    const auto slash = path.find_last_of(L"\\/");
    const auto name = path.substr(slash == std::wstring_view::npos ? 0 : slash + 1);
    if (source == Source::process) return !name.empty();
    const auto expected = source == Source::vlc ? L"vlc.exe" : source == Source::chrome ? L"chrome.exe" : L"msedge.exe";
    const std::wstring_view executable(expected);
    if (name.size() != executable.size()) return false;
    for (size_t i = 0; i < name.size(); ++i) {
        const auto c = name[i] >= L'A' && name[i] <= L'Z' ? name[i] + (L'a' - L'A') : name[i];
        if (c != executable[i]) return false;
    }
    return true;
}
}
