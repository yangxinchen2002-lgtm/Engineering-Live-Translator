#pragma once
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

namespace elt {
constexpr uint32_t max_body = 1024 * 1024;
enum Kind : uint16_t { Audio = 1, Start = 2, Stop = 3, Status = 4, Error = 5 };
enum Format : uint16_t { None = 0, S16 = 1, S24 = 2, S32 = 3, F32 = 4 };
#pragma pack(push, 1)
struct Header {
    uint16_t version = 1, kind = 0;
    uint64_t sequence = 0;
    uint32_t rate = 0;
    uint16_t channels = 0, format = 0;
    uint32_t frames = 0;
    uint64_t timestamp = 0, first_sample = 0;
    uint32_t flags = 0;
    uint16_t valid_bits = 0, reserved = 0;
    uint32_t channel_mask = 0;
};
#pragma pack(pop)
static_assert(sizeof(Header) == 52);
struct Message { Header header; std::vector<uint8_t> payload; };
inline Message event(Kind kind, const std::string& json) {
    Message m;
    m.header.kind = kind;
    m.payload.assign(json.begin(), json.end());
    return m;
}
inline std::vector<uint8_t> encode(Message m, uint64_t sequence) {
    const auto size = sizeof(Header) + m.payload.size();
    if (size > max_body) throw std::runtime_error("packet_too_large");
    const auto n = static_cast<uint32_t>(size);
    m.header.sequence = sequence;
    std::vector<uint8_t> out(4 + size);
    std::memcpy(out.data(), &n, 4);  // Windows x64 is little endian
    std::memcpy(out.data() + 4, &m.header, sizeof(Header));
    if (!m.payload.empty()) std::memcpy(out.data() + 4 + sizeof(Header), m.payload.data(), m.payload.size());
    return out;
}
inline Header decode_control(const std::vector<uint8_t>& body, uint64_t sequence) {
    if (body.size() != sizeof(Header) + 2 || body[52] != '{' || body[53] != '}')
        throw std::runtime_error("invalid_control_body");
    Header h;
    std::memcpy(&h, body.data(), sizeof(h));
    Header expected;
    expected.kind = h.kind;
    expected.sequence = sequence;
    if (std::memcmp(&h, &expected, sizeof(h)) ||
        (h.kind != Start && h.kind != Stop && h.kind != Status))
        throw std::runtime_error("invalid_control_header");
    return h;
}
} // namespace elt

