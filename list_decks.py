import json
import requests

# AnkiConnect API URL
ANKI_CONNECT_URL = "http://127.0.0.1:8765"

def invoke(action, params=None):
    """Send a request to AnkiConnect."""
    request_json = {
        "action": action,
        "version": 6,
        "params": params or {}
    }
    response = requests.post(ANKI_CONNECT_URL, json=request_json)
    return response.json().get("result")

def list_all_decks():
    """Retrieve a list of all available decks and subdecks."""
    return invoke("deckNames")

if __name__ == "__main__":
    decks = list_all_decks()
    if decks:
        print("Available decks:")
        for deck in decks:
            print(f"- {deck}")
    else:
        print("No decks found.")
