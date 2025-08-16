import os.path
import base64
import ollama
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

def get_email_body(payload):
    """
    Recursively search for the text/plain part of an email payload.
    """
    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
            # Recurse into multipart/alternative parts
            if "parts" in part:
                body = get_email_body(part)
                if body:
                    return body
    if "body" in payload and "data" in payload["body"]:
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
    return "" # Return empty string if no plain text part is found

def main():
  """
  Connects to Gmail, fetches unread emails, and uses a local Ollama instance
  to summarize them.
  """
  creds = None
  if os.path.exists("token.json"):
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
  
  if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
      creds.refresh(Request())
    else:
      flow = InstalledAppFlow.from_client_secrets_file(
          "credentials.json", SCOPES
      )
      creds = flow.run_local_server(port=0)
    with open("token.json", "w") as token:
      token.write(creds.to_json())

  try:
    service = build("gmail", "v1", credentials=creds)
    results = service.users().messages().list(userId='me', labelIds=['INBOX'], q="is:unread").execute()
    messages = results.get('messages', [])

    if not messages:
        print("No unread messages found.")
        return

    print(f"Found {len(messages)} unread emails. Summarizing with Ollama...\n")
    
    for message in messages:
        # Fetch the full email content
        msg = service.users().messages().get(userId='me', id=message['id'], format='full').execute()
        
        headers = msg['payload']['headers']
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
        sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
        
        body = get_email_body(msg['payload'])

        if not body:
            print(f"--- From: {sender}")
            print(f"--- Subject: {subject}")
            print("--- Could not extract text body for this email.\n")
            continue

        print("----------------------------------------------------")
        print(f"From: {sender}")
        print(f"Subject: {subject}")
        print("----------------------------------------------------")
        
        try:
            # Connect to Ollama for summarization
            response = ollama.chat(
                model='gemma3:1b', # Using your specified model
                messages=[
                    {
                        'role': 'user',
                        'content': f"Please provide a concise, one-paragraph summary of the following email:\n\n{body}",
                    },
                ]
            )
            summary = response['message']['content']
            print(f"\nSummary:\n{summary}\n")
        
        except Exception as e:
            print(f"\n--- Could not connect to Ollama: {e}")
            print("--- Please ensure your local Ollama server is running and the 'llama3' model is installed.\n")
            # Stop the script if Ollama isn't running
            break 

  except HttpError as error:
    print(f"An error occurred with the Gmail API: {error}")
  except FileNotFoundError:
    print("\nERROR: credentials.json not found.")
    print("Please follow the setup instructions to enable the Gmail API and download your credentials.")
  except Exception as e:
    print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
  main()