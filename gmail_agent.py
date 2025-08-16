import os.path
import base64
import ollama
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from email.mime.text import MIMEText

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

class GmailAgent:
    def __init__(self):
        self.creds = self._get_credentials()
        self.service = build("gmail", "v1", credentials=self.creds)
        self.ollama_models = self._get_ollama_models()
        self.selected_model = self.ollama_models[0] if self.ollama_models else None

    def _get_credentials(self):
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
        return creds

    def _get_ollama_models(self):
        try:
            response = ollama.list()
            models = response.get('models', [])
            
            # The ollama library can return objects instead of dictionaries.
            # We access the model name via the .model attribute.
            if models and hasattr(models[0], 'model'):
                return [model.model for model in models]
            # Fallback for older versions that return dictionaries
            elif models and isinstance(models[0], dict) and 'name' in models[0]:
                 return [model['name'] for model in models]
            else:
                return [] # No models or unrecognized format

        except Exception as e:
            print(f"--- Could not connect to Ollama or parse its response: {e}")
            print("--- Please ensure your local Ollama server is running and you have pulled a model (e.g., 'ollama pull llama3').")
            return []

    def list_ollama_models(self):
        if not self.ollama_models:
            print("No Ollama models found.")
            return
        print("Available Ollama models:")
        for model in self.ollama_models:
            print(f"- {model}")

    def set_ollama_model(self, model_name):
        if model_name in self.ollama_models:
            self.selected_model = model_name
            print(f"Selected Ollama model: {self.selected_model}")
        else:
            print(f"Model '{model_name}' not found.")

    def check_unread_emails(self):
        try:
            results = self.service.users().messages().list(userId='me', labelIds=['INBOX'], q="is:unread").execute()
            messages = results.get('messages', [])
            if not messages:
                print("No unread messages found.")
                return []

            print(f"Found {len(messages)} unread emails.")
            email_list = []
            for msg_summary in messages:
                msg = self.service.users().messages().get(userId='me', id=msg_summary['id'], format='metadata', metadataHeaders=['Subject', 'From']).execute()
                headers = msg['payload']['headers']
                subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
                sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
                email_list.append({'id': msg_summary['id'], 'subject': subject, 'from': sender})
                print(f"- ID: {msg_summary['id']}, From: {sender}, Subject: {subject}")
            return email_list
        except HttpError as error:
            print(f"An error occurred: {error}")
            return []

    def read_email(self, message_id):
        try:
            msg = self.service.users().messages().get(userId='me', id=message_id, format='full').execute()
            payload = msg['payload']
            headers = payload['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
            
            body = self._get_email_body(payload)

            print("----------------------------------------------------")
            print(f"From: {sender}")
            print(f"Subject: {subject}")
            print("----------------------------------------------------")
            print(body)
            return {'subject': subject, 'from': sender, 'body': body}
        except HttpError as error:
            print(f"An error occurred: {error}")
            return None

    def _get_email_body(self, payload):
        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                if "parts" in part:
                    body = self._get_email_body(part)
                    if body:
                        return body
        if "body" in payload and "data" in payload["body"]:
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
        return ""

    def process_with_ollama(self, message_id, prompt_template):
        if not self.selected_model:
            print("No Ollama model selected.")
            return
        
        email_data = self.read_email(message_id)
        if not email_data:
            return

        content = prompt_template.format(
            sender=email_data['from'],
            subject=email_data['subject'],
            body=email_data['body']
        )

        try:
            print(f"Processing with {self.selected_model}...")
            response = ollama.chat(
                model=self.selected_model,
                messages=[{'role': 'user', 'content': content}]
            )
            result = response['message']['content']
            print(f"\nResponse:\n{result}\n")
            return result
        except Exception as e:
            print(f"An error occurred with Ollama: {e}")
            return None

    def send_email(self, to, subject, body):
        try:
            message = MIMEText(body)
            message['to'] = to
            message['subject'] = subject
            create_message = {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
            
            send_message = (self.service.users().messages().send(userId="me", body=create_message).execute())
            print(f"Message Id: {send_message['id']}")
        except HttpError as error:
            print(f"An error occurred: {error}")


def print_help():
    print("\nAvailable commands:")
    print("  check                  - Check for unread emails.")
    print("  read <id>              - Read a specific email.")
    print("  summarize <id>         - Summarize an email using Ollama.")
    print("  reply <id>             - Draft a reply to an email using Ollama.")
    print("  send                   - Send an email.")
    print("  models                 - List available Ollama models.")
    print("  model <model_name>     - Select an Ollama model to use.")
    print("  help                   - Show this help message.")
    print("  quit                   - Exit the agent.")

def main():
    try:
        agent = GmailAgent()
        if not agent.selected_model:
            print("No Ollama models found. Please make sure Ollama is running and you have pulled a model.")
            return
    except FileNotFoundError:
        print("\nERROR: credentials.json not found.")
        print("Please follow the setup instructions to enable the Gmail API and download your credentials.")
        return
    except Exception as e:
        print(f"An unexpected error occurred during initialization: {e}")
        return

    print("Gmail Agent started.")
    print(f"Using Ollama model: {agent.selected_model}")
    print_help()

    while True:
        command = input("\nEnter a command: ").strip().lower().split()
        if not command:
            continue

        action = command[0]

        if action == "quit":
            break
        elif action == "help":
            print_help()
        elif action == "check":
            agent.check_unread_emails()
        elif action == "read":
            if len(command) > 1:
                agent.read_email(command[1])
            else:
                print("Please provide an email ID.")
        elif action == "summarize":
            if len(command) > 1:
                prompt = "Please provide a concise, one-paragraph summary of the following email:\n\n{body}"
                agent.process_with_ollama(command[1], prompt)
            else:
                print("Please provide an email ID.")
        elif action == "reply":
            if len(command) > 1:
                prompt = "You are a helpful assistant. Draft a reply to the following email from {sender} with subject '{subject}'. Keep it professional and address the main points.\n\nEmail Body:\n{body}\n\nDraft your reply below:"
                agent.process_with_ollama(command[1], prompt)
            else:
                print("Please provide an email ID.")
        elif action == "send":
            to = input("To: ")
            subject = input("Subject: ")
            body = input("Body: ")
            agent.send_email(to, subject, body)
        elif action == "models":
            agent.list_ollama_models()
        elif action == "model":
            if len(command) > 1:
                agent.set_ollama_model(command[1])
            else:
                print("Please provide a model name.")
        else:
            print("Unknown command. Type 'help' for a list of commands.")

if __name__ == "__main__":
    main()
