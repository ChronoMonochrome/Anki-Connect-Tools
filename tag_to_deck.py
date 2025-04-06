import argparse
import json
import random
import requests

ANKI_CONNECT_URL = "http://localhost:8765"

def anki_request(action, params=None):
    payload = {
        "action": action,
        "version": 6,
        "params": params or {}
    }
    response = requests.post(ANKI_CONNECT_URL, json=payload).json()
    if response.get("error") is not None:
        raise Exception(f"AnkiConnect error: {response['error']}")
    return response["result"]

def find_cards_with_all_tags(all_tags):
    tag_query = " ".join([f'tag:"{tag}"' for tag in all_tags])
    return anki_request("findCards", {"query": tag_query})

def get_unique_note_infos(card_ids):
    notes_info = anki_request("cardsInfo", {"cards": card_ids})
    note_ids = list({card["note"] for card in notes_info})
    print(f" Corresponding unique notes found: {len(note_ids)}")
    return anki_request("notesInfo", {"notes": note_ids})

def create_deck_if_not_exists(deck_name):
    decks = anki_request("deckNames")
    if deck_name not in decks:
        print(f" Creating new deck: {deck_name}")
        anki_request("createDeck", {"deck": deck_name})

def add_cloned_notes(notes, target_deck, shuffle=False):
    if shuffle:
        random.shuffle(notes)

    new_notes = []
    for note in notes:
        model_name = note["modelName"]
        fields = note["fields"]
        tags = note["tags"]

        cloned_fields = {}
        for key, val in fields.items():
            text = val.get("value", "")
            if key.lower() == "text":
                # Hidden anti-duplicate marker (invisible span)
                rand_marker = f'<span style="display:none;">&#8204;{random.randint(100000, 999999)}</span>'
                text += rand_marker
            cloned_fields[key] = text

        new_note = {
            "deckName": target_deck,
            "modelName": model_name,
            "fields": cloned_fields,
            "tags": tags,
            "options": {
                "allowDuplicate": True,
                "duplicateScope": "deck"
            }
        }
        new_notes.append(new_note)

    print(f" Creating {len(new_notes)} new notes...")
    result = anki_request("addNotes", {"notes": new_notes})
    print(" Notes added successfully.")
    return result

def main():
    parser = argparse.ArgumentParser(description="Clone notes with specific tags into a new Anki deck.")
    parser.add_argument("tags", metavar="TAG", type=str, nargs="+", help="Tags to match (notes must have ALL).")
    parser.add_argument("--deck", required=True, help="Name of the target deck for cloned notes.")
    parser.add_argument("--shuffle", action="store_true", help="Shuffle notes before copying.")
    args = parser.parse_args()

    print("\n Matching notes that have ALL of these tags:")
    for tag in args.tags:
        print(f"   - #{tag}")

    card_ids = find_cards_with_all_tags(args.tags)
    print(f"\nTotal cards matching all tags: {len(card_ids)}")
    if not card_ids:
        print(" No notes found matching all tags.")
        return

    note_infos = get_unique_note_infos(card_ids)
    create_deck_if_not_exists(args.deck)
    result = add_cloned_notes(note_infos, args.deck, shuffle=args.shuffle)

if __name__ == "__main__":
    main()
