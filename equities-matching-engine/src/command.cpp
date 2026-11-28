#include "lob/command.hpp"

#include <charconv>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace lob {

namespace {

template <class... Fs>
struct Overloaded : Fs... {
    using Fs::operator()...;
};
template <class... Fs>
Overloaded(Fs...) -> Overloaded<Fs...>;

std::vector<std::string_view> split(std::string_view line) {
    std::vector<std::string_view> out;
    std::size_t i = 0;
    while (i < line.size()) {
        while (i < line.size() && (line[i] == ' ' || line[i] == '\t')) ++i;
        const std::size_t start = i;
        while (i < line.size() && line[i] != ' ' && line[i] != '\t') ++i;
        if (i > start) out.push_back(line.substr(start, i - start));
    }
    return out;
}

template <class Int>
bool parse_int(std::string_view text, Int& out) {
    if (text.empty()) return false;
    const auto [ptr, ec] = std::from_chars(text.data(), text.data() + text.size(), out);
    return ec == std::errc{} && ptr == text.data() + text.size();
}

using Fields = std::map<std::string, std::string, std::less<>>;

Result<Fields> parse_fields(const std::vector<std::string_view>& tokens,
                            const std::set<std::string, std::less<>>& allowed) {
    Fields fields;
    for (std::size_t i = 1; i < tokens.size(); ++i) {
        const auto eq = tokens[i].find('=');
        if (eq == std::string_view::npos || eq == 0) {
            return Result<Fields>::failure("expected key=value, got '" + std::string(tokens[i]) +
                                           "'");
        }
        std::string key(tokens[i].substr(0, eq));
        if (!allowed.contains(key)) return Result<Fields>::failure("unknown field '" + key + "'");
        if (fields.contains(key)) return Result<Fields>::failure("repeated field '" + key + "'");
        fields.emplace(std::move(key), std::string(tokens[i].substr(eq + 1)));
    }
    if (!fields.contains("sym") || fields.at("sym").empty()) {
        return Result<Fields>::failure("missing sym=");
    }
    return fields;
}

template <class Int>
Result<Int> required_int(const Fields& f, const char* key) {
    const auto it = f.find(key);
    if (it == f.end()) return Result<Int>::failure(std::string("missing ") + key + "=");
    Int v{};
    if (!parse_int(it->second, v)) {
        return Result<Int>::failure(std::string("bad number for ") + key + ": '" + it->second +
                                    "'");
    }
    return v;
}

}  // namespace

const std::string& symbol_of(const Command& c) noexcept {
    return std::visit([](const auto& cmd) -> const std::string& { return cmd.symbol; }, c);
}

Result<Price> parse_price(std::string_view text) {
    const auto dot = text.find('.');
    const std::string_view whole = text.substr(0, dot);
    std::int64_t pence = 0;
    if (!parse_int(whole, pence) || pence < 0) {
        return Result<Price>::failure("bad price '" + std::string(text) + "'");
    }
    std::int64_t fraction = 0;
    if (dot != std::string_view::npos) {
        std::string_view frac = text.substr(dot + 1);
        if (frac.empty() || frac.size() > 2) {
            return Result<Price>::failure("price needs 1-2 decimals: '" + std::string(text) + "'");
        }
        if (!parse_int(frac, fraction) || fraction < 0) {
            return Result<Price>::failure("bad price '" + std::string(text) + "'");
        }
        if (frac.size() == 1) fraction *= 10;
    }
    return Price{pence * kPriceUnitsPerPenny + fraction};
}

Result<Command> parse_command(std::string_view line) {
    using R = Result<Command>;
    const auto tokens = split(line);
    if (tokens.empty()) return R::failure("empty command");
    const std::string_view verb = tokens[0];

    if (verb == "NEW") {
        auto fields = parse_fields(tokens, {"sym", "id", "owner", "side", "type", "tif", "px",
                                            "qty", "peak", "post", "stp"});
        if (!fields) return R::failure(fields.error());
        const Fields& f = fields.value();
        SubmitCmd cmd;
        cmd.symbol = f.at("sym");
        auto id = required_int<OrderId>(f, "id");
        if (!id) return R::failure(id.error());
        cmd.order.id = id.value();
        auto owner = required_int<ParticipantId>(f, "owner");
        if (!owner) return R::failure(owner.error());
        cmd.order.owner = owner.value();
        auto qty = required_int<Qty>(f, "qty");
        if (!qty) return R::failure(qty.error());
        cmd.order.qty = qty.value();

        const auto side = f.find("side");
        if (side == f.end()) return R::failure("missing side=");
        if (side->second == "B") {
            cmd.order.side = Side::Buy;
        } else if (side->second == "S") {
            cmd.order.side = Side::Sell;
        } else {
            return R::failure("side must be B or S");
        }

        const auto type = f.find("type");
        const std::string t = type == f.end() ? "LMT" : type->second;
        if (t == "LMT") {
            cmd.order.type = OrderType::Limit;
        } else if (t == "MKT") {
            cmd.order.type = OrderType::Market;
        } else if (t == "ICE") {
            cmd.order.type = OrderType::Iceberg;
        } else {
            return R::failure("type must be LMT, MKT or ICE");
        }

        const auto tif = f.find("tif");
        const std::string ti = tif == f.end() ? "DAY" : tif->second;
        if (ti == "DAY") {
            cmd.order.tif = TimeInForce::Day;
        } else if (ti == "IOC") {
            cmd.order.tif = TimeInForce::IOC;
        } else if (ti == "FOK") {
            cmd.order.tif = TimeInForce::FOK;
        } else {
            return R::failure("tif must be DAY, IOC or FOK");
        }

        if (cmd.order.type != OrderType::Market) {
            const auto px = f.find("px");
            if (px == f.end()) return R::failure("missing px=");
            auto price = parse_price(px->second);
            if (!price) return R::failure(price.error());
            cmd.order.price = price.value();
        } else if (f.contains("px")) {
            return R::failure("market orders take no px=");
        }

        if (const auto peak = f.find("peak"); peak != f.end()) {
            Qty p = 0;
            if (!parse_int(peak->second, p)) return R::failure("bad peak=");
            cmd.order.display_qty = p;
        }
        if (const auto post = f.find("post"); post != f.end()) {
            if (post->second != "0" && post->second != "1") return R::failure("post must be 0/1");
            cmd.order.post_only = post->second == "1";
        }
        if (const auto stp = f.find("stp"); stp != f.end()) {
            if (stp->second == "NONE") {
                cmd.order.stp = StpMode::None;
            } else if (stp->second == "CR") {
                cmd.order.stp = StpMode::CancelResting;
            } else if (stp->second == "CI") {
                cmd.order.stp = StpMode::CancelIncoming;
            } else if (stp->second == "CB") {
                cmd.order.stp = StpMode::CancelBoth;
            } else {
                return R::failure("stp must be NONE, CR, CI or CB");
            }
        }
        return Command{std::move(cmd)};
    }

    if (verb == "CXL") {
        auto fields = parse_fields(tokens, {"sym", "id"});
        if (!fields) return R::failure(fields.error());
        auto id = required_int<OrderId>(fields.value(), "id");
        if (!id) return R::failure(id.error());
        return Command{CancelCmd{fields.value().at("sym"), CancelOrder{id.value()}}};
    }

    if (verb == "AMD") {
        auto fields = parse_fields(tokens, {"sym", "id", "px", "qty"});
        if (!fields) return R::failure(fields.error());
        const Fields& f = fields.value();
        auto id = required_int<OrderId>(f, "id");
        if (!id) return R::failure(id.error());
        auto qty = required_int<Qty>(f, "qty");
        if (!qty) return R::failure(qty.error());
        const auto px = f.find("px");
        if (px == f.end()) return R::failure("missing px=");
        auto price = parse_price(px->second);
        if (!price) return R::failure(price.error());
        return Command{AmendCmd{f.at("sym"), AmendOrder{id.value(), price.value(), qty.value()}}};
    }

    const std::map<std::string_view, SessionCmd::Kind> sessions{
        {"AUCTION", SessionCmd::Kind::StartAuction},
        {"UNCROSS", SessionCmd::Kind::Uncross},
        {"HALT", SessionCmd::Kind::Halt},
        {"RESUME", SessionCmd::Kind::Resume},
    };
    if (const auto it = sessions.find(verb); it != sessions.end()) {
        auto fields = parse_fields(tokens, {"sym"});
        if (!fields) return R::failure(fields.error());
        return Command{SessionCmd{fields.value().at("sym"), it->second}};
    }
    return R::failure("unknown command '" + std::string(verb) + "'");
}

namespace {

std::string price_text(Price p) {
    std::string s = format_price(p);
    s.pop_back();  // drop the trailing 'p'
    return s;
}

}  // namespace

std::string format_command(const Command& c) {
    return std::visit(
        Overloaded{
            [](const SubmitCmd& s) {
                const NewOrder& o = s.order;
                std::string out = "NEW sym=" + s.symbol + " id=" + std::to_string(o.id) +
                                  " owner=" + std::to_string(o.owner) +
                                  " side=" + (o.side == Side::Buy ? "B" : "S") +
                                  " type=" + std::string(to_string(o.type)) +
                                  " tif=" + std::string(to_string(o.tif));
                if (o.type != OrderType::Market) out += " px=" + price_text(o.price);
                out += " qty=" + std::to_string(o.qty);
                if (o.display_qty != 0) out += " peak=" + std::to_string(o.display_qty);
                if (o.post_only) out += " post=1";
                static constexpr const char* kStp[] = {"NONE", "CR", "CI", "CB"};
                out += std::string(" stp=") + kStp[static_cast<std::size_t>(o.stp)];
                return out;
            },
            [](const CancelCmd& c2) {
                return "CXL sym=" + c2.symbol + " id=" + std::to_string(c2.request.id);
            },
            [](const AmendCmd& a) {
                return "AMD sym=" + a.symbol + " id=" + std::to_string(a.request.id) +
                       " px=" + price_text(a.request.new_price) +
                       " qty=" + std::to_string(a.request.new_qty);
            },
            [](const SessionCmd& s) {
                static constexpr const char* kVerb[] = {"AUCTION", "UNCROSS", "HALT", "RESUME"};
                return std::string(kVerb[static_cast<std::size_t>(s.kind)]) + " sym=" + s.symbol;
            },
        },
        c);
}

}  // namespace lob
