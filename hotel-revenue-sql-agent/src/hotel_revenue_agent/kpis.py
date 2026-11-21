"""Business glossary: the agent's single source of truth for hotel KPI definitions.

Giving the model canonical definitions is the cheapest way to stop the most common
text-to-SQL failure in hospitality: counting cancelled bookings as revenue.
"""

from __future__ import annotations

KPI_GLOSSARY: dict[str, dict[str, str]] = {
    "room_revenue": {
        "definition": "Sum of nightly_rate_gbp * nights for bookings with status = 'completed'.",
        "sql": "SUM(CASE WHEN status = 'completed' THEN nightly_rate_gbp * nights END)",
    },
    "room_nights_sold": {
        "definition": "Sum of nights for completed bookings.",
        "sql": "SUM(CASE WHEN status = 'completed' THEN nights END)",
    },
    "adr": {
        "definition": "Average Daily Rate = room revenue / room nights sold (completed only).",
        "sql": "SUM(nightly_rate_gbp * nights) / SUM(nights) ... WHERE status = 'completed'",
    },
    "occupancy": {
        "definition": "Room nights sold / room nights available. Available = hotels.total_rooms"
        " * days in the period. Attribute nights to the check_in date.",
        "sql": "room_nights_sold / (total_rooms * days_in_period)",
    },
    "revpar": {
        "definition": "Revenue per available room = room revenue / room nights available"
        " (equivalently ADR * occupancy).",
        "sql": "room_revenue / (total_rooms * days_in_period)",
    },
    "cancellation_rate": {
        "definition": "Cancelled bookings / all bookings, by count. Exclude NULL channels when"
        " splitting by channel.",
        "sql": "AVG(status = 'cancelled')",
    },
    "net_room_revenue": {
        "definition": "Room revenue after OTA commission: rate * nights * (1 - commission_pct/100)"
        " for completed bookings.",
        "sql": "SUM(nightly_rate_gbp * nights * (1 - commission_pct / 100.0))",
    },
    "lead_time": {
        "definition": "Days between booked_at and check_in.",
        "sql": "julianday(check_in) - julianday(date(booked_at))",
    },
    "trevpar": {
        "definition": "Total revenue (room + ancillary) per available room night.",
        "sql": "(room_revenue + ancillary_revenue) / room_nights_available",
    },
}

CONVENTIONS = (
    "Dates are ISO-8601 text. A year filter means check_in in that calendar year. "
    "Money is GBP. Revenue metrics count completed stays only unless asked otherwise."
)
