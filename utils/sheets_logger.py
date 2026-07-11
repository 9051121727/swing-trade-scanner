"""
Pushes swing scan results to a Google Sheet using a service account.

Setup:
1. Create a Google Cloud service account, enable the Sheets API, and download its JSON key.
2. Share your target Google Sheet with the service account's client_email (Editor access).
3. Store the JSON key contents as a GitHub Actions secret named GOOGLE_CREDENTIALS_JSON.
4. Store the target sheet ID as a secret/variable named SHEET_ID
   (the long id in the sheet's URL: https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit).
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

# Ensure the repo root is importable even if this file is run directly
# (e.g. via an editor's "Run" button) instead of imported by another script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

HEADER = ["ScanDate", "Symbol", "Entry", "StopLoss", "Target", "RSI", "VolSpike", "CAR_Status", "LoggedAt"]


def _get_client() -> gspread.Client:
    if not config.GOOGLE_CREDENTIALS_JSON:
        raise RuntimeError(
            "GOOGLE_CREDENTIALS_JSON is not set. Add your service account JSON as a GitHub secret "
            "and export it into the environment before running."
        )
    creds_dict = json.loads(config.GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_worksheet(client: gspread.Client):
    if not config.GOOGLE_SHEET_ID:
        raise RuntimeError("SHEET_ID is not set. Add it as a GitHub secret/variable.")

    sheet = client.open_by_key(config.GOOGLE_SHEET_ID)

    try:
        worksheet = sheet.worksheet(config.GOOGLE_WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title=config.GOOGLE_WORKSHEET_NAME, rows=1000, cols=len(HEADER))
        worksheet.append_row(HEADER)

    # Ensure header exists if the sheet was empty/pre-existing
    first_row = worksheet.row_values(1)
    if first_row != HEADER:
        worksheet.insert_row(HEADER, 1)

    return worksheet


def update_swing_dashboard(setups: list[dict]) -> None:
    """
    Appends today's swing setups to the configured Google Sheet worksheet.
    """
    client = _get_client()
    worksheet = _get_worksheet(client)

    logged_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        [
            s["ScanDate"], s["Symbol"], s["Entry"], s["StopLoss"],
            s["Target"], s["RSI"], s["VolSpike"], s["CAR_Status"], logged_at,
        ]
        for s in setups
    ]

    worksheet.append_rows(rows, value_input_option="USER_ENTERED")
    print(f"Pushed {len(rows)} setup(s) to Google Sheet '{config.GOOGLE_WORKSHEET_NAME}'.")
