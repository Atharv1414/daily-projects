#include "jobsearch/corpus.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <span>
#include <string>
#include <string_view>

namespace jobsearch {
namespace {

struct Family {
    std::string_view title;
    std::uint32_t base_salary;  // national median for the mid-level role, pounds
    std::array<std::string_view, 8> skills;
    std::string_view sector;
    double remote_share;
    double contract_share;
};

constexpr std::array<Family, 14> kFamilies{{
    {"Software Engineer",
     52'000,
     {"C++", "C#", "Python", "Go", "Kubernetes", "AWS", "microservices", "TDD"},
     "technology",
     0.45,
     0.15},
    {"Data Engineer",
     55'000,
     {"Python", "SQL", "Spark", "Airflow", "dbt", "Kafka", "Snowflake", "data modelling"},
     "technology",
     0.5,
     0.2},
    {"Data Analyst",
     38'000,
     {"SQL", "Power BI", "Excel", "Python", "Tableau", "statistics", "stakeholder reporting",
      "A/B testing"},
     "analytics",
     0.4,
     0.1},
    {"Front-End Developer",
     47'000,
     {"React", "TypeScript", "JavaScript", "CSS", "accessibility", "Next.js", "design systems",
      "testing"},
     "technology",
     0.5,
     0.2},
    {"Registered Nurse",
     33'000,
     {"NMC registration", "patient care", "medication rounds", "Band 5", "Band 6",
      "ward experience", "triage", "clinical audit"},
     "healthcare",
     0.0,
     0.25},
    {"HGV Driver",
     36'000,
     {"Class 1 licence", "CPC", "tachograph", "night shifts", "multi-drop", "ADR", "trunking",
      "forklift"},
     "logistics",
     0.0,
     0.3},
    {"Warehouse Operative",
     24'500,
     {"pick and pack", "forklift", "RF scanner", "stock control", "goods in", "shift work",
      "health and safety", "loading"},
     "logistics",
     0.0,
     0.45},
    {"Primary Teacher",
     35'000,
     {"QTS", "KS1", "KS2", "phonics", "SEND", "safeguarding", "curriculum planning",
      "behaviour management"},
     "education",
     0.0,
     0.15},
    {"Accountant",
     46'000,
     {"ACCA", "CIMA", "month end", "Xero", "Sage", "management accounts", "VAT returns", "audit"},
     "finance",
     0.3,
     0.15},
    {"Chef de Partie",
     28'000,
     {"food hygiene", "fresh produce", "menu development", "fine dining", "allergens",
      "section management", "split shifts", "banqueting"},
     "hospitality",
     0.0,
     0.2},
    {"Recruitment Consultant",
     27'000,
     {"360 recruitment", "business development", "candidate sourcing", "LinkedIn Recruiter",
      "commission", "client management", "Bullhorn", "KPIs"},
     "recruitment",
     0.2,
     0.05},
    {"Project Manager",
     54'000,
     {"PRINCE2", "Agile", "stakeholder management", "budgets", "risk management", "Jira", "MSP",
      "change management"},
     "professional services",
     0.35,
     0.3},
    {"Electrician",
     38'000,
     {"18th Edition", "ECS card", "domestic installs", "commercial fit-out",
      "testing and inspection", "NVQ Level 3", "fault finding", "solar PV"},
     "construction",
     0.0,
     0.35},
    {"Customer Service Advisor",
     23'500,
     {"inbound calls", "CRM", "complaints handling", "live chat", "first contact resolution",
      "shift patterns", "retention", "billing queries"},
     "customer service",
     0.35,
     0.2},
}};

struct Seniority {
    std::string_view prefix;
    double multiplier;
    double weight;
};

constexpr std::array<Seniority, 5> kSeniority{{
    {"Junior ", 0.72, 0.18},
    {"", 1.0, 0.42},
    {"Senior ", 1.3, 0.25},
    {"Lead ", 1.5, 0.1},
    {"Head of ", 1.85, 0.05},
}};

struct Region {
    std::string_view city;
    double salary_factor;
    double weight;
};

constexpr std::array<Region, 12> kRegions{{
    {"London", 1.22, 0.24},
    {"Manchester", 1.0, 0.1},
    {"Birmingham", 0.98, 0.09},
    {"Leeds", 0.97, 0.08},
    {"Bristol", 1.03, 0.07},
    {"Glasgow", 0.95, 0.07},
    {"Edinburgh", 1.01, 0.06},
    {"Cardiff", 0.93, 0.05},
    {"Newcastle", 0.92, 0.05},
    {"Belfast", 0.9, 0.04},
    {"Nottingham", 0.94, 0.05},
    {"Reading", 1.08, 0.1},
}};

constexpr std::array<std::string_view, 16> kCompanies{
    "Northgate Digital",      "Harbour Health Trust",  "Pennine Logistics",
    "Kestrel Analytics",      "Brightwater Academies", "Albion Retail Group",
    "Severn Energy",          "Thistle Bank",          "Copperleaf Consulting",
    "Greystone Construction", "Meridian Hotels",       "Oakfield Care",
    "Lumen Software",         "Fenland Foods",         "Riverside Council Services",
    "Atlas Talent Partners"};

constexpr std::array<std::string_view, 8> kBenefits{"25 days holiday plus bank holidays",
                                                    "a 6% matched pension",
                                                    "private medical cover",
                                                    "hybrid working with two office days",
                                                    "an annual training budget of £1,500",
                                                    "cycle-to-work and season ticket loans",
                                                    "enhanced parental leave",
                                                    "a yearly performance bonus"};

template <typename T>
const T& weighted(Rng& rng, std::span<const T> items) {
    double total = 0.0;
    for (const auto& item : items) {
        total += item.weight;
    }
    double r = rng.unit() * total;
    for (const auto& item : items) {
        r -= item.weight;
        if (r < 0.0) {
            return item;
        }
    }
    return items.back();
}

template <typename T, std::size_t N>
const T& pick(Rng& rng, const std::array<T, N>& items) {
    return items[static_cast<std::size_t>(rng.below(N))];
}

std::uint32_t round_to(double value, std::uint32_t step) {
    const auto steps = std::llround(value / static_cast<double>(step));
    return static_cast<std::uint32_t>(steps) * step;
}

std::string pounds(std::uint32_t value) {
    auto digits = std::to_string(value);
    for (auto i = static_cast<std::ptrdiff_t>(digits.size()) - 3; i > 0; i -= 3) {
        digits.insert(static_cast<std::size_t>(i), ",");
    }
    return "£" + digits;
}

std::string join_skills(Rng& rng, const Family& family, std::size_t count) {
    std::string out;
    std::size_t start = static_cast<std::size_t>(rng.below(family.skills.size()));
    for (std::size_t i = 0; i < count; ++i) {
        if (i > 0) {
            out += (i + 1 == count) ? " and " : ", ";
        }
        out += family.skills[(start + i * 3) % family.skills.size()];
    }
    return out;
}

}  // namespace

std::uint64_t Rng::next() noexcept {
    state_ += 0x9E3779B97F4A7C15ULL;
    std::uint64_t z = state_;
    z = (z ^ (z >> 30U)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27U)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31U);
}

double Rng::unit() noexcept {
    return static_cast<double>(next() >> 11U) * (1.0 / 9007199254740992.0);  // 2^53
}

std::vector<JobAd> generate_corpus(const CorpusOptions& options) {
    Rng rng(options.seed);
    std::vector<JobAd> jobs;
    jobs.reserve(options.jobs);
    for (std::size_t i = 0; i < options.jobs; ++i) {
        if (!jobs.empty() && rng.chance(options.repost_rate)) {
            // Agencies often re-post an advert a few days later under a fresh reference.
            JobAd copy = jobs[static_cast<std::size_t>(rng.below(jobs.size()))];
            copy.id = "JB" + std::to_string(100'000 + i);
            copy.posted_day = std::min(
                options.days, copy.posted_day + 1 + static_cast<std::uint32_t>(rng.below(7)));
            copy.company = "Atlas Talent Partners";
            jobs.push_back(std::move(copy));
            continue;
        }
        const auto& family = pick(rng, kFamilies);
        const auto& level = weighted(rng, std::span<const Seniority>(kSeniority));
        const auto& region = weighted(rng, std::span<const Region>(kRegions));
        JobAd job;
        job.id = "JB" + std::to_string(100'000 + i);
        job.title = std::string(level.prefix) + std::string(family.title);
        if (level.prefix == "Head of ") {
            job.title = "Head of " + std::string(family.sector);
            job.title[8] = static_cast<char>(job.title[8] - 'a' + 'A');
        }
        job.company = std::string(pick(rng, kCompanies));
        job.remote = rng.chance(family.remote_share);
        job.location = job.remote && rng.chance(0.35) ? "Remote" : std::string(region.city);
        const double noise = 0.88 + 0.24 * rng.unit();
        const double mid = static_cast<double>(family.base_salary) * level.multiplier *
                           region.salary_factor * noise;
        job.salary_min = round_to(mid * 0.92, 500);
        job.salary_max = round_to(mid * 1.1, 500);
        if (rng.chance(0.03)) {
            job.salary_min = 0;  // "competitive": no salary advertised
            job.salary_max = 0;
        }
        const double c = rng.unit();
        job.contract = c < family.contract_share          ? Contract::Contract
                       : c < family.contract_share + 0.05 ? Contract::Temporary
                                                          : Contract::Permanent;
        job.posted_day = static_cast<std::uint32_t>(rng.below(options.days + 1));
        const auto salary_text = job.salary_max == 0 ? std::string("a competitive salary")
                                                     : pounds(job.salary_min) + " to " +
                                                           pounds(job.salary_max) + " a year";
        job.body = std::string(job.company) + " is hiring a " + job.title + " to join our " +
                   std::string(family.sector) + " team" +
                   (job.location == "Remote" ? std::string(", working from home")
                                             : " in " + job.location) +
                   ". ";
        job.body += "You will bring experience with " + join_skills(rng, family, 3) + ". ";
        if (rng.chance(0.6)) {
            job.body += "Nice to have: " + join_skills(rng, family, 2) + ". ";
        }
        job.body += "We offer " + salary_text + ", " + std::string(pick(rng, kBenefits)) + " and " +
                    std::string(pick(rng, kBenefits)) + ". ";
        if (job.remote) {
            job.body += "This role is fully remote within the UK. ";
        }
        if (job.contract == Contract::Contract) {
            job.body += "Initial 6 month contract, outside IR35, with a view to extend. ";
        } else if (job.contract == Contract::Temporary) {
            job.body += "Temporary cover for 3 months, immediate start. ";
        }
        if (rng.chance(0.15)) {
            job.body +=
                "Applicants must have the right to work in the UK; we cannot offer sponsorship. ";
        }
        job.body += "Apply with your CV quoting " + job.id + ".";
        jobs.push_back(std::move(job));
    }
    return jobs;
}

}  // namespace jobsearch
