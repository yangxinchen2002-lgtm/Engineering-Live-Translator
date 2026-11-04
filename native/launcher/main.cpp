// Native Windows GUI entry point. No cmd.exe, shell script or console window.
#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <shobjidl.h>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <regex>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;
#include "ui_language.h"

struct Failure : std::runtime_error {
    std::wstring message;
    explicit Failure(std::wstring value) : std::runtime_error("ELT launcher error"), message(std::move(value)) {}
};

fs::path executable_path() {
    std::vector<wchar_t> buffer(32768);
    DWORD count = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
    if (!count || count >= buffer.size()) throw Failure(text(L"无法取得程序位置。", L"Cannot locate the application."));
    return fs::path(std::wstring(buffer.data(), count));
}

void check_hr(HRESULT result, const wchar_t* action) {
    if (FAILED(result)) throw Failure(std::wstring(action) + text(L"（Windows 错误码 ", L" (Windows error ") + std::to_wstring(static_cast<unsigned long>(result)) + text(L"）。", L")."));
}

// Microsoft command-line quoting, including backslashes before quotes/end.
std::wstring quote(const std::wstring& value) {
    std::wstring result = L"\""; size_t backslashes = 0;
    for (wchar_t character : value) {
        if (character == L'\\') { ++backslashes; continue; }
        if (character == L'\"') result.append(backslashes * 2 + 1, L'\\');
        else result.append(backslashes, L'\\');
        result += character; backslashes = 0;
    }
    result.append(backslashes * 2, L'\\'); result += L'\"'; return result;
}

bool configure_profile(const fs::path& root) {
    const fs::path metadata = root / L"distribution.json";
    if (!fs::exists(metadata)) {
        // Local development install retains its existing normal settings/key.
        SetEnvironmentVariableW(L"ELT_PROFILE_ID", nullptr);
        return false;
    }
    if (fs::file_size(metadata) > 16384) throw Failure(text(L"便携版配置损坏，请重新解压完整程序。", L"Portable settings are damaged. Extract the complete application again."));
    std::ifstream stream(metadata, std::ios::binary);
    std::string data((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
    std::regex pattern(R"profile("profile"\s*:\s*"(portable-[0-9a-f]{32})")profile");
    std::smatch match;
    if (!stream || !std::regex_search(data, match, pattern)) throw Failure(text(L"便携版配置无效，请重新解压完整程序。", L"Invalid portable settings. Extract the complete application again."));
    std::string profile = match[1].str(); std::wstring wide(profile.begin(), profile.end());
    if (!SetEnvironmentVariableW(L"ELT_PROFILE_ID", wide.c_str()) ||
        !SetEnvironmentVariableW(L"DEEPSEEK_API_KEY", nullptr) ||
        !SetEnvironmentVariableW(L"HF_HUB_OFFLINE", L"1")) throw Failure(text(L"无法初始化独立配置。", L"Cannot initialize the separate application profile."));
    return true;
}

DWORD run(const fs::path& root, bool diagnostic, const fs::path& report) {
    bool portable = configure_profile(root);
    load_ui_language();
    fs::path folder = portable ? root / L"runtime/python" : root / L".venv/Scripts";
    fs::path python = folder / (diagnostic ? L"python.exe" : L"pythonw.exe");
    if (!fs::is_regular_file(python)) throw Failure(text(L"未找到运行环境。请保留 ELT.exe 与程序、模型和运行库所在的完整文件夹。", L"Runtime not found. Keep ELT.exe with the complete application, models and runtime folders."));
    std::wstring command = quote(python.wstring()) + L" -B ";
    if (diagnostic) {
        // A real widget initialization check, not synthesized subtitle output.
        const std::wstring script =
            L"import sys,json;from pathlib import Path;from PySide6.QtWidgets import QApplication;"
            L"from PySide6.QtTest import QTest;from app.ui.window import MainWindow,STYLE;"
            L"from app.asr.config import ROOT;from app.profile import profile_id;"
            L"from app.ui.preferences import PreferencesStore,default_path;"
            L"a=QApplication([]);a.setStyle('Fusion');a.setStyleSheet(STYLE);w=MainWindow(preferences=PreferencesStore(default_path()));"
            L"w.show();QTest.qWait(350);a.processEvents();"
            L"r={'window_visible':w.isVisible(),'capture_running':w.controller.running,"
            L"'translation_enabled':w.translate_check.isChecked(),'profile':profile_id(),"
            L"'python':sys.executable,'root':str(ROOT),'isolated':sys.flags.isolated,'ui_language':w.settings.ui_language};"
            L"w.close();a.processEvents();Path(sys.argv[1]).write_text(json.dumps(r),encoding='utf-8')";
        command += L"-c " + quote(script) + L" " + quote(report.wstring());
    } else command += L"-m app.ui.main";
    STARTUPINFOW startup{}; startup.cb = sizeof(startup);
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(python.c_str(), command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW,
                        nullptr, root.c_str(), &startup, &process))
        throw Failure(text(L"ELT 无法启动（Windows 错误码 ", L"ELT could not start (Windows error ") + std::to_wstring(GetLastError()) + text(L"）。", L")."));
    CloseHandle(process.hThread);
    if (!diagnostic) { CloseHandle(process.hProcess); return 0; }
    DWORD result = WaitForSingleObject(process.hProcess, 60000), code = 1;
    if (result == WAIT_OBJECT_0) GetExitCodeProcess(process.hProcess, &code);
    else { TerminateProcess(process.hProcess, 1); WaitForSingleObject(process.hProcess, 5000); }
    CloseHandle(process.hProcess); return code;
}

struct Apartment {
    Apartment() { check_hr(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED), text(L"无法初始化桌面快捷方式组件", L"Cannot initialize desktop shortcut support")); }
    ~Apartment() { CoUninitialize(); }
};
template<class T> struct Com {
    T* value = nullptr;
    ~Com() { if (value) value->Release(); }
    T** address() { return &value; }
    T* operator->() { return value; }
};

fs::path create_shortcut(const fs::path& root) {
    fs::path target = root / L"ELT.exe";
    if (!fs::is_regular_file(target)) throw Failure(text(L"请将快捷方式工具与 ELT.exe 放在同一个程序文件夹。", L"Keep the shortcut tool and ELT.exe in the same application folder."));
    Apartment apartment; PWSTR desktop = nullptr;
    check_hr(SHGetKnownFolderPath(FOLDERID_Desktop, 0, nullptr, &desktop), text(L"无法取得桌面位置", L"Cannot locate the desktop"));
    fs::path directory(desktop); CoTaskMemFree(desktop);
    fs::path destination;
    for (int number = 1; number <= 100; ++number) {
        std::wstring name = text(L"ELT 工科实时字幕", L"ELT Live Subtitles") + (number == 1 ? std::wstring() : L" (" + std::to_wstring(number) + L")") + L".lnk";
        fs::path candidate = directory / name;
        if (!fs::exists(candidate)) { destination = candidate; break; }
        Com<IShellLinkW> old_link; Com<IPersistFile> old_file;
        if (SUCCEEDED(CoCreateInstance(CLSID_ShellLink, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(old_link.address()))) &&
            SUCCEEDED(old_link->QueryInterface(IID_PPV_ARGS(old_file.address()))) && SUCCEEDED(old_file->Load(candidate.c_str(), STGM_READ))) {
            wchar_t old_target[32768]{};
            if (SUCCEEDED(old_link->GetPath(old_target, 32768, nullptr, SLGP_RAWPATH)) &&
                _wcsicmp(old_target, target.c_str()) == 0) { destination = candidate; break; }
        }
    }
    if (destination.empty()) throw Failure(text(L"同名桌面快捷方式过多，请手动整理后重试。", L"Too many shortcuts have this name. Organize your desktop and try again."));
    Com<IShellLinkW> link; Com<IPersistFile> file;
    check_hr(CoCreateInstance(CLSID_ShellLink, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(link.address())), text(L"无法创建快捷方式", L"Cannot create the shortcut"));
    check_hr(link->SetPath(target.c_str()), text(L"无法设置启动路径", L"Cannot set the launch path"));
    check_hr(link->SetWorkingDirectory(root.c_str()), text(L"无法设置程序目录", L"Cannot set the application folder"));
    check_hr(link->SetDescription(text(L"Engineering Live Translator · 工科实时字幕", L"Engineering Live Translator · Live subtitles")), text(L"无法设置说明", L"Cannot set the description"));
    fs::path icon = root / L"app" / L"ui" / L"assets" / L"elt.ico";
    if (!fs::is_regular_file(icon)) icon = target;
    check_hr(link->SetIconLocation(icon.c_str(), 0), text(L"无法设置图标", L"Cannot set the icon"));
    check_hr(link->QueryInterface(IID_PPV_ARGS(file.address())), text(L"无法保存快捷方式", L"Cannot save the shortcut"));
    check_hr(file->Save(destination.c_str(), TRUE), text(L"无法写入桌面快捷方式", L"Cannot write the desktop shortcut"));
    SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW | SHCNF_FLUSHNOWAIT, destination.c_str(), nullptr);
    return destination;
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    load_ui_language();
    bool quiet = false;
    try {
        fs::path exe = executable_path(), root = exe.parent_path(), report;
        bool shortcut = exe.filename() == L"创建桌面快捷方式.exe", diagnostic = false;
        int count = 0; LPWSTR* arguments = CommandLineToArgvW(GetCommandLineW(), &count);
        if (!arguments) throw Failure(text(L"无法读取启动参数。", L"Cannot read launch arguments."));
        for (int i = 1; i < count; ++i) {
            std::wstring argument(arguments[i]);
            if (argument == L"--quiet") quiet = true;
            else if (argument == L"--create-shortcut") shortcut = true;
            else if (argument == L"--check") diagnostic = true;
            else if (argument == L"--report" && i + 1 < count) report = arguments[++i];
            else { LocalFree(arguments); throw Failure(text(L"启动参数无效。", L"Invalid launch arguments.")); }
        }
        LocalFree(arguments);
        if (shortcut) {
            fs::path created = create_shortcut(root);
            if (!quiet) MessageBoxW(nullptr, (text(L"桌面快捷方式已创建：\n", L"Desktop shortcut created:\n") + created.wstring()).c_str(), L"ELT", MB_OK | MB_ICONINFORMATION);
            return 0;
        }
        if (diagnostic && report.empty()) throw Failure(text(L"启动检查需要指定报告路径。", L"The startup check requires a report path."));
        return static_cast<int>(run(root, diagnostic, report));
    } catch (const Failure& failure) {
        if (!quiet) MessageBoxW(nullptr, failure.message.c_str(), text(L"ELT 启动失败", L"ELT could not start"), MB_OK | MB_ICONERROR);
        return 1;
    } catch (const std::exception&) {
        if (!quiet) MessageBoxW(nullptr, text(L"程序入口出现错误，请检查程序目录是否完整。", L"The launcher failed. Check that the application folder is complete."), L"ELT", MB_OK | MB_ICONERROR);
        return 1;
    }
}
