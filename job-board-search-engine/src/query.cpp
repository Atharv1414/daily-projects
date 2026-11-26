#include "jobsearch/query.hpp"

#include <algorithm>
#include <charconv>

#include "jobsearch/text.hpp"

namespace jobsearch {
namespace {

enum class TokKind : std::uint8_t { Word, Phrase, LParen, RParen, Minus, And, Or, Not, End };

struct Tok {
    TokKind kind = TokKind::End;
    std::string text;   // Word: raw word; Phrase: the quoted text
    std::string field;  // Phrase: optional "title" / "body" prefix
    std::size_t pos = 0;
};

class Lexer {
  public:
    explicit Lexer(std::string_view s) : s_(s) {}

    std::vector<Tok> run() {
        std::vector<Tok> out;
        while (true) {
            while (i_ < s_.size() && is_space(s_[i_])) {
                ++i_;
            }
            if (i_ >= s_.size()) {
                out.push_back(Tok{TokKind::End, {}, {}, i_});
                return out;
            }
            const char c = s_[i_];
            const std::size_t start = i_;
            if (c == '(') {
                ++i_;
                out.push_back(Tok{TokKind::LParen, "(", {}, start});
            } else if (c == ')') {
                ++i_;
                out.push_back(Tok{TokKind::RParen, ")", {}, start});
            } else if (c == '-') {
                ++i_;
                out.push_back(Tok{TokKind::Minus, "-", {}, start});
            } else if (c == '"') {
                out.push_back(Tok{TokKind::Phrase, quoted(), {}, start});
            } else {
                std::string word;
                while (i_ < s_.size() && !is_space(s_[i_]) && s_[i_] != '(' && s_[i_] != ')' &&
                       s_[i_] != '"') {
                    word.push_back(s_[i_++]);
                }
                if (!word.empty() && word.back() == ':' && i_ < s_.size() && s_[i_] == '"') {
                    word.pop_back();
                    out.push_back(Tok{TokKind::Phrase, quoted(), word, start});
                } else if (word == "AND") {
                    out.push_back(Tok{TokKind::And, word, {}, start});
                } else if (word == "OR") {
                    out.push_back(Tok{TokKind::Or, word, {}, start});
                } else if (word == "NOT") {
                    out.push_back(Tok{TokKind::Not, word, {}, start});
                } else {
                    out.push_back(Tok{TokKind::Word, word, {}, start});
                }
            }
        }
    }

  private:
    static bool is_space(char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r'; }

    std::string quoted() {
        const std::size_t open = i_++;
        std::string text;
        while (i_ < s_.size() && s_[i_] != '"') {
            text.push_back(s_[i_++]);
        }
        if (i_ >= s_.size()) {
            throw QueryParseError("unterminated quote", open);
        }
        ++i_;
        return text;
    }

    std::string_view s_;
    std::size_t i_ = 0;
};

std::string lower(std::string_view s) {
    std::string out(s);
    std::ranges::transform(out, out.begin(), [](char c) {
        return (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c;
    });
    return out;
}

std::optional<Field> parse_field(std::string_view name) {
    if (name == "title") {
        return Field::Title;
    }
    if (name == "body") {
        return Field::Body;
    }
    return std::nullopt;
}

QueryPtr make(NodeKind kind) {
    auto n = std::make_unique<QueryNode>();
    n->kind = kind;
    return n;
}

class Parser {
  public:
    Parser(std::vector<Tok> toks, const ParseLimits& limits)
        : toks_(std::move(toks)), limits_(limits) {}

    QueryPtr parse() {
        if (peek().kind == TokKind::End) {
            return make(NodeKind::All);
        }
        auto node = parse_or();
        if (peek().kind != TokKind::End) {
            throw QueryParseError("unexpected '" + peek().text + "'", peek().pos);
        }
        if (!node) {
            throw QueryParseError("query has no searchable words", 0);
        }
        return node;
    }

  private:
    const Tok& peek() const { return toks_[i_]; }
    const Tok& take() { return toks_[i_++]; }

    static bool starts_unary(TokKind k) {
        return k == TokKind::Word || k == TokKind::Phrase || k == TokKind::LParen ||
               k == TokKind::Minus || k == TokKind::Not;
    }

    QueryPtr combine(NodeKind kind, std::vector<QueryPtr> parts) {
        std::erase(parts, nullptr);
        if (parts.empty()) {
            return nullptr;
        }
        if (parts.size() == 1) {
            return std::move(parts.front());
        }
        auto n = make(kind);
        for (auto& p : parts) {
            // Flatten (a AND (b AND c)) into one node so scoring sees all clauses at once.
            if (p->kind == kind) {
                for (auto& c : p->children) {
                    n->children.push_back(std::move(c));
                }
            } else {
                n->children.push_back(std::move(p));
            }
        }
        return n;
    }

    QueryPtr parse_or() {
        std::vector<QueryPtr> parts;
        parts.push_back(parse_and());
        while (peek().kind == TokKind::Or) {
            const auto& op = take();
            if (!starts_unary(peek().kind)) {
                throw QueryParseError("OR needs a clause after it", op.pos);
            }
            parts.push_back(parse_and());
        }
        return combine(NodeKind::Or, std::move(parts));
    }

    QueryPtr parse_and() {
        std::vector<QueryPtr> parts;
        parts.push_back(parse_unary());
        while (true) {
            if (peek().kind == TokKind::And) {
                const auto& op = take();
                if (!starts_unary(peek().kind)) {
                    throw QueryParseError("AND needs a clause after it", op.pos);
                }
            } else if (!starts_unary(peek().kind)) {
                break;
            }
            parts.push_back(parse_unary());
        }
        return combine(NodeKind::And, std::move(parts));
    }

    QueryPtr parse_unary() {
        const auto& t = peek();
        if (t.kind == TokKind::Minus || t.kind == TokKind::Not) {
            take();
            if (!starts_unary(peek().kind)) {
                throw QueryParseError("nothing to exclude", t.pos);
            }
            auto inner = parse_unary();
            if (!inner) {
                return nullptr;
            }
            auto n = make(NodeKind::Not);
            n->children.push_back(std::move(inner));
            return n;
        }
        return parse_primary();
    }

    QueryPtr parse_primary() {
        const Tok& t = take();
        switch (t.kind) {
            case TokKind::LParen: {
                if (++depth_ > limits_.max_depth) {
                    throw QueryParseError("parentheses nested too deeply", t.pos);
                }
                if (peek().kind == TokKind::RParen) {
                    throw QueryParseError("empty parentheses", t.pos);
                }
                auto inner = parse_or();
                if (peek().kind != TokKind::RParen) {
                    throw QueryParseError("missing ')'", t.pos);
                }
                take();
                --depth_;
                return inner;
            }
            case TokKind::Phrase: {
                std::optional<Field> field;
                if (!t.field.empty()) {
                    field = parse_field(lower(t.field));
                    if (!field) {
                        throw QueryParseError("unknown field '" + t.field + "'", t.pos);
                    }
                }
                return phrase(t.text, field, t.pos);
            }
            case TokKind::Word:
                return word(t);
            default:
                throw QueryParseError("unexpected '" + t.text + "'", t.pos);
        }
    }

    void count_clause(std::size_t pos) {
        if (++clauses_ > limits_.max_clauses) {
            throw QueryParseError("too many clauses", pos);
        }
    }

    QueryPtr phrase(std::string_view text, std::optional<Field> field, std::size_t pos) {
        const auto tokens = analyze(text);
        if (tokens.empty()) {
            return nullptr;
        }
        count_clause(pos);
        if (tokens.size() == 1) {
            auto n = make(NodeKind::Term);
            n->field = field;
            n->terms.push_back(tokens.front().term);
            return n;
        }
        auto n = make(NodeKind::Phrase);
        n->field = field;
        for (const auto& tok : tokens) {
            n->terms.push_back(tok.term);
            n->offsets.push_back(tok.position - tokens.front().position);
        }
        return n;
    }

    QueryPtr word(const Tok& t) {
        const std::string& raw = t.text;
        if (const auto ge = raw.find(">="); ge != std::string::npos) {
            return comparison(lower(raw.substr(0, ge)), raw.substr(ge + 2), t.pos);
        }
        if (const auto colon = raw.find(':'); colon != std::string::npos && colon > 0) {
            const auto key = lower(raw.substr(0, colon));
            const auto value = raw.substr(colon + 1);
            if (value.empty()) {
                throw QueryParseError("missing value after '" + key + ":'", t.pos);
            }
            if (const auto field = parse_field(key)) {
                return term_or_prefix(value, field, t.pos);
            }
            return filter(key, value, t.pos);
        }
        return term_or_prefix(raw, std::nullopt, t.pos);
    }

    QueryPtr term_or_prefix(std::string_view raw, std::optional<Field> field, std::size_t pos) {
        if (raw.ends_with('*')) {
            const auto stem_part = lower(raw.substr(0, raw.size() - 1));
            const auto words = split_words(stem_part);
            if (words.size() != 1 || words.front().size() < 2 || words.front() != stem_part) {
                throw QueryParseError("a prefix needs at least two letters before '*'", pos);
            }
            count_clause(pos);
            auto n = make(NodeKind::Prefix);
            n->field = field;
            n->terms.push_back(stem_part);
            return n;
        }
        // "front-end" or "e-commerce" split into several words: treat as a phrase.
        return phrase(raw, field, pos);
    }

    static std::uint32_t parse_number(std::string_view s, std::size_t pos) {
        std::string digits;
        for (const char c : s) {
            if (c != ',' && c != '_') {
                digits.push_back(c);
            }
        }
        if (!digits.empty() && (digits.back() == 'k' || digits.back() == 'K')) {
            digits.back() = '0';
            digits += "00";
        }
        std::uint32_t value = 0;
        const auto* begin = digits.data();
        const auto* end = digits.data() + digits.size();
        const auto [ptr, ec] = std::from_chars(begin, end, value);
        if (ec != std::errc{} || ptr != end || digits.empty()) {
            throw QueryParseError("expected a number, got '" + std::string(s) + "'", pos);
        }
        return value;
    }

    QueryPtr comparison(const std::string& key, std::string_view value, std::size_t pos) {
        if (key != "salary") {
            throw QueryParseError("only salary supports >=", pos);
        }
        count_clause(pos);
        auto n = make(NodeKind::Filter);
        n->filter.kind = FilterKind::MinSalary;
        auto v = value;
        if (v.starts_with("\xC2\xA3")) {  // a leading UTF-8 pound sign
            v.remove_prefix(2);
        }
        n->filter.number = parse_number(v, pos);
        return n;
    }

    QueryPtr filter(const std::string& key, std::string_view raw_value, std::size_t pos) {
        count_clause(pos);
        auto n = make(NodeKind::Filter);
        const auto value = lower(raw_value);
        if (key == "location" || key == "loc") {
            n->filter.kind = FilterKind::Location;
            n->filter.text = value;
        } else if (key == "contract") {
            n->filter.kind = FilterKind::Contract;
            if (value == "permanent" || value == "perm") {
                n->filter.contract = Contract::Permanent;
            } else if (value == "contract") {
                n->filter.contract = Contract::Contract;
            } else if (value == "temporary" || value == "temp") {
                n->filter.contract = Contract::Temporary;
            } else {
                throw QueryParseError("contract must be permanent, contract or temporary", pos);
            }
        } else if (key == "remote") {
            n->filter.kind = FilterKind::Remote;
            if (value == "yes" || value == "true") {
                n->filter.flag = true;
            } else if (value == "no" || value == "false") {
                n->filter.flag = false;
            } else {
                throw QueryParseError("remote must be yes or no", pos);
            }
        } else if (key == "days") {
            n->filter.kind = FilterKind::PostedWithin;
            n->filter.number = parse_number(value, pos);
        } else {
            throw QueryParseError("unknown field '" + key + "'", pos);
        }
        return n;
    }

    std::vector<Tok> toks_;
    ParseLimits limits_;
    std::size_t i_ = 0;
    std::size_t depth_ = 0;
    std::size_t clauses_ = 0;
};

std::string field_prefix(const QueryNode& n) {
    return n.field ? std::string(field_name(*n.field)) + ":" : std::string{};
}

void collect_highlights(const QueryNode& n, std::vector<std::string>& out) {
    switch (n.kind) {
        case NodeKind::Term:
        case NodeKind::Phrase:
            // Single characters ("1" in "class 1 licence") would light up every stray digit.
            for (const auto& t : n.terms) {
                if (t.size() > 1) {
                    out.push_back(t);
                }
            }
            break;
        case NodeKind::Prefix:
            out.push_back(n.terms.front() + "*");
            break;
        case NodeKind::And:
        case NodeKind::Or:
            for (const auto& c : n.children) {
                collect_highlights(*c, out);
            }
            break;
        default:
            break;
    }
}

}  // namespace

QueryPtr parse_query(std::string_view text, const ParseLimits& limits) {
    if (text.size() > limits.max_length) {
        throw QueryParseError(
            "query is longer than " + std::to_string(limits.max_length) + " bytes",
            limits.max_length);
    }
    Parser parser(Lexer(text).run(), limits);
    return parser.parse();
}

std::string to_string(const QueryNode& n) {
    switch (n.kind) {
        case NodeKind::All:
            return "*";
        case NodeKind::Term:
            return field_prefix(n) + n.terms.front();
        case NodeKind::Prefix:
            return field_prefix(n) + n.terms.front() + "*";
        case NodeKind::Phrase: {
            std::string out = field_prefix(n) + "\"";
            for (std::size_t i = 0; i < n.terms.size(); ++i) {
                out += (i == 0 ? "" : " ") + n.terms[i] + "@" + std::to_string(n.offsets[i]);
            }
            return out + "\"";
        }
        case NodeKind::And:
        case NodeKind::Or: {
            std::string out = n.kind == NodeKind::And ? "(AND" : "(OR";
            for (const auto& c : n.children) {
                out += " " + to_string(*c);
            }
            return out + ")";
        }
        case NodeKind::Not:
            return "(NOT " + to_string(*n.children.front()) + ")";
        case NodeKind::Filter:
            switch (n.filter.kind) {
                case FilterKind::MinSalary:
                    return "[salary>=" + std::to_string(n.filter.number) + "]";
                case FilterKind::Location:
                    return "[location=" + n.filter.text + "]";
                case FilterKind::Contract:
                    return "[contract=" + std::string(contract_name(n.filter.contract)) + "]";
                case FilterKind::Remote:
                    return std::string("[remote=") + (n.filter.flag ? "yes" : "no") + "]";
                case FilterKind::PostedWithin:
                    return "[days<=" + std::to_string(n.filter.number) + "]";
            }
    }
    return "?";
}

std::vector<std::string> highlight_terms(const QueryNode& node) {
    std::vector<std::string> out;
    collect_highlights(node, out);
    std::ranges::sort(out);
    const auto [first, last] = std::ranges::unique(out);
    out.erase(first, last);
    return out;
}

}  // namespace jobsearch
