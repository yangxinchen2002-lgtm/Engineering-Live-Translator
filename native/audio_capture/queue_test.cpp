#include "packet_queue.h"
#include <iostream>
#include <thread>

int main() {
    elt::PacketQueue queue;
    for (int i = 0; i < 256; ++i) if (!queue.push(elt::event(elt::Status, "{}"))) return 1;
    if (queue.push(elt::event(elt::Status, "{}"))) return 2;
    elt::Message m;
    for (int i = 0; i < 256; ++i) if (!queue.pop(m)) return 3;
    if (queue.pop(m) || queue.depth() || queue.payload_bytes()) return 4;
    m.payload.resize(4 * 1024 * 1024);
    if (!queue.push(std::move(m)) || queue.push(elt::event(elt::Status, "{}"))) return 5;
    if (!queue.pop(m)) return 6;
    std::atomic<bool> failed{false};
    std::thread consumer([&] {
        for (uint64_t i = 0; i < 100000; ++i) {
            elt::Message received;
            while (!queue.pop(received)) std::this_thread::yield();
            if (received.header.sequence != i || received.payload.size() != 2) failed.store(true);
        }
    });
    for (uint64_t i = 0; i < 100000; ++i) {
        auto next = elt::event(elt::Status, "{}");
        next.header.sequence = i;
        // Retrying is a TEST stress harness behavior, never used on capture path.
        while (!queue.push(next)) std::this_thread::yield();
    }
    consumer.join();
    if (failed.load() || queue.depth() || queue.payload_bytes()) return 7;
    std::cout << "SPSC bounds and 100000-message ordering passed\n";
}
