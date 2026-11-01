"""Synthetic, labelled dataset for service categorisation.

Every example comes from a TEMPLATE filled with a few different values. All
paraphrases of one template share a `group` id. Splits are made by group, so the
model is never tested on a near-copy of a sentence it saw in training (leakage).

The data is synthetic: good scores here do NOT prove real-world accuracy.

    python -m app.services.ml.dataset      # regenerate data/ml/service_requests.jsonl
"""
import hashlib
import itertools
import json
import random
from pathlib import Path

from ...config import BACKEND_DIR

DATA_PATH = BACKEND_DIR / "data" / "ml" / "service_requests.jsonl"
LABELS = ["plumbing", "electrical", "appliance"]

# (template, {slot: [values]}) — each template yields up to 4 paraphrases.
TEMPLATES: dict[str, list[tuple[str, dict[str, list[str]]]]] = {
    "plumbing": [
        ("My {room} tap is leaking{tail}", {"room": ["kitchen", "bathroom", "wash basin", "balcony"],
                                           "tail": ["", " constantly", " all night", " drop by drop"]}),
        ("Water is dripping from the {thing}", {"thing": ["pipe under the sink", "ceiling of the bathroom",
                                                          "joint near the meter", "overhead tank pipe"]}),
        ("The {drain} is blocked and water is not draining", {"drain": ["kitchen sink", "bathroom drain",
                                                                        "shower drain", "wash basin"]}),
        ("Toilet {issue}", {"issue": ["flush is not working", "keeps running after flushing",
                                      "is overflowing", "cistern is leaking"]}),
        ("Need a plumber to {job}", {"job": ["fix a leaking pipe", "replace the kitchen faucet",
                                             "install a new wash basin", "repair the shower mixer"]}),
        ("Very low water pressure in the {room}", {"room": ["bathroom", "kitchen", "whole flat", "shower"]}),
        ("There is a foul smell coming from the {drain}", {"drain": ["bathroom drain", "kitchen sink",
                                                                     "floor trap", "balcony outlet"]}),
        ("{pipe} pipe burst {where}", {"pipe": ["PVC", "Water", "The inlet", "Old GI"],
                                       "where": ["in the bathroom", "near the tank", "under the sink", "outside"]}),
        ("Water tank overflow {issue}", {"issue": ["valve is broken", "keeps spilling",
                                                   "float valve stuck", "pipe cracked"]}),
        ("Seepage on the wall behind the {room} because of a hidden leak", {
            "room": ["bathroom", "kitchen", "washing area", "toilet"]}),
        ("Shower {issue}", {"issue": ["head is leaking", "gives only a trickle", "mixer is stuck", "diverter broken"]}),
        ("Please fix the {part} in my bathroom", {"part": ["leaking health faucet", "broken angle valve",
                                                           "loose commode", "cracked waste pipe"]}),
        ("Sink is {issue}", {"issue": ["clogged with food", "draining very slowly", "backing up", "gurgling"]}),
        ("water pump {issue} for the overhead tank", {"issue": ["not lifting water", "running dry",
                                                                "making noise and no water", "leaking at the joint"]}),
        ("leakage from {thing} needs urgent repair", {"thing": ["the main water line", "the bathroom pipe",
                                                                "the kitchen tap", "the flush tank"]}),
        ("Install a {item}", {"item": ["new kitchen sink", "water filter tap", "washbasin pedestal", "bib cock"]}),
        ("{room} floor is flooded because the pipe is leaking", {"room": ["Bathroom", "Kitchen", "Utility", "Balcony"]}),
        ("Hot and cold water mixer {issue}", {"issue": ["leaking", "jammed", "dripping", "loose"]}),
        ("drainage line {issue}", {"issue": ["choked", "overflowing in the society duct", "blocked badly", "smelly"]}),
        ("Need help with a {thing} that wont stop dripping", {"thing": ["tap", "faucet", "valve", "pipe joint"]}),
    ],
    "electrical": [
        ("The {room} switch board is sparking", {"room": ["bedroom", "kitchen", "hall", "study"]}),
        ("{n} sockets stopped working{tail}", {"n": ["Two", "All the", "Some", "The bedroom"],
                                               "tail": ["", " suddenly", " after rain", " since morning"]}),
        ("MCB keeps tripping {when}", {"when": ["again and again", "when I switch on the AC", "every evening",
                                                "at night"]}),
        ("Ceiling fan {issue}", {"issue": ["is not running", "is very slow", "makes humming noise",
                                           "regulator is broken"]}),
        ("Need an electrician to {job}", {"job": ["install a new light fitting", "fix a faulty switch",
                                                  "add a new plug point", "change the wiring in one room"]}),
        ("Lights {issue}", {"issue": ["keep flickering", "go off randomly", "are dim", "fuse frequently"]}),
        ("Burning smell from the {thing}", {"thing": ["switchboard", "main panel", "plug socket",
                                                      "wiring in the wall"]}),
        ("No power in {where}", {"where": ["one room", "half the house", "the kitchen sockets", "the bedroom"]}),
        ("Getting a mild shock from the {thing}", {"thing": ["switch", "metal door handle", "socket", "fan regulator"]}),
        ("Install {item}", {"item": ["a ceiling fan", "LED panel lights", "an exhaust fan", "a doorbell"]}),
        ("{part} is loose and wires are hanging", {"part": ["Switch plate", "Light holder", "Socket", "Junction box"]}),
        ("Inverter wiring {issue}", {"issue": ["is faulty", "does not charge", "trips the main", "needs to be redone"]}),
        ("Tube light {issue}", {"issue": ["not starting", "choke burnt", "blinking", "holder broken"]}),
        ("electric meter {issue}", {"issue": ["wire is heating", "connection loose", "shows sparks", "is buzzing"]}),
        ("Short circuit in the {room}", {"room": ["kitchen", "bedroom", "hall", "bathroom"]}),
        ("Earthing problem {detail}", {"detail": ["at home", "in the kitchen sockets", "tester glows", "needs checking"]}),
        ("Power fluctuates and {thing} voltage drops", {"thing": ["the", "bedroom", "kitchen", "whole flat"]}),
        ("Need wiring for a new {thing}", {"thing": ["AC point", "geyser point", "TV unit", "study lamp"]}),
        ("{part} switch is broken", {"part": ["Bedroom fan", "Hall light", "Kitchen", "Bathroom"]}),
        ("Plug point {issue}", {"issue": ["melted", "loose", "is not giving power", "smoked once"]}),
    ],
    "appliance": [
        ("Washing machine {issue}", {"issue": ["is not spinning", "does not drain", "shows an error code",
                                               "makes a loud noise"]}),
        ("Refrigerator {issue}", {"issue": ["is not cooling", "freezer has too much ice", "is making noise",
                                           "light is on but no cooling"]}),
        ("Microwave {issue}", {"issue": ["is not heating", "turntable stopped", "sparks inside",
                                         "display is dead"]}),
        ("Need {what} for my {appliance}", {"what": ["servicing", "a repair", "a check-up", "a technician"],
                                           "appliance": ["washing machine", "fridge", "microwave oven", "dishwasher"]}),
        ("Geyser {issue}", {"issue": ["is not heating water", "thermostat seems faulty", "takes too long",
                                      "heating element failed"]}),
        ("RO water purifier {issue}", {"issue": ["is leaking", "is not giving water", "filter needs change",
                                                 "is making noise"]}),
        ("Mixer grinder {issue}", {"issue": ["is not starting", "jar is stuck", "smells burnt", "is very noisy"]}),
        ("Dishwasher {issue}", {"issue": ["is not cleaning", "will not drain", "shows error", "leaks at the door"]}),
        ("{brand} front load machine {issue}", {"brand": ["My", "The", "Our", "Old"],
                                                "issue": ["drum is not rotating", "door is locked", "stops midway",
                                                          "is vibrating badly"]}),
        ("Fridge {issue}", {"issue": ["door gasket broken", "water dripping inside", "compressor not starting",
                                      "keeps tripping"]}),
        ("Chimney {issue}", {"issue": ["suction is weak", "needs deep cleaning", "motor not working",
                                       "makes noise"]}),
        ("Air fryer {issue}", {"issue": ["is not heating", "timer is broken", "fan stopped", "won't turn on"]}),
        ("Oven {issue}", {"issue": ["temperature is wrong", "does not heat evenly", "door hinge broken",
                                    "fan not working"]}),
        ("Water dispenser {issue}", {"issue": ["is not cooling", "is leaking", "tap is broken", "makes noise"]}),
        ("Induction cooktop {issue}", {"issue": ["shows E1 error", "is not heating", "turns off by itself",
                                                 "buttons not responding"]}),
        ("Top load washer {issue}", {"issue": ["not filling water", "spin is weak", "lid lock fault",
                                               "timer stuck"]}),
        ("Annual maintenance for my {appliance}", {"appliance": ["refrigerator", "washing machine", "RO purifier",
                                                                 "kitchen chimney"]}),
        ("Double door fridge {issue}", {"issue": ["frost build-up", "bottom section warm", "beeping",
                                                  "fan noise"]}),
        ("Electric kettle and toaster {issue}", {"issue": ["both stopped", "need repair", "not heating", "dead"]}),
        ("The vacuum cleaner {issue}", {"issue": ["has no suction", "will not charge", "is overheating",
                                                  "brush stopped"]}),
    ],
}

# Dataset v2 additions. v1 (20 templates per category) generalised poorly to held-out
# templates because each template had its own vocabulary. These templates reuse the
# everyday words customers actually repeat ("plumber", "leak", "electrician", "socket",
# "repair my fridge") in new sentence shapes. See docs/learning-guide.md, Milestone 3.
EXTRA_TEMPLATES: dict[str, list[tuple[str, dict[str, list[str]]]]] = {
    "plumbing": [
        ("Can a plumber come {when} to look at a {thing}", {"when": ["today", "this week", "soon", "urgently"],
                                                            "thing": ["leak", "blocked drain", "broken tap", "pipe"]}),
        ("I have a water leak {where}", {"where": ["in the bathroom", "under the kitchen sink", "near the toilet",
                                                   "from the ceiling"]}),
        ("Pipe {issue} in my flat", {"issue": ["leaking", "cracked", "broken", "making a knocking noise"]}),
        ("{who} needed for bathroom fittings", {"who": ["Plumber", "A plumber", "Plumbing help", "Someone"]}),
        ("my {thing} is leaking water everywhere", {"thing": ["tap", "pipe", "flush tank", "basin"]}),
        ("Drain {issue} and water is collecting", {"issue": ["clogged", "jammed", "choked", "slow"]}),
        ("Tap {issue}", {"issue": ["not closing fully", "handle broken", "spraying water", "leaking from base"]}),
        ("Fix the leaking {thing} please", {"thing": ["pipe", "tap", "flush", "valve"]}),
        ("Bathroom {issue}", {"issue": ["leak", "drain blocked", "tap dripping", "pipe burst"]}),
        ("Kitchen sink {issue}", {"issue": ["pipe leaking", "tap broken", "drain blocked", "water not going down"]}),
        ("Water not coming in the {where} tap", {"where": ["kitchen", "bathroom", "balcony", "basin"]}),
        ("Plumbing work {job}", {"job": ["for a new bathroom", "to fix leaks", "for pipe replacement",
                                         "for a blocked toilet"]}),
    ],
    "electrical": [
        ("Can an electrician come {when} to check the {thing}", {"when": ["today", "this week", "soon", "urgently"],
                                                                 "thing": ["wiring", "switches", "MCB", "sockets"]}),
        ("I have an electrical problem {where}", {"where": ["in the bedroom", "in the kitchen", "with the lights",
                                                            "in the main board"]}),
        ("Wiring {issue} in my flat", {"issue": ["is faulty", "burnt", "is loose", "needs repair"]}),
        ("{who} needed for switch and socket work", {"who": ["Electrician", "An electrician", "Electrical help",
                                                             "Someone"]}),
        ("my {thing} is sparking", {"thing": ["socket", "switch", "plug", "wire"]}),
        ("Socket {issue}", {"issue": ["not working", "burnt", "sparking", "loose"]}),
        ("Switch {issue}", {"issue": ["not working", "stuck", "sparking", "broken"]}),
        ("Fix the faulty {thing} please", {"thing": ["switch", "socket", "wiring", "light point"]}),
        ("Bedroom {issue}", {"issue": ["light not working", "fan not running", "socket dead", "switch sparking"]}),
        ("Power {issue}", {"issue": ["cut in one room", "keeps tripping", "socket dead", "trips with the iron"]}),
        ("Electric {issue}", {"issue": ["shock from switch", "wire burning", "board sparking", "point not working"]}),
        ("Electrical work {job}", {"job": ["for new lights", "to fix wiring", "for MCB replacement",
                                           "for sockets"]}),
    ],
    "appliance": [
        ("Can a technician come {when} to repair my {thing}", {"when": ["today", "this week", "soon", "urgently"],
                                                               "thing": ["fridge", "washing machine", "microwave",
                                                                         "geyser"]}),
        ("I have a problem with my {thing}", {"thing": ["washing machine", "refrigerator", "microwave",
                                                        "water purifier"]}),
        ("{thing} repair needed", {"thing": ["Fridge", "Washing machine", "Microwave", "Mixer"]}),
        ("{who} needed for appliance repair", {"who": ["Technician", "A technician", "Appliance help", "Someone"]}),
        ("my {thing} stopped working", {"thing": ["fridge", "washing machine", "microwave", "oven"]}),
        ("Machine {issue}", {"issue": ["not spinning", "not draining", "showing error", "stopping midway"]}),
        ("Fridge not {issue}", {"issue": ["cooling", "freezing", "starting", "turning on"]}),
        ("Service my {thing} please", {"thing": ["washing machine", "fridge", "RO purifier", "chimney"]}),
        ("Kitchen appliance {issue}", {"issue": ["microwave dead", "mixer not starting", "oven not heating",
                                                 "chimney weak"]}),
        ("Washing {issue}", {"issue": ["machine drum noisy", "machine leaking water", "machine not starting",
                                       "machine door stuck"]}),
        ("Appliance {issue}", {"issue": ["not turning on", "making noise", "showing error", "needs service"]}),
        ("Repair {thing}", {"thing": ["my fridge", "the washing machine", "the microwave", "the RO purifier"]}),
    ],
}
for _label, _extra in EXTRA_TEMPLATES.items():
    TEMPLATES[_label].extend(_extra)

# Requests that do not belong to any supported category. Used only for validation/test.
OUT_OF_SCOPE = [
    ("I want to book a haircut at home", "o1"), ("Can you deliver groceries tomorrow", "o2"),
    ("Need a car mechanic for my scooter", "o3"), ("Looking for a yoga teacher in Baner", "o4"),
    ("My laptop screen is cracked", "o5"), ("Please paint my bedroom walls", "o6"),
    ("I need pest control for cockroaches", "o7"), ("Book a cab to the airport", "o8"),
    ("Need a carpenter to fix my wardrobe door", "o9"), ("What is the weather in Pune", "o10"),
    ("Help me with my maths homework", "o11"), ("I want to order a pizza", "o12"),
    ("Clean my sofa and carpets", "o13"), ("Need a tutor for my child", "o14"),
    ("Mobile phone battery drains fast", "o15"), ("Wifi router is slow", "o16"),
]

# Plausibly more than one category. Any listed label counts as acceptable; asking is also fine.
AMBIGUOUS = [
    ("Water is leaking from my washing machine pipe", ["appliance", "plumbing"], "a1"),
    ("Geyser is not working", ["appliance", "electrical"], "a2"),
    ("Something is wrong in the kitchen", ["plumbing", "electrical", "appliance"], "a3"),
    ("Water heater trips the switch", ["electrical", "appliance"], "a4"),
    ("The RO pipe is leaking under the sink", ["appliance", "plumbing"], "a5"),
    ("Fridge plug socket is sparking", ["electrical", "appliance"], "a6"),
    ("Need a repair at home", ["plumbing", "electrical", "appliance"], "a7"),
    ("Exhaust fan not working in bathroom", ["electrical", "appliance"], "a8"),
    ("Dishwasher drain pipe blocked", ["appliance", "plumbing"], "a9"),
    ("Water pump motor not starting", ["plumbing", "electrical"], "a10"),
]


def generate(seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    rows: list[dict] = []
    for label, templates in TEMPLATES.items():
        for t_idx, (template, slots) in enumerate(templates):
            keys = list(slots)
            combos = list(itertools.product(*(slots[k] for k in keys)))
            rng.shuffle(combos)
            seen = set()
            for combo in combos:
                text = template.format(**dict(zip(keys, combo)))
                if text in seen:
                    continue
                seen.add(text)
                if rng.random() < 0.3:
                    text = text.lower()
                rows.append({"text": text, "label": label, "group": f"{label[:2]}{t_idx:02d}", "kind": "in_scope",
                             "acceptable": [label]})
                if len(seen) == 4:
                    break
    for text, gid in OUT_OF_SCOPE:
        rows.append({"text": text, "label": "out_of_scope", "group": gid, "kind": "out_of_scope", "acceptable": []})
    for text, acceptable, gid in AMBIGUOUS:
        rows.append({"text": text, "label": "ambiguous", "group": gid, "kind": "ambiguous", "acceptable": acceptable})
    return rows


def dataset_version(rows: list[dict]) -> str:
    blob = json.dumps(rows, sort_keys=True).encode()
    return "ds-" + hashlib.sha256(blob).hexdigest()[:10]


def load(path: Path = DATA_PATH) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write(path: Path = DATA_PATH) -> tuple[int, str]:
    rows = generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return len(rows), dataset_version(rows)


if __name__ == "__main__":
    n, v = write()
    counts = {}
    for r in generate():
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    print(f"wrote {n} rows, version {v}, counts {counts}")
