#!/usr/bin/env python3
"""Upload VoC dashboard HTML files to SharePoint via Microsoft Graph API.

Uses app-only authentication (client credentials flow) via MSAL.
Required env vars:
    GRAPH_CLIENT_ID      — Azure AD app registration client ID
    GRAPH_CLIENT_SECRET  — App secret
    GRAPH_TENANT_ID      — Microsoft tenant ID
    SHAREPOINT_SITE_ID   — Target SharePoint site ID
    SHAREPOINT_FOLDER    — Target folder path (default: "Voice of Customer")
"""

import os
import sys
from pathlib import Path

import msal
import requests

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
OUTPUT_DIR = Path(__file__).parent / "output_v3"

FILES_TO_UPLOAD = [
    "pulse_dashboard_v3.html",
    "architecture.html",
]


def get_token() -> str:
    client_id = os.environ.get("GRAPH_CLIENT_ID")
    client_secret = os.environ.get("GRAPH_CLIENT_SECRET")
    tenant_id = os.environ.get("GRAPH_TENANT_ID")

    if not all([client_id, client_secret, tenant_id]):
        print("ERROR: Missing GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET, or GRAPH_TENANT_ID")
        sys.exit(1)

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id, authority=authority, client_credential=client_secret,
    )

    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        print(f"ERROR: Token acquisition failed: {result.get('error_description', result)}")
        sys.exit(1)

    return result["access_token"]


def upload_file(token: str, site_id: str, folder: str, file_path: Path) -> bool:
    content = file_path.read_bytes()
    filename = file_path.name

    # Graph API: PUT to upload/replace file
    url = f"{GRAPH_BASE}/sites/{site_id}/drive/root:/{folder}/{filename}:/content"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
    }

    resp = requests.put(url, headers=headers, data=content, timeout=60)
    if resp.status_code in (200, 201):
        web_url = resp.json().get("webUrl", "")
        print(f"  Uploaded: {filename} -> {web_url}")
        return True
    else:
        print(f"  FAILED: {filename} — {resp.status_code} {resp.text[:200]}")
        return False


def main():
    site_id = os.environ.get("SHAREPOINT_SITE_ID")
    folder = os.environ.get("SHAREPOINT_FOLDER", "Voice of Customer")

    if not site_id:
        print("ERROR: SHAREPOINT_SITE_ID not set")
        sys.exit(1)

    if not OUTPUT_DIR.exists():
        print(f"ERROR: Output directory not found: {OUTPUT_DIR}")
        sys.exit(1)

    print("\n  SharePoint Upload")
    print("  " + "=" * 40)

    token = get_token()
    success = 0

    for filename in FILES_TO_UPLOAD:
        file_path = OUTPUT_DIR / filename
        if not file_path.exists():
            print(f"  [warn] File not found, skipping: {filename}")
            continue
        if upload_file(token, site_id, folder, file_path):
            success += 1

    print(f"\n  Uploaded {success}/{len(FILES_TO_UPLOAD)} files")
    if success == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
