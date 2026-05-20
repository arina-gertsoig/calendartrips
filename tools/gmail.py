import base64
import re
from datetime import datetime, timedelta

from tools.pdf import extract_pdf_text


TRAVEL_PROCESSED_LABEL = "travel-processed"

TRAVEL_SEARCH_QUERY = (
    "(subject:(flight OR train OR bus OR hotel OR booking OR reservation OR confirmation OR ticket OR itinerary) "
    "OR from:(booking.com OR airbnb.com OR expedia.com OR kayak.com OR skyscanner.com OR ryanair.com OR "
    "wizzair.com OR easyjet.com OR lufthansa.com OR klm.com OR airfrance.com OR britishairways.com OR "
    "emirates.com OR flydubai.com OR ukraineintl.com OR mau.com.ua OR uz.gov.ua OR ukrzaliznytsia.com OR "
    "tickets.ua OR infobus.eu OR flixbus.com OR busbud.com OR lot.com)) "
    "-label:travel-processed"
)

_label_id_cache: dict[str, str] = {}


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
    pdf_text = _extract_pdf_attachments(payload, service, message_id)

    full_text = body
    if pdf_text:
        full_text += "\n\n--- PDF Attachments ---\n" + pdf_text

    if len(full_text) > 30000:
        full_text = full_text[:30000] + "\n...[truncated]"

    return {
        "id": message_id,
        "subject": headers.get("Subject", "(no subject)"),
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "date": headers.get("Date", ""),
        "body": full_text,
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
        plain = next((p for p in parts if p.get("mimeType") == "text/plain"), None)
        if plain:
            return _extract_body(plain)
        html = next((p for p in parts if p.get("mimeType") == "text/html"), None)
        if html:
            return _extract_body(html)
        for part in parts:
            text = _extract_body(part)
            if text:
                return text

    return ""


def _html_to_text(html: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Tables: each row on new line, cells separated by |
    text = re.sub(r"</tr>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<t[dh][^>]*>", " | ", text, flags=re.IGNORECASE)
    # Block elements
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:p|div|h[1-6]|section|article)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # HTML entities
    entities = {
        "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&apos;": "'", "&#160;": " ",
        "&hellip;": "...", "&mdash;": "—", "&ndash;": "–",
        "&laquo;": "«", "&raquo;": "»",
    }
    for entity, replacement in entities.items():
        text = text.replace(entity, replacement)
    text = re.sub(r"&#\d+;", "", text)
    text = re.sub(r"&[a-z]+;", "", text)
    # Whitespace cleanup
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_pdf_attachments(payload: dict, service, message_id: str) -> str:
    pdf_texts = []
    _collect_pdf_parts(payload, service, message_id, pdf_texts)
    return "\n\n".join(pdf_texts)


def _collect_pdf_parts(payload: dict, service, message_id: str, results: list) -> None:
    mime = payload.get("mimeType", "")
    filename = payload.get("filename", "")

    is_pdf = mime == "application/pdf" or filename.lower().endswith(".pdf")
    if is_pdf:
        attachment_id = payload.get("body", {}).get("attachmentId")
        if attachment_id:
            try:
                attachment = (
                    service.users()
                    .messages()
                    .attachments()
                    .get(userId="me", messageId=message_id, id=attachment_id)
                    .execute()
                )
                data = base64.urlsafe_b64decode(attachment["data"] + "==")
                text = extract_pdf_text(data)
                if text:
                    label = filename or "attachment.pdf"
                    results.append(f"[PDF: {label}]\n{text}")
            except Exception:
                pass

    for part in payload.get("parts", []):
        _collect_pdf_parts(part, service, message_id, results)


def get_or_create_label(service, label_name: str) -> str:
    if label_name in _label_id_cache:
        return _label_id_cache[label_name]

    existing = service.users().labels().list(userId="me").execute()
    for label in existing.get("labels", []):
        if label["name"] == label_name:
            _label_id_cache[label_name] = label["id"]
            return label["id"]

    new_label = service.users().labels().create(userId="me", body={"name": label_name}).execute()
    _label_id_cache[label_name] = new_label["id"]
    return new_label["id"]


def mark_email_processed(service, message_id: str) -> dict:
    label_id = get_or_create_label(service, TRAVEL_PROCESSED_LABEL)
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"addLabelIds": [label_id]},
    ).execute()
    return {"success": True, "message_id": message_id, "label": TRAVEL_PROCESSED_LABEL}
