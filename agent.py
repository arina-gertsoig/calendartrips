import json
import os

import anthropic
from dotenv import load_dotenv

from auth import get_calendar_service, get_gmail_service
from tools.calendar import create_calendar_event, list_calendars
from tools.gmail import get_email_content, mark_email_processed, search_travel_emails

load_dotenv()

MODEL = "claude-opus-4-7"

PASSENGERS_FILE = "passengers.json"


def _load_passengers() -> dict:
    if not os.path.exists(PASSENGERS_FILE):
        return {}
    with open(PASSENGERS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _build_passengers_block(passengers: dict) -> str:
    if not passengers:
        return ""
    lines = ["## Passenger Email Mapping\n"]
    for name, email in passengers.items():
        lines.append(f"- {name}: {email}")
    return "\n".join(lines) + "\n"


SYSTEM_PROMPT_TEMPLATE = """You are a travel assistant that extracts travel information from emails and creates Google Calendar events.

{passengers_block}
## Workflow

1. `search_travel_emails` — find unprocessed travel confirmation emails
2. `get_email_content` — read each email fully (body + PDF attachments)
3. Extract ALL travel segments:
   - **Flights**: one event per leg — outbound and return are always separate events
   - **Hotels**: one event for the entire stay (check-in to check-out)
   - **Trains/buses**: one event per leg
4. `list_calendars` — pick the right calendar (use primary if unsure)
5. `create_calendar_event` for each segment with:
   - `summary`: e.g. "✈️ Kyiv → Warsaw (LOT LO782)" or "🏨 Hotel Marriott Warsaw"
   - `start_datetime` / `end_datetime`: ISO 8601 with offset, e.g. "2024-06-15T10:30:00+03:00"
   - `description`: booking reference, seat, confirmation number, etc.
   - `location`: departure airport/station or hotel address
   - `attendee_email`: from the Passenger Email Mapping above — match by full name. If the passenger is not in the list, omit this field entirely.
   - `start_timezone`: IANA timezone of the departure city, e.g. "Europe/Kyiv"
   - `end_timezone`: IANA timezone of the arrival city, e.g. "Europe/Warsaw"
6. `mark_email_processed` after all events for an email are created

## Rules

- **Never use the booking account's email for a different person.** Only use the Passenger Email Mapping.
- **Flight details are often in PDF attachments** — always check the PDF section of the email body.
- **Create a separate event for every flight leg** — never merge outbound + return.
- If you cannot determine the exact time, make a reasonable estimate and note it in the description.
- If an email has no travel info (marketing, price alert, review request, receipt without travel details), skip it and do NOT mark it processed.
- Report at the end: how many emails processed and how many events created."""


TOOLS = [
    {
        "name": "search_travel_emails",
        "description": "Search Gmail for unprocessed travel confirmation emails (flights, trains, buses, hotels). Returns a list of email metadata.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "How many days back to search. Default is 30.",
                    "default": 30,
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_email_content",
        "description": "Fetch the full content of an email by ID: subject, from, to, date, body text, and any PDF attachments.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "The Gmail message ID returned by search_travel_emails.",
                }
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "list_calendars",
        "description": "List all Google Calendars available in the account.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "create_calendar_event",
        "description": "Create a Google Calendar event for a travel segment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Event title, e.g. '✈️ Kyiv → Warsaw (LOT LO782)'",
                },
                "start_datetime": {
                    "type": "string",
                    "description": "Start date/time in ISO 8601 format, e.g. '2024-06-15T10:30:00+03:00'",
                },
                "end_datetime": {
                    "type": "string",
                    "description": "End date/time in ISO 8601 format, e.g. '2024-06-15T12:00:00+02:00'",
                },
                "description": {
                    "type": "string",
                    "description": "Booking reference, seat, confirmation number, etc.",
                },
                "location": {
                    "type": "string",
                    "description": "Departure airport/station or hotel address.",
                },
                "attendee_email": {
                    "type": "string",
                    "description": "Email of the passenger from the Passenger Email Mapping. Omit if not found.",
                },
                "start_timezone": {
                    "type": "string",
                    "description": "IANA timezone of the departure location, e.g. 'Europe/Kyiv'.",
                },
                "end_timezone": {
                    "type": "string",
                    "description": "IANA timezone of the arrival location, e.g. 'Europe/Warsaw'.",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Google Calendar ID. Use 'primary' for the main calendar.",
                    "default": "primary",
                },
            },
            "required": ["summary", "start_datetime", "end_datetime"],
        },
    },
    {
        "name": "mark_email_processed",
        "description": "Add the 'travel-processed' label to an email so it won't be picked up again.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "The Gmail message ID to mark as processed.",
                }
            },
            "required": ["message_id"],
        },
    },
]


def execute_tool(name: str, inputs: dict, gmail_service, calendar_service):
    if name == "search_travel_emails":
        return search_travel_emails(gmail_service, days_back=inputs.get("days_back", 30))
    if name == "get_email_content":
        return get_email_content(gmail_service, inputs["message_id"])
    if name == "list_calendars":
        return list_calendars(calendar_service)
    if name == "create_calendar_event":
        return create_calendar_event(
            calendar_service,
            summary=inputs["summary"],
            start_datetime=inputs["start_datetime"],
            end_datetime=inputs["end_datetime"],
            description=inputs.get("description", ""),
            location=inputs.get("location", ""),
            attendee_email=inputs.get("attendee_email", ""),
            start_timezone=inputs.get("start_timezone", "UTC"),
            end_timezone=inputs.get("end_timezone", inputs.get("start_timezone", "UTC")),
            calendar_id=inputs.get("calendar_id", "primary"),
        )
    if name == "mark_email_processed":
        return mark_email_processed(gmail_service, inputs["message_id"])
    raise ValueError(f"Unknown tool: {name}")


def run_agent(days_back: int = 30):
    print(f"Starting travel agent (searching last {days_back} days)...")

    passengers = _load_passengers()
    if passengers:
        print(f"Loaded {len(passengers)} passengers from {PASSENGERS_FILE}")
    else:
        print(f"Warning: {PASSENGERS_FILE} not found or empty — attendee emails will be skipped")

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        passengers_block=_build_passengers_block(passengers)
    )

    gmail_service = get_gmail_service()
    calendar_service = get_calendar_service()

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    messages = [
        {
            "role": "user",
            "content": f"Please process all unprocessed travel emails from the last {days_back} days and create calendar events for them.",
        }
    ]

    max_iterations = 50
    for iteration in range(max_iterations):
        if iteration == max_iterations - 1:
            print("Warning: reached max iterations limit")

        response = client.messages.create(
            model=MODEL,
            max_tokens=16384,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    print("\n" + block.text)
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                print(f"  → {block.name}({json.dumps(block.input, ensure_ascii=False)})")

                try:
                    result = execute_tool(block.name, block.input, gmail_service, calendar_service)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        }
                    )
                except Exception as e:
                    print(f"  ✗ Tool error: {e}")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "is_error": True,
                            "content": str(e),
                        }
                    )

            messages.append({"role": "user", "content": tool_results})
        else:
            print(f"Unexpected stop_reason: {response.stop_reason}")
            break


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Travel email → calendar agent")
    parser.add_argument("--days", type=int, default=30, help="Days back to search (default: 30)")
    args = parser.parse_args()

    run_agent(days_back=args.days)
