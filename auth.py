import os
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]

TOKEN_FILE = "token.pickle"
CREDENTIALS_FILE = "credentials.json"

_credentials = None


def get_google_credentials():
    global _credentials
    if _credentials and _credentials.valid:
        return _credentials

    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    _credentials = creds
    return creds


def get_gmail_service():
    creds = get_google_credentials()
    return build("gmail", "v1", credentials=creds)


def get_calendar_service():
    creds = get_google_credentials()
    return build("calendar", "v3", credentials=creds)


def get_people_service():
    creds = get_google_credentials()
    return build("people", "v1", credentials=creds)
