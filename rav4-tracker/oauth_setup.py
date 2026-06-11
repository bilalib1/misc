"""One-time Gmail consent. Opens a browser, you approve, saves token.json
(which contains the offline refresh token used by every later run)."""
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

import paths

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def main():
    paths.ensure()
    client_secret = sys.argv[1] if len(sys.argv) > 1 else str(paths.CLIENT_SECRET)
    flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    paths.TOKEN.write_text(creds.to_json())
    if not creds.refresh_token:
        print("WARNING: no refresh token returned. Delete token.json and re-run.")
    print(f"Saved {paths.TOKEN}")


if __name__ == "__main__":
    main()
