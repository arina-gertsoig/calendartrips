import base64
import re
from datetime import datetime, timedelta


TRAVEL_PROCESSED_LABEL = "travel-processed"

TRAVEL_SEARCH_QUERY = (
    "(subject:(flight OR train OR bus OR hotel OR booking OR reservation OR confirmation OR ticket OR itinerary) "
    "OR from:(booking.com OR airbnb.com OR expedia.com OR kayak.com OR skyscanner.com OR ryanair.com OR "
    "wizzair.com OR easyjet.com OR lufthansa.com OR klm.com OR airfrance.com OR britishairways.com OR "
    "emirates.com OR flydubai.com OR ukraineintl.com OR mau.com.ua OR uz.gov.ua OR ukrzaliznytsia.com OR "
    "tickets.ua OR infobus.eu OR flixbus.com OR busbud.com)) "
    "-label:travel-processed"
)


def search_travel_emails(service, days_back: int = 30) -> list[dict]:
    after_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y/%m/%d")
    query = f"{TRAVEL_SEARCH_QUERY} after:{after_date}"

    result = service.users().messages().list(userId="me", q=query, maxResults=50).execute()
    messages = result.get("messages", [])

    emails = []
    for msg in messages:
        meta = (
            service.users()
            .messages()
            .get(userId="me", id=msg["id"], format="metadata", metadataHeaders=["Subject", "From", "Date"])
            .execute()
        )
        headers = {h["name"]: h["value"] for h in meta.get("payload", {}).get("headers", [])}
        emails.append(
            {
                "id": msg["id"],
                "subject": headers.get("Subject", "(no subject)"),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
            }
        )

    return emails


def get_email_content(service, message_id: str) -> dict:
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    payload = msg.get("payload", {})
    headers = {h["name"]: h["value"] for h in payload.get("headers", [])}

    body = _extract_body(payload)
    if len(body) > 8000:
        body = body[:8000] + "\n...[truncated]"

    return {
        "id": message_id,
        "subject": headers.get("Subject", "(no subject)"),
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "date": headers.get("Date", ""),
        "body": body,
    }


def _extract_body(payload: dict) -> str:
    mime = payload.get("mimeType", "")

    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace") if data else ""

    if mime == "text/html":
        data = payload.get("body", {}).get("data", "")
        html = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace") if data else ""
        return _html_to_text(html)

    if mime.startswith("multipart/"):
        parts = payload.get("parts", [])
        # Prefer plain text; fall back to html
        plain = next((p for p in parts if p.get("mimeType") == "text/plain"), None)
        if plain:
            return _extract_body(plain)
        html = next((p for p in parts if p.get("mimeType") == "text/html"), None)
        if html:
            return _extract_body(html)
        # Recurse into nested multipart
        for part in parts:
            text = _extract_body(part)
            if text:
                return text

    return ""


def _html_to_text(html: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;", "'", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def get_or_create_label(service, label_name: str) -> str:
    existing = service.users().labels().list(userId="me").execute()
    for label in existing.get("labels", []):
        if label["name"] == label_name:
            return label["id"]

    new_label = service.users().labels().create(userId="me", body={"name": label_name}).execute()
    return new_label["id"]


def mark_email_processed(service, message_id: str) -> dict:
    label_id = get_or_create_label(service, TRAVEL_PROCESSED_LABEL)
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"addLabelIds": [label_id]},
    ).execute()
    return {"success": True, "message_id": message_id, "label": TRAVEL_PROCESSED_LABEL}
