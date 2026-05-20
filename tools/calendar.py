def list_calendars(service) -> list[dict]:
    result = service.calendarList().list().execute()
    return [
        {"id": c["id"], "summary": c.get("summary", ""), "primary": c.get("primary", False)}
        for c in result.get("items", [])
    ]


def create_calendar_event(
    service,
    summary: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    location: str = "",
    attendee_email: str = "",
    start_timezone: str = "UTC",
    end_timezone: str = "UTC",
    calendar_id: str = "primary",
) -> dict:
    event = {
        "summary": summary,
        "description": description,
        "location": location,
        "start": {"dateTime": start_datetime, "timeZone": start_timezone},
        "end": {"dateTime": end_datetime, "timeZone": end_timezone},
    }

    if attendee_email:
        event["attendees"] = [{"email": attendee_email}]

    created = (
        service.events()
        .insert(calendarId=calendar_id, body=event, sendUpdates="all")
        .execute()
    )

    return {
        "id": created["id"],
        "summary": created.get("summary", ""),
        "start": created.get("start", {}),
        "end": created.get("end", {}),
        "html_link": created.get("htmlLink", ""),
        "attendees": [a["email"] for a in created.get("attendees", [])],
    }
