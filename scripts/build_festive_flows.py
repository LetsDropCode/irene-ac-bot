"""Generate reviewable Meta Flow assets locally. Never calls Meta or publishes."""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "flows" / "assets"
TEXT_FIELDS = {
    "title": ("Run title", 80),
    "meeting_point": ("Meeting point", 120),
    "location_description": ("Meeting instructions", 300),
    "start_time": ("Start time (HH:MM)", 5),
    "distances": ("Distances: 5km, 10km", 80),
    "route_description": ("Route descriptions", 600),
    "maps_url": ("Maps HTTPS link", 500),
    "route_url": ("Route HTTPS link", 500),
    "pace_information": ("Pace / group info", 160),
    "safety_notes": ("Safety / parking notes", 500),
}


def prop(kind="string", example=""):
    return {"type": kind, "__example__": example}


def options(values):
    return [{"id": k, "title": v} for k, v in values]


def select(name, label, values, required=True, initial=None):
    c = {
        "type": "Dropdown",
        "name": name,
        "label": label,
        "required": required,
        "data-source": values,
    }
    if initial is not None:
        c["init-value"] = initial
    return c


def screen(name, children, fields, extra=None, terminal=False, label="Continue"):
    schema = {
        "revision": prop(example="0"),
        "error": prop(),
        "summary": prop(example="Irene AC Festive Run Adventures"),
    }
    schema.update(extra or {})
    footer = {
        "type": "Footer",
        "label": label,
        "on-click-action": {
            "name": "complete" if terminal else "data_exchange",
            "payload": {}
            if terminal
            else {
                "revision": "${data.revision}",
                **{k: "${form." + k + "}" for k in fields},
            },
        },
    }
    return {
        "id": name,
        "title": "Irene AC Festive Runs",
        "terminal": terminal,
        "refresh_on_back": True,
        "data": schema,
        "layout": {
            "type": "SingleColumnLayout",
            "children": [
                {"type": "TextBody", "text": "${data.error}"},
                {"type": "TextBody", "text": "${data.summary}"},
                *children,
                footer,
            ],
        },
    }


OPTIONS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "title": {"type": "string"}},
    },
    "__example__": [{"id": "2026-12-13", "title": "Sun 13 Dec 2026"}],
}


def build(kind):
    choose_fields = ["choice"]
    choose = [select("choice", "Choose a date", "${data.options}")]
    choose_schema = {"options": OPTIONS_SCHEMA}
    if kind == "HOST":
        choose += [
            select(
                "role",
                "Hosting role",
                options([("LEAD", "Lead host"), ("COHOST", "Co-host")]),
                initial="${data.role}",
            ),
            {
                "type": "OptIn",
                "name": "reminders",
                "label": "Remind me to finalise details",
                "init-value": "${data.reminders}",
            },
        ]
        choose_fields += ["role", "reminders"]
        choose_schema.update(
            role=prop(example="LEAD"), reminders=prop("boolean", False)
        )
    screens = [screen("CHOOSE", choose, choose_fields, choose_schema)]
    confirm = [
        {
            "type": "OptIn",
            "name": "confirm",
            "label": "I confirm these details",
            "required": True,
        }
    ]
    if kind == "HOST":
        screens.append(screen("BOOK", confirm, ["confirm"], label="Save registration"))
    if kind == "MANAGE":
        screens.append(
            screen(
                "ACTION",
                [select("choice", "Manage selection", "${data.options}")],
                ["choice"],
                {"options": OPTIONS_SCHEMA, "replacement": prop()},
            )
        )
    if kind in {"HOST", "MANAGE"}:
        inputs = [
            {
                "type": "TextInput" if maximum <= 160 else "TextArea",
                "name": key,
                "label": label,
                "required": False,
                "init-value": "${data." + key + "}",
            }
            for key, (label, maximum) in TEXT_FIELDS.items()
        ]
        inputs += [
            select(
                "walkers_welcome",
                "Walking friendly?",
                options([("yes", "Yes"), ("no", "No")]),
                initial="${data.walkers_welcome}",
            ),
            select(
                "coffee_arrangements",
                "Coffee / breakfast?",
                options([("yes", "Yes"), ("no", "No"), ("TBC", "To be confirmed")]),
                initial="${data.coffee_arrangements}",
            ),
            select(
                "save_mode",
                "Save details",
                options(
                    [
                        ("draft", "Save unfinished draft"),
                        ("submit", "Submit for approval"),
                    ]
                ),
                initial="${data.save_mode}",
            ),
        ]
        names = list(TEXT_FIELDS) + [
            "walkers_welcome",
            "coffee_arrangements",
            "save_mode",
        ]
        schema = {
            k: prop(
                example="draft"
                if k == "save_mode"
                else "no"
                if k == "walkers_welcome"
                else "TBC"
                if k == "coffee_arrangements"
                else ""
            )
            for k in names
        }
        screens.append(screen("DETAILS", inputs, names, schema, label="Review details"))
    if kind in {"JOIN", "MANAGE"}:
        screens.append(
            screen(
                "RSVP",
                [
                    select("distance", "Choose your distance", "${data.options}"),
                    {
                        "type": "OptIn",
                        "name": "reminders",
                        "label": "Run reminders and change alerts",
                        "init-value": "${data.reminders}",
                    },
                ],
                ["distance", "reminders"],
                {
                    "options": OPTIONS_SCHEMA,
                    "distance": prop(),
                    "reminders": prop("boolean", False),
                },
                label="Review RSVP",
            )
        )
    screens += [
        screen("REVIEW", confirm, ["confirm"], label="Confirm and save"),
        screen("DONE", [], [], terminal=True, label="Close"),
    ]
    routes = {
        "HOST": {
            "CHOOSE": ["BOOK"],
            "BOOK": ["DETAILS", "DONE"],
            "DETAILS": ["REVIEW"],
            "REVIEW": ["DONE"],
            "DONE": [],
        },
        "JOIN": {
            "CHOOSE": ["RSVP"],
            "RSVP": ["REVIEW"],
            "REVIEW": ["DONE"],
            "DONE": [],
        },
        "MANAGE": {
            "CHOOSE": ["ACTION"],
            "ACTION": ["DETAILS", "RSVP", "REVIEW"],
            "DETAILS": ["REVIEW"],
            "RSVP": ["REVIEW"],
            "REVIEW": ["DONE"],
            "DONE": [],
        },
    }[kind]
    return {
        "version": "7.3",
        "data_api_version": "4.0",
        "routing_model": routes,
        "screens": screens,
    }


if __name__ == "__main__":
    for kind in ("HOST", "JOIN", "MANAGE"):
        (OUT / f"festive_{kind.lower()}.json").write_text(
            json.dumps(build(kind), indent=2) + "\n"
        )
