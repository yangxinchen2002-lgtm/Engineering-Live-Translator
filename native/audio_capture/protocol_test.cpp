#include "protocol.h"
#include <iostream>

int main() {
    auto m = elt::event(elt::Start, "{}");
    auto b = elt::encode(m, 0);
    if (b.size() != 58 || b[0] != 54 || b[4] != 1 || b[6] != 2) return 1;
    std::vector<uint8_t> body(b.begin() + 4, b.end());
    if (elt::decode_control(body, 0).kind != elt::Start) return 2;
    body[8] = 1;
    try { elt::decode_control(body, 0); return 3; } catch (const std::runtime_error&) {}
    m.payload.resize(elt::max_body);
    try { elt::encode(m, 0); return 4; } catch (const std::runtime_error&) {}
    std::cout << "native protocol passed\n";
}

