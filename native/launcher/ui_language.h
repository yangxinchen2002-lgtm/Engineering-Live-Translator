#pragma once
// Read only the bounded, non-secret UI preference. No credentials are loaded.
inline bool english_ui = false;
inline const wchar_t* text(const wchar_t* chinese, const wchar_t* english) {
    return english_ui ? english : chinese;
}
inline void load_ui_language() noexcept {
    try {
        wchar_t folder[32768]{}, profile[128]{};
        DWORD size = GetEnvironmentVariableW(L"LOCALAPPDATA", folder, 32768);
        if (!size || size >= 32768) return;
        fs::path path = fs::path(folder) / L"ELT";
        DWORD count = GetEnvironmentVariableW(L"ELT_PROFILE_ID", profile, 128);
        if (count && count < 128 && std::regex_match(profile, std::wregex(L"portable-[0-9a-f]{32}")))
            path /= fs::path(L"profiles") / profile;
        path /= L"ui-settings.json";
        if (!fs::is_regular_file(path) || fs::file_size(path) > 16384) return;
        std::ifstream input(path, std::ios::binary);
        std::string data((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
        english_ui = std::regex_search(data, std::regex(R"ui("ui_language"\s*:\s*"en")ui"));
    } catch (...) { /* A broken preference cannot prevent error reporting. */ }
}
