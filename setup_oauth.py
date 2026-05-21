"""
Run this once locally to generate a refresh token for Drive uploads.
Requires oauth_client.json (OAuth 2.0 Desktop App credentials) in this folder.

Usage:
    python setup_oauth.py

Then add these three values as GitHub Secrets:
    GOOGLE_REFRESH_TOKEN
    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly',
]

flow = InstalledAppFlow.from_client_secrets_file(
    'client_secret_1061831573768-v5195flb6ql1a38fva5ic0a5b0gm80iq.apps.googleusercontent.com.json',
    SCOPES,
)
creds = flow.run_local_server(port=0)

print("\n--- Copy these into GitHub Secrets ---")
print(f"GOOGLE_REFRESH_TOKEN  = {creds.refresh_token}")
print(f"GOOGLE_CLIENT_ID      = {creds.client_id}")
print(f"GOOGLE_CLIENT_SECRET  = {creds.client_secret}")
