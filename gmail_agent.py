import os.path
import base64
import ollama
import json
import sys
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
        self.tools = {
            "fetch_unread_emails": self.fetch_unread_emails,
            "read_email": self.read_email,
            "analyze_and_summarize": self.analyze_and_summarize,
            "send_email": self.send_email,
        }

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
            if models and hasattr(models[0], 'model'):
                return [model.model for model in models]
            elif models and isinstance(models[0], dict) and 'name' in models[0]:
                 return [model['name'] for model in models]
            else:
                return []
        except Exception as e:
            print(f"--- Could not connect to Ollama: {e}")
            return []

    def list_ollama_models(self):
        # This is for interactive mode
        if not self.ollama_models:
            print("No Ollama models found.")
            return
        print("Available Ollama models:")
        for model in self.ollama_models:
            print(f"- {model}")

    def set_ollama_model(self, model_name):
        # This is for interactive mode
        if model_name in self.ollama_models:
            self.selected_model = model_name
            print(f"Selected Ollama model: {self.selected_model}")
        else:
            print(f"Model '{model_name}' not found.")

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

    # --- Agent Tools ---

    def fetch_unread_emails(self, max_count=20):
        """Fetches the content of unread emails up to a max_count."""
        print(f"Fetching up to {max_count} unread emails...")
        try:
            results = self.service.users().messages().list(userId='me', labelIds=['INBOX'], q="is:unread", maxResults=max_count).execute()
            messages = results.get('messages', [])
            if not messages:
                return "No unread messages found."
            
            email_contents = []
            for msg_summary in messages:
                msg = self.service.users().messages().get(userId='me', id=msg_summary['id'], format='full').execute()
                headers = msg['payload']['headers']
                subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
                sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
                body = self._get_email_body(msg['payload'])
                email_contents.append({"from": sender, "subject": subject, "body": body})
            print(f"Found {len(email_contents)} emails.")
            return email_contents
        except HttpError as error:
            return f"An error occurred: {error}"

    def read_email(self, message_id):
        """Reads a single, specific email by its ID."""
        print(f"Reading email with ID: {message_id}...")
        try:
            msg = self.service.users().messages().get(userId='me', id=message_id, format='full').execute()
            # ... (rest of the read_email logic is the same)
            return "Email read successfully. (Full content would be returned here)"
        except HttpError as error:
            return f"An error occurred: {error}"

    def analyze_and_summarize(self, emails, user_request):
        """Analyzes a list of emails to provide a summary based on a user request."""
        print("Analyzing emails with Ollama...")
        # If the previous step returned a string (e.g., "No unread emails"), just pass it through.
        if not isinstance(emails, list):
            return emails
        if not emails:
            return "No emails provided to analyze."

        # Prepare a simplified text blob for the LLM
        email_blob = ""
        for email in emails:
            email_blob += f"From: {email['from']}\nSubject: {email['subject']}\n\n{email['body'][:1000]}...\n\n---\n\n"

        prompt = f"""
        You are a helpful assistant. A user has provided a batch of their recent emails and made a request.
        Analyze the emails and provide a concise, helpful response that directly answers the user's request.

        USER'S REQUEST: "{user_request}"

        EMAIL DATA:
        {email_blob}

        YOUR RESPONSE:
        """
        
        try:
            response = ollama.chat(
                model=self.selected_model,
                messages=[{'role': 'user', 'content': prompt}]
            )
            return response['message']['content']
        except Exception as e:
            return f"An error occurred with Ollama: {e}"

    def send_email(self, to, subject, body):
        """Sends an email."""
        print(f"Sending email to {to}...")
        try:
            message = MIMEText(body)
            message['to'] = to
            message['subject'] = subject
            create_message = {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
            send_message = (self.service.users().messages().send(userId="me", body=create_message).execute())
            return f"Message sent successfully. ID: {send_message['id']}"
        except HttpError as error:
            return f"An error occurred: {error}"

    # --- Planner and Executor ---

    def create_plan(self, user_task):
        print("Creating a plan with Ollama...")
        
        # Create a string describing the available tools
        tools_description = ""
        for name, func in self.tools.items():
            tools_description += f'- {name}: {func.__doc__}\n'

        prompt = f"""
        You are a planner that helps a Gmail agent execute tasks.
        Based on the user's request, create a JSON plan of the steps to take.
        You can only use the functions available in the following list. Do not invent new functions.

        Available Functions:
        {tools_description}

        The user's request is: "{user_task}"

        Your output must be a JSON object with a single key "plan" which is a list of steps.
        Each step is a dictionary with two keys: "function" (the name of the function to call) and "parameters" (a dictionary of arguments for that function).
        For the 'analyze_and_summarize' function, always include the original 'user_request' as a parameter.

        Example Plan:
        {{
          "plan": [
            {{
              "function": "fetch_unread_emails",
              "parameters": {{ "max_count": 20 }}
            }},
            {{
              "function": "analyze_and_summarize",
              "parameters": {{ "emails": "{{step1_result}}", "user_request": "{user_task}" }}
            }}
          ]
        }}

        Now, create the plan for the user's request.
        """
        
        try:
            response = ollama.chat(
                model=self.selected_model,
                messages=[{'role': 'user', 'content': prompt}]
            )
            plan_str = response['message']['content']
            # Clean up the response to extract only the JSON
            plan_str = plan_str[plan_str.find('{'):plan_str.rfind('}')+1]
            return json.loads(plan_str)
        except Exception as e:
            print(f"Error creating plan: {e}")
            return None

    def execute_plan(self, plan):
        print("Executing plan...")
        step_results = {}
        for i, step in enumerate(plan['plan']):
            func_name = step['function']
            # Make a copy of parameters to avoid modifying the original plan
            params = step['parameters'].copy()
            
            print(f"Executing Step {i+1}: {func_name}")
            print(f"  - Initial parameters: {params}")

            # Substitute results from previous steps
            for key, value in params.items():
                if isinstance(value, str) and value.strip().startswith("{{'" ) and value.strip().endswith("'}}"):
                    # Be robust against whitespace
                    prev_step_key = value.strip().strip("'{{'").strip()
                    print(f"  - Found placeholder '{value}'. Looking for key '{prev_step_key}' in previous results.")
                    if prev_step_key in step_results:
                        params[key] = step_results[prev_step_key]
                        print(f"  - Substitution successful. New value for '{key}' is (type: {type(params[key])}).")
                    else:
                        print(f"  - WARNING: Could not find result for key '{prev_step_key}'. Placeholder will not be replaced.")

            # Abridged view for printing, to avoid dumping huge lists of emails
            abridged_params = {k: (v if not isinstance(v, list) else f'<list of {len(v)} items>') for k, v in params.items()}
            print(f"  - Final parameters: {abridged_params}")


            if func_name in self.tools:
                try:
                    result = self.tools[func_name](**params)
                    step_results[f"step{i+1}_result"] = result
                    print(f"--- Step {i+1} ({func_name}) result ---")
                    # Avoid printing huge lists of emails
                    if isinstance(result, list) and len(result) > 5:
                        print(f"(Result is a list with {len(result)} items)")
                    else:
                        print(result)
                    print("-" * (len(f"--- Step {i+1} ({func_name}) result ---")))

                except Exception as e:
                    print(f"Error executing step {i+1} ({func_name}): {e}")
                    return
            else:
                print(f"Unknown function in plan: {func_name}")
                return

def run_interactive_mode(agent):
    print("Gmail Agent started in interactive mode.")
    print(f"Using Ollama model: {agent.selected_model}")
    
    while True:
        command_str = input("\nEnter a command ('help' for list, 'quit' to exit): ").strip().lower()
        if not command_str:
            continue
        
        command = command_str.split()
        action = command[0]

        if action == "quit":
            break
        # ... (Add back other interactive commands if desired)
        else:
            # For simplicity, we'll just allow tasking in interactive mode too
            task = command_str
            plan = agent.create_plan(task)
            if plan:
                agent.execute_plan(plan)

def main():
    try:
        agent = GmailAgent()
        if not agent.selected_model:
            print("No Ollama models found. Please ensure Ollama is running and you have pulled a model.")
            return
    except FileNotFoundError:
        print("\nERROR: credentials.json not found.")
        return
    except Exception as e:
        print(f"An unexpected error occurred during initialization: {e}")
        return

    if len(sys.argv) > 1:
        # Task mode
        task = " ".join(sys.argv[1:])
        print(f"Received task: {task}")
        plan = agent.create_plan(task)
        if plan:
            agent.execute_plan(plan)
    else:
        # Interactive mode
        run_interactive_mode(agent)

if __name__ == "__main__":
    main()