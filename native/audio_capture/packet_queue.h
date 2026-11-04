#pragma once
#include "protocol.h"
#include <array>
#include <atomic>

namespace elt {
// Exactly one producer and one consumer. Slot ownership transfers with acquire/release.
class PacketQueue {
    std::array<Message, 257> slots;
    std::atomic<size_t> head{0}, tail{0}, bytes{0};
public:
    bool push(Message m) {
        const auto h = head.load(std::memory_order_relaxed);
        const auto next = (h + 1) % slots.size();
        if (next == tail.load(std::memory_order_acquire) || bytes.load() + m.payload.size() > 4 * 1024 * 1024)
            return false;
        bytes.fetch_add(m.payload.size());
        slots[h] = std::move(m);
        head.store(next, std::memory_order_release);
        return true;
    }
    bool pop(Message& m) {
        const auto t = tail.load(std::memory_order_relaxed);
        if (t == head.load(std::memory_order_acquire)) return false;
        m = std::move(slots[t]);
        bytes.fetch_sub(m.payload.size());
        tail.store((t + 1) % slots.size(), std::memory_order_release);
        return true;
    }
    size_t depth() const { return (head.load() + slots.size() - tail.load()) % slots.size(); }
    size_t payload_bytes() const { return bytes.load(); }
};
}
