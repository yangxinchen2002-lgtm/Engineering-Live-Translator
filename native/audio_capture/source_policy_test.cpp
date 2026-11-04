#include "source_policy.h"
#include <iostream>

int main() {
    using elt::Source;
    if (!elt::source_matches(elt::parse_source(L"vlc"), L"C:\\VideoLAN\\VLC.EXE")) return 1;
    if (!elt::source_matches(elt::parse_source(L"chrome"), L"C:\\Program Files\\Chrome\\chrome.exe")) return 2;
    if (!elt::source_matches(elt::parse_source(L"edge"), L"C:/Program Files/Edge/MSEdge.exe")) return 3;
    if (elt::source_matches(Source::chrome, L"vlc.exe") || elt::source_matches(Source::vlc, L"chrome.exe")) return 4;
    if (elt::source_matches(Source::edge, L"msedgewebview2.exe") || elt::source_matches(Source::chrome, L"evilchrome.exe")) return 5;
    try { elt::parse_source(L"system"); return 6; } catch (const std::runtime_error&) {}
    try { elt::parse_source(L"firefox"); return 7; } catch (const std::runtime_error&) {}
    if (!elt::source_matches(elt::parse_source(L"process"), L"C:\\Music\\player.exe")) return 8;
    if (elt::source_matches(Source::process, L"") || elt::source_matches(Source::process, L"C:\\")) return 9;
    std::cout << "native source policy passed\n";
}
