"""Seeded synthetic customer messages for Fenwick Energy, an invented UK energy supplier.

Every message is built from a *phrasing family*: a group of templates that say the same thing
the same way. Two families per category are held out entirely, along with some vulnerability
phrasings. The "unseen" test set is written in phrasings that never appear in training or
pre-training text, which is the honest test of whether a model has learned the task or the
templates.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

from .labels import Triage

# (category, base urgency, templates). The last two families of each category are held out.
FAMILIES: dict[str, list[list[tuple[str, str]]]] = {
    "billing": [
        [
            (
                "My bill for {month} is {amount}, which is way more than usual. Can someone check it?",
                "medium",
            ),
            ("Why has my bill gone up to {amount}? Nothing has changed in the house.", "medium"),
        ],
        [
            (
                "I think I've been charged twice this month, two payments of {amount} left my account.",
                "high",
            ),
            ("Double charged!! {amount} taken twice on {date}. Account {acct}", "high"),
        ],
        [
            ("Could you send me a copy of my last statement please? Account {acct}.", "low"),
            ("I need a PDF of my bills for the last year for my accountant.", "low"),
        ],
        [
            ("The estimate on my bill is wrong, the house was empty for {weeks} weeks.", "medium"),
            ("Bill says I used loads in {month} but we were away. Please recalculate.", "medium"),
        ],
        [
            ("Your invoice has a standing charge I don't recognise, what is it for?", "low"),
            ("What's the extra line on my statement for {amount}? Didn't agree to that.", "medium"),
        ],
        [
            (
                "Statement arrived showing a balance of {amount} owed which can't be right, I pay by direct debit.",
                "medium",
            ),
            (
                "Got a letter saying I owe {amount} but my direct debit has gone out every month.",
                "medium",
            ),
        ],
    ],
    "meter_reading": [
        [
            ("Here is my electricity reading: {reading}. Taken {date}.", "low"),
            ("Meter reading for account {acct} is {reading}", "low"),
        ],
        [
            ("Gas reading {reading}, electric {reading2}. Photo attached.", "low"),
            ("Readings today: gas {reading} elec {reading2}", "low"),
        ],
        [
            ("Your website won't accept my reading of {reading}, it says it's too low.", "medium"),
            (
                "The app keeps rejecting my meter reading {reading}, says it's out of range.",
                "medium",
            ),
        ],
        [
            (
                "Can you stop estimating and use my actual reads? I've sent {reading} twice now.",
                "medium",
            ),
            ("I keep giving you readings and you keep estimating, latest is {reading}.", "medium"),
        ],
        [
            ("Submitting my closing read of {reading} for the flat I've just left.", "low"),
            ("Final reading as I'm moving out is {reading}.", "low"),
        ],
        [
            ("Numbers on my meter display now say {reading}, is that what you need?", "low"),
            (
                "I've copied the digits off the dial, {reading}, hope that helps with the estimate.",
                "low",
            ),
        ],
    ],
    "smart_meter": [
        [
            ("My smart meter's in-home display has gone blank.", "low"),
            ("The little screen that came with the smart meter stopped working.", "low"),
        ],
        [
            ("Smart meter isn't sending readings, I'm getting estimated bills again.", "medium"),
            (
                "Since {month} my smart meter has stopped talking to you, bills are estimates.",
                "medium",
            ),
        ],
        [
            ("I'd like to book a smart meter installation please.", "low"),
            ("Can I get a smart meter fitted? What dates have you got near {town}?", "low"),
        ],
        [
            ("Smart prepay meter won't take my top up, I've got no credit left.", "high"),
            (
                "Topped up {amount} on the app but it never reached the meter and now the power's off.",
                "high",
            ),
        ],
        [
            ("The engineer didn't turn up for my smart meter appointment on {date}.", "medium"),
            ("Waited in all day {date} for the smart install and nobody came.", "medium"),
        ],
        [
            ("The smart display shows red all the time even with everything switched off.", "low"),
            (
                "Since the new meter went in the readout flashes a warning symbol, what does it mean?",
                "medium",
            ),
        ],
    ],
    "payment_support": [
        [
            ("I'm struggling to pay my bill of {amount}, can I set up a payment plan?", "medium"),
            ("Can I spread the {amount} I owe over a few months? Money is tight.", "medium"),
        ],
        [
            ("I can't afford to top up and the meter is about to run out.", "high"),
            ("I've had to self-disconnect, I can't afford to top up the prepayment meter.", "high"),
        ],
        [
            ("Can I change my direct debit date to after payday on the {day}th?", "low"),
            ("Please move my payment date, my wages come in later now.", "low"),
        ],
        [
            (
                "Are there any grants or support schemes for people behind on energy bills?",
                "medium",
            ),
            ("Is there help available? I'm {amount} in arrears and getting letters.", "medium"),
        ],
        [
            ("I got a debt collection letter about {amount}, I didn't know I was behind.", "high"),
            ("Received a letter from debt collectors for {amount}. Please call me.", "high"),
        ],
        [
            (
                "We're behind on the account and every reminder makes it worse, what are my options?",
                "medium",
            ),
            ("Arrears of {amount} and I can't see a way out, who can I talk to?", "high"),
        ],
    ],
    "switching": [
        [
            ("I want to switch to you from {supplier}, how long does it take?", "low"),
            ("Thinking of moving over from {supplier}. What's the process?", "low"),
        ],
        [
            ("My switch has been stuck for {weeks} weeks, what's going on?", "medium"),
            ("Switch from {supplier} still hasn't happened after {weeks} weeks.", "medium"),
        ],
        [
            ("I didn't agree to switch to you, I think this is an erroneous transfer.", "high"),
            ("You've taken over my supply without my permission, I'm with {supplier}.", "high"),
        ],
        [
            ("I'm leaving, can you confirm my final bill will be sent?", "low"),
            ("Switching away to {supplier}. Please send the closing bill.", "low"),
        ],
        [
            ("Will I have to pay an exit fee if I move to {supplier} now?", "low"),
            ("Is there a charge for leaving my fixed deal early?", "low"),
        ],
        [
            (
                "I signed up online last month but I'm still getting letters from {supplier}, have you taken over yet?",
                "medium",
            ),
            (
                "Has my move across to you gone through? {supplier} say they are still my supplier.",
                "medium",
            ),
        ],
    ],
    "supply_fault": [
        [
            ("We have no electricity at all, the whole street is dark.", "high"),
            ("Power cut on our road in {town} since this morning.", "high"),
        ],
        [
            ("No gas since yesterday, the boiler won't light.", "high"),
            ("Gas supply has stopped, no heating or hot water.", "high"),
        ],
        [
            ("The lights keep flickering and the fuse box trips.", "medium"),
            ("Our electrics keep tripping, is it a supply problem?", "medium"),
        ],
        [
            ("There's a smell of gas near the meter.", "high"),
            ("I can smell gas outside by the meter box, what should I do?", "high"),
        ],
        [
            ("The meter cupboard door is broken and the meter is exposed.", "low"),
            ("Meter box cover has come off in the wind.", "low"),
        ],
        [
            ("Everything went off at about {time} and the neighbours are off too.", "high"),
            ("Nothing in the house has power and the street lamps are out.", "high"),
        ],
    ],
    "tariff": [
        [
            ("What tariff am I on and when does it end?", "low"),
            ("Can you tell me my current tariff and the unit rates?", "low"),
        ],
        [
            ("My fixed deal ends in {month}, what are my options?", "low"),
            ("Fix is ending soon, can I renew on a new fixed tariff?", "low"),
        ],
        [
            ("Do you have an EV tariff with cheap overnight rates?", "low"),
            ("I've got an electric car now, which tariff is best?", "low"),
        ],
        [
            ("Your price rise is outrageous, I want to be on the cheapest deal.", "medium"),
            ("Prices have gone up again, put me on something cheaper.", "medium"),
        ],
        [
            ("Can I get an export payment for my solar panels?", "low"),
            ("I've installed solar, how do I get paid for what I export?", "low"),
        ],
        [
            ("Is a variable rate or a fixed one cheaper for a small flat like mine?", "low"),
            (
                "Which of your deals works out cheapest if I mostly use power in the evenings?",
                "low",
            ),
        ],
    ],
    "moving_home": [
        [
            ("I'm moving house on {date}, how do I take my account with me?", "low"),
            ("Moving to {town} on {date}. Can I keep my account?", "low"),
        ],
        [
            ("I've just moved in and the account is in the old tenant's name.", "low"),
            ("New tenant here, please set up an account for this address.", "low"),
        ],
        [
            ("Moved in today and there's no power at the property.", "high"),
            ("Just got the keys and the prepayment meter has no credit, no electricity.", "high"),
        ],
        [
            ("The previous owner left a debt of {amount} on the meter.", "medium"),
            ("There's {amount} of someone else's debt on my new meter.", "medium"),
        ],
        [
            ("Please close my account, I'm moving abroad on {date}.", "low"),
            ("Leaving the UK on {date}, close my account and send the final bill.", "low"),
        ],
        [
            ("We complete on the new place on {date}, what do I need to tell you and when?", "low"),
            ("Selling up next month, how do I hand the energy over to the buyers?", "low"),
        ],
    ],
}

HELD_OUT_FAMILIES = 2

# Vulnerability: (phrase, raises urgency for supply and payment problems). The last third are held out.
VULNERABILITY = [
    "My mum is 87 and lives with me.",
    "I'm on oxygen at home and need the power.",
    "I have a baby of six weeks.",
    "I'm disabled and housebound.",
    "My husband has dementia.",
    "I'm a full-time carer for my son.",
    "I'm pregnant and on my own.",
    "I'm registered blind.",
    "My dad uses a stairlift and a hospital bed.",
    "I'm recovering from chemotherapy.",
    "We rely on a home dialysis machine.",
    "I've just lost my job and I'm on my own with three kids.",
]
HELD_OUT_VULNERABILITY = 4

HIGH_SIGNALS = ["URGENT.", "Please help today.", "It's freezing in here.", "The kids are cold."]
LOW_SIGNALS = ["No rush.", "Whenever you get a chance.", "Not urgent."]
GREETINGS = ["", "", "Hi,", "Hello,", "Dear Fenwick Energy,", "hi there", "Good morning,"]
SIGN_OFFS = ["", "", "Thanks", "Thank you.", "Cheers", "Regards, {name}", "{name}"]
NAMES = ["Asha", "Tom", "Priya", "Gareth", "Siobhan", "Mo", "Ewa", "Kwame", "Rhian", "Dev"]
TOWNS = ["Harrowgate Vale", "Mersey Lock", "Ashby Fen", "Kettering Moor", "Saltmarsh", "Ellesby"]
SUPPLIERS = ["Northlight Power", "Brightwater Energy", "Pennine Gas & Light", "Kestrel Utilities"]
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

URGENCY_RANK = {"low": 0, "medium": 1, "high": 2}
RANKED = ["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    text: str
    category: str
    urgency: str
    vulnerable: str
    family: str
    split: str

    @property
    def triage(self) -> Triage:
        return Triage(self.category, self.urgency, self.vulnerable)


def _fill(template: str, rng: random.Random) -> str:
    values = {
        "amount": f"£{rng.choice([38, 64, 92, 117, 148, 213, 286, 412, 640, 1180])}.{rng.randint(0, 99):02d}",
        "acct": f"FE-{rng.randint(10_000_000, 99_999_999)}",
        "date": f"{rng.randint(1, 28)} {rng.choice(MONTHS)}",
        "month": rng.choice(MONTHS),
        "reading": f"{rng.randint(1000, 99999):05d}",
        "reading2": f"{rng.randint(1000, 99999):05d}",
        "weeks": str(rng.randint(2, 9)),
        "town": rng.choice(TOWNS),
        "supplier": rng.choice(SUPPLIERS),
        "day": str(rng.randint(1, 28)),
        "time": f"{rng.randint(1, 11)}{rng.choice(['am', 'pm'])}",
        "name": rng.choice(NAMES),
    }
    return template.format(**values)


def _typos(text: str, rng: random.Random, rate: float) -> str:
    words = text.split(" ")
    for i, word in enumerate(words):
        if len(word) > 3 and rng.random() < rate:
            j = rng.randrange(len(word) - 1)
            words[i] = word[:j] + word[j + 1] + word[j] + word[j + 2 :]
    return " ".join(words)


def _style(text: str, rng: random.Random) -> str:
    roll = rng.random()
    if roll < 0.15:
        text = text.lower()
    elif roll < 0.2:
        text = text.replace(".", "").replace(",", "")
    return text


def _message(
    rng: random.Random,
    category: str,
    family_index: int,
    split: str,
    index: int,
    held_out: bool | None,
) -> Message:
    family = FAMILIES[category][family_index]
    template, base = rng.choice(family)
    urgency = base
    pieces = [_fill(template, rng)]

    vulnerable = rng.random() < 0.18
    if vulnerable:
        if held_out is None:  # unlabelled traffic: any phrasing at all
            pool = VULNERABILITY
        elif held_out:
            pool = VULNERABILITY[-HELD_OUT_VULNERABILITY:]
        else:
            pool = VULNERABILITY[:-HELD_OUT_VULNERABILITY]
        phrase = rng.choice(pool)
        pieces.insert(rng.choice([0, len(pieces)]), phrase)
        if (
            category in {"supply_fault", "payment_support", "moving_home", "smart_meter"}
            and base != "low"
        ):
            urgency = "high"
        elif urgency == "low":
            urgency = "medium"

    signal = rng.random()
    if signal < 0.1:
        pieces.append(rng.choice(HIGH_SIGNALS))
        urgency = RANKED[min(2, URGENCY_RANK[urgency] + 1)]
    elif signal < 0.18 and urgency != "high":
        pieces.append(rng.choice(LOW_SIGNALS))
        urgency = RANKED[max(0, URGENCY_RANK[urgency] - 1)]

    greeting = rng.choice(GREETINGS)
    sign_off = _fill(rng.choice(SIGN_OFFS), rng)
    text = " ".join(p for p in [greeting, *pieces, sign_off] if p)
    text = _typos(_style(text, rng), rng, rate=0.03)
    return Message(
        id=f"{split}-{index:05d}",
        text=text,
        category=category,
        urgency=urgency,
        vulnerable="yes" if vulnerable else "no",
        family=f"{category}/{family_index}",
        split=split,
    )


# "unlabelled" is customer traffic with no labels: every phrasing, including the held-out ones, as a
# live inbox would contain. It is only ever used for language-model pre-training.
SPLIT_SIZES = {
    "train": 9000,
    "val": 1200,
    "test_seen": 1500,
    "test_unseen": 1500,
    "unlabelled": 6000,
}


def generate(
    seed: int = 7, sizes: dict[str, int] | None = None, label_noise: float = 0.02
) -> list[Message]:
    """Builds every split. Training labels get a little noise, as real annotation does; test labels do not."""
    sizes = sizes or SPLIT_SIZES
    rng = random.Random(seed)
    messages: list[Message] = []
    categories = list(FAMILIES)
    for split, size in sizes.items():
        held_out: bool | None = None if split == "unlabelled" else split == "test_unseen"
        for i in range(size):
            category = (
                categories[i % len(categories)] if rng.random() < 0.5 else rng.choice(categories)
            )
            families = len(FAMILIES[category])
            if held_out is None:
                choices = range(families)
            elif held_out:
                choices = range(families - HELD_OUT_FAMILIES, families)
            else:
                choices = range(families - HELD_OUT_FAMILIES)
            message = _message(rng, category, rng.choice(list(choices)), split, i, held_out)
            if split == "train" and rng.random() < label_noise:
                message = Message(**{**asdict(message), "urgency": rng.choice(RANKED)})
            messages.append(message)
    return messages


def by_split(messages: list[Message]) -> dict[str, list[Message]]:
    out: dict[str, list[Message]] = {}
    for m in messages:
        out.setdefault(m.split, []).append(m)
    return out


def write_jsonl(messages: list[Message], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for m in messages:
            f.write(json.dumps(asdict(m), ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> Iterator[Message]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            yield Message(**json.loads(line))
