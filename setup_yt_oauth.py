"""
One-time YouTube OAuth setup for HIMYM shortGen.
Generates yt_token.json — store its contents as YT_TOKEN_JSON GitHub Secret.

Usage:
    python setup_yt_oauth.py

When the browser opens, pick the HIMYM YouTube channel (NOT "The One Where").
"""
from google_auth_oauthlib.flow import InstalledAppFlow
import json, os

SCOPES = ['https://www.googleapis.com/auth/youtube.upload']

# Use the yt_client_secret.json from the bike project (same GCloud project, works for YT)
CLIENT_SECRET = os.path.join(
    os.path.dirname(__file__),
    r'..\4kflows\normal-bike-ig\yt_client_secret.json'
)

flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
creds = flow.run_local_server(port=0)

token_path = os.path.join(os.path.dirname(__file__), 'yt_token.json')
with open(token_path, 'w') as f:
    f.write(creds.to_json())

print(f"\nSaved to {token_path}")
print("\n--- Paste this as GitHub Secret YT_TOKEN_JSON ---")
print(creds.to_json())
