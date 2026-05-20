import json
import os

import anthropic
from dotenv import load_dotenv

from auth import get_calendar_service, get_gmail_service
from tools.calendar import create_calendar_event, list_calendars
from tools.gmail import get_email_content, mark_email_processed, search_travel_emails

load_dotenv()

MODEL = "claude-opus-4-7"

SYSTEM_PROMPT = """You are a travel assistant that automatically extracts travel information from emails and creates Google Calendar events.

Your workflow:
1. Search for unprocessed travel confirmation emails using `search_travel_emails`.
2. For each email found, read the full content with `get_email_content`.
3. Extract ALL travel segments from the email:
   - Flights: each flight leg is a separate event (outbound + return + any connections)
   - Trains/buses: each leg separately
   - Hotels: one event for the entire stay (check-in to check-out)
4. List available calendars with `list_calendars` to pick the right one (use primary if unsure).
5. For each segment, call `create_calendar_event` with:
   - `summary`: descriptive title, e.g. "✈️ Kyiv → Warsaw (LOT LO782)" or "🏨 Hotel Marriott Warsaw"
   - `start_datetime` / `end_datetime`: in ISO 8601 format with timezone offset, e.g. "2024-06-15T10:30:00+03:00"
   - `description`: booking reference, seat, class, confirmation number, etc.
   - `location`: departure airport/station or hotel address
   - `attendee_email`: the email address of the passenger whose name is on the ticket (extract from the email body — look for the passenger name and match it to an email address in the email, or use the recipient's email if it matches the ticket name)
   - `timezone`: IANA timezone name, e.g. "Europe/Kyiv", "Europe/Warsaw"
6. After creating all events for an email, mark it as processed with `mark_email_processed`.

Important rules:
- Create a separate calendar event for every travel segment (do not combine outbound + return into one event).
- For the attendee_email: use the email of the person named on the ticket. If the ticket is in the name of the email recipient, use the "To" address from the email. If multiple passengers are on the ticket, create one event and add the primary passenger's email.
- If you cannot determine the exact time, make a best guess and note uncertainty in the description.
- Always prefer the local timezone of the departure city for `start_datetime`.
- If an email has no travel info (false positive), skip it and do NOT mark it processed.
- Report what you've done at the end: how many emails processed, how many events created."""

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
        "description": "Fetch the full content (subject, from, to, date, body) of a specific email by its ID.",
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
        "description": "List all Google Calendars available in the account. Returns calendar IDs and names.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "create_calendar_event",
        "description": "Create a Google Calendar event for a travel segment and optionally invite the passenger via email.",
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
                    "description": "Event description with booking reference, seat, confirmation number, etc.",
                },
                "location": {
                    "type": "string",
                    "description": "Departure location: airport name/code, train station, or hotel address.",
                },
                "attendee_email": {
                    "type": "string",
                    "description": "Email of the passenger named on the ticket. They will receive a calendar invite.",
                },
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone of the departure location, e.g. 'Europe/Kyiv', 'Europe/Warsaw'.",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Google Calendar ID to add the event to. Use 'primary' for the main calendar.",
                    "default": "primary",
                },
            },
            "required": ["summary", "start_datetime", "end_datetime"],
        },
    },
    {
        "name": "mark_email_processed",
        "description": "Add the 'travel-processed' Gmail label to an email so it won't be picked up on the next run.",
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
            timezone=inputs.get("timezone", "UTC"),
            calendar_id=inputs.get("calendar_id", "primary"),
        )
    if name == "mark_email_processed":
        return mark_email_processed(gmail_service, inputs["message_id"])
    raise ValueError(f"Unknown tool: {name}")


def run_agent(days_back: int = 30):
    print(f"Starting travel agent (searching last {days_back} days)...")

    gmail_service = get_gmail_service()
    calendar_service = get_calendar_service()

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    messages = [
        {
            "role": "user",
            "content": f"Please process all unprocessed travel emails from the last {days_back} days and create calendar events for them.",
        }
    ]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,
            messages=messages,
        )

        # Append assistant response
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Print final message
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
