import argparse
import requests
import sys

ANKI_CONNECT_URL = "http://127.0.0.1:8765"

def invoke(action, **params):
    """Send a request to AnkiConnect."""
    request_payload = {"action": action, "version": 6, "params": params}
    response = requests.post(ANKI_CONNECT_URL, json=request_payload).json()
    if "error" in response and response["error"] is not None:
        print(f"AnkiConnect Error: {response['error']}")
        sys.exit(1)
    return response.get("result")

def get_notes_by_tag(tag):
    """Retrieve all note IDs associated with the given tag."""
    return invoke("findNotes", query=f"tag:{tag}")

def get_note_fields(note_id):
    """Retrieve fields and model for a note."""
    notes = invoke("notesInfo", notes=[note_id])
    return notes[0] if notes else None

def create_deck(deck_name):
    """Create a new deck."""
    invoke("createDeck", deck=deck_name)

def add_card_to_deck(deck_name, model, fields, tags):
    """Modify first field to bypass duplicate protection and add note."""
    formatted_fields = {key: value["value"] for key, value in fields.items()}

    # Ensure uniqueness by modifying the first field slightly
    first_field_key = list(formatted_fields.keys())[0]  # Get the first field name
    formatted_fields[first_field_key] += " (copy)"  # Append "(copy)" to first field

    # Add note to Anki
    invoke("addNote", note={
        "deckName": deck_name,
        "modelName": model,
        "fields": formatted_fields,
        "tags": tags
    })

def copy_cards(tag):
    """Copy all cards with the given tag to the new deck."""
    new_deck = f"Copied_{tag}"
    print(f"Fetching notes with tag '{tag}'...")
    note_ids = get_notes_by_tag(tag)

    if not note_ids:
        print(f"No notes found with tag '{tag}'. Exiting.")
        return

    print(f"Found {len(note_ids)} notes. Creating deck '{new_deck}'...")
    create_deck(new_deck)

    for note_id in note_ids:
        note_data = get_note_fields(note_id)
        if not note_data:
            print(f"Skipping note {note_id} (no data found).")
            continue

        model_name = note_data["modelName"]
        fields = note_data["fields"]
        tags = note_data["tags"]

        print(f"Copying note {note_id} to deck '{new_deck}'...")
        add_card_to_deck(new_deck, model_name, fields, tags)

    print(f"✅ Successfully copied {len(note_ids)} cards to '{new_deck}'.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copy all Anki cards with a specific tag into a new deck.")
    parser.add_argument("tag", help="Tag to filter cards by.")

    args = parser.parse_args()
    copy_cards(args.tag)

