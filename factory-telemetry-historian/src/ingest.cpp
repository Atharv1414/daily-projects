#include "historian/ingest.hpp"

#include <atomic>
#include <istream>
#include <map>
#include <ostream>
#include <semaphore>
#include <string>
#include <thread>
#include <vector>

#include "historian/bounded_queue.hpp"

namespace historian {

namespace {

struct RawBatch {
    std::uint64_t sequence = 0;
    std::uint64_t first_line = 0;
    std::vector<std::string> lines;
};

struct Rejected {
    std::uint64_t line = 0;
    RejectReason reason = RejectReason::FieldCount;
    std::string text;
};

struct ParsedBatch {
    std::uint64_t sequence = 0;
    std::uint64_t lines = 0;
    std::vector<Point> points;
    std::vector<Rejected> rejected;
};

ParsedBatch parse_batch(RawBatch raw) {
    ParsedBatch out;
    out.sequence = raw.sequence;
    out.lines = raw.lines.size();
    out.points.reserve(raw.lines.size());
    for (std::size_t i = 0; i < raw.lines.size(); ++i) {
        auto parsed = parse_line(raw.lines[i]);
        if (auto* point = std::get_if<Point>(&parsed)) {
            out.points.push_back(std::move(*point));
        } else {
            out.rejected.push_back(
                {raw.first_line + i, std::get<RejectReason>(parsed), std::move(raw.lines[i])});
        }
    }
    return out;
}

}  // namespace

Result<IngestReport> ingest_csv(std::istream& in, Store& store, std::ostream& quarantine,
                                const IngestOptions& options) {
    if (options.parsers == 0 || options.batch_lines == 0 || options.max_in_flight == 0) {
        return Error{ErrorCode::InvalidArgument, "ingest options must be positive"};
    }
    // A ticket covers a batch from being read until being stored. That bounds memory even
    // when one slow parser makes the reorder buffer wait for its batch.
    std::counting_semaphore<> tickets(static_cast<std::ptrdiff_t>(options.max_in_flight));
    BoundedQueue<RawBatch> raw(options.max_in_flight);
    BoundedQueue<ParsedBatch> parsed(options.max_in_flight);
    std::atomic<bool> abort{false};
    std::atomic<unsigned> active_parsers{options.parsers};

    IngestReport report;
    Status failure;
    {
        // Declared after everything the threads use, so they join before it is destroyed.
        std::vector<std::jthread> threads;
        threads.emplace_back([&] {
            std::string line;
            std::uint64_t line_number = 0;
            std::uint64_t sequence = 0;
            RawBatch batch;
            const auto send = [&] {
                tickets.acquire();
                batch.sequence = sequence++;
                const bool sent = !abort.load() && raw.push(std::move(batch));
                batch = {};
                return sent;
            };
            while (std::getline(in, line)) {
                ++line_number;
                if (line_number == 1 && line.starts_with("timestamp,")) {
                    continue;  // header
                }
                if (batch.lines.empty()) {
                    batch.first_line = line_number;
                }
                batch.lines.push_back(std::move(line));
                if (batch.lines.size() == options.batch_lines && !send()) {
                    break;
                }
            }
            if (!batch.lines.empty() && !abort.load()) {
                static_cast<void>(send());
            }
            raw.close();
        });
        for (unsigned i = 0; i < options.parsers; ++i) {
            threads.emplace_back([&] {
                while (auto batch = raw.pop()) {
                    if (!parsed.push(parse_batch(std::move(*batch)))) {
                        break;
                    }
                }
                if (active_parsers.fetch_sub(1) == 1) {
                    parsed.close();  // last parser out
                }
            });
        }

        // File order matters: a later line must overwrite an earlier one.
        std::map<std::uint64_t, ParsedBatch> waiting;
        std::uint64_t next = 0;
        while (auto arrived = parsed.pop()) {
            const auto key = arrived->sequence;
            waiting.emplace(key, std::move(*arrived));
            for (auto it = waiting.find(next); it != waiting.end() && failure.ok();
                 it = waiting.find(next)) {
                const ParsedBatch& batch = it->second;
                failure = store.append(batch.points);
                if (!failure.ok()) {
                    break;
                }
                report.lines += batch.lines;
                report.accepted += batch.points.size();
                report.rejected += batch.rejected.size();
                for (const Rejected& r : batch.rejected) {
                    ++report.by_reason[static_cast<std::size_t>(r.reason)];
                    quarantine << r.line << ',' << to_string(r.reason) << ',' << r.text << '\n';
                }
                waiting.erase(it);
                ++next;
                tickets.release();
            }
            if (!failure.ok()) {
                abort.store(true);
                tickets.release();  // the reader may be blocked waiting for a ticket
                raw.close();
                parsed.close();
                break;
            }
        }
    }
    if (!failure.ok()) {
        return failure.error();
    }
    return report;
}

}  // namespace historian
