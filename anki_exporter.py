import json
import requests
import argparse
import os
import re
import base64
import imghdr # Used for basic image format detection, though not strictly for saving filename
import mimetypes # Used for guessing file extensions if imghdr fails
from bs4 import BeautifulSoup

# AnkiConnect API URL
ANKI_CONNECT_URL = "http://127.0.0.1:8765"

def invoke(action, params=None):
    """Send a request to AnkiConnect."""
    request_json = {
        "action": action,
        "version": 6, # Ensure this matches your AnkiConnect version. Check AnkiConnect add-on config.
        "params": params or {}
    }
    print(f"DEBUG: Invoking AnkiConnect action: '{action}' with params: {params.keys() if params else ''}...")
    try:
        response = requests.post(ANKI_CONNECT_URL, json=request_json, timeout=30)
        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        response_json = response.json()
        if "error" in response_json and response_json["error"] is not None:
            print(f"ERROR: AnkiConnect returned error for action '{action}': {response_json['error']}")
            return None
        print(f"DEBUG: Action '{action}' successful.")
        return response_json.get("result")
    except requests.exceptions.ConnectionError:
        print(f"CRITICAL ERROR: Could not connect to AnkiConnect at {ANKI_CONNECT_URL}. Please ensure Anki is running and AnkiConnect add-on is installed.")
        return None
    except requests.exceptions.Timeout:
        print(f"ERROR: AnkiConnect request for action '{action}' timed out after 30 seconds. Anki may be busy or unresponsive.")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"ERROR: AnkiConnect HTTP error for action '{action}': {e}")
        print(f"Response content: {e.response.text}") # Print response content for HTTP errors
        return None
    except requests.exceptions.RequestException as e:
        print(f"ERROR: AnkiConnect request failed for action '{action}': {e}")
        return None
    except json.JSONDecodeError:
        print(f"ERROR: AnkiConnect returned invalid JSON for action '{action}'. Response text: {response.text}")
        return None


def get_cards(deck_name=None, tag=None):
    """Retrieve all card IDs from a specified deck or by tag across all decks."""
    if tag:
        query = f'tag:"{tag}"'
    elif deck_name:
        query = f'deck:"{deck_name}"'
    else:
        raise ValueError("Either deck name or tag must be provided.")
    
    print(f"DEBUG: Finding cards with query: '{query}'")
    card_ids = invoke("findCards", {"query": query})
    if card_ids:
        print(f"DEBUG: Found {len(card_ids)} cards.")
    else:
        print("DEBUG: No cards found for the given query.")
    return card_ids if card_ids else []

def get_note_info(note_id):
    """Retrieve note information including fields, tags, and note type."""
    print(f"DEBUG: Getting info for note ID: {note_id}")
    note_info = invoke("notesInfo", {"notes": [note_id]})
    return note_info[0] if note_info and isinstance(note_info, list) else None

def get_model_fields(model_name):
    """Get the field names for a specific note type (model)."""
    print(f"DEBUG: Getting field names for model: '{model_name}'")
    model_data = invoke("modelFieldNames", {"modelName": model_name})
    if model_data:
        print(f"DEBUG: Model '{model_name}' fields: {model_data}")
    return model_data if model_data else []

def extract_media_filenames_from_html(html_content):
    """
    Extracts all media filenames (images, audio, video) from HTML content
    using BeautifulSoup, and also handles [sound:...] tags with regex.
    """
    found_files = set()
    
    # Print the first 200 characters of the HTML content for debugging
    print(f"DEBUG: Analyzing HTML content for media (first 200 chars): {html_content[:200]}...")

    # 1. Extract from standard HTML tags using BeautifulSoup
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Look for 'src' attribute in <img>, <audio>, <video>, and <source> tags
    for tag in soup.find_all(['img', 'audio', 'video', 'source']):
        if tag.has_attr('src'):
            filename_with_path = tag['src']
            if filename_with_path: 
                # Anki media files are usually referenced by their base filename.
                # Example: <img src="collection.media/image.png"> or <img src="_image.png">
                # We need to extract just the base filename.
                clean_filename = os.path.basename(filename_with_path)
                found_files.add(clean_filename)
                print(f"DEBUG: Found HTML media src: '{filename_with_path}', extracted: '{clean_filename}'")
    
    # 2. Extract from [sound:...] tags using regex (as these are Anki-specific)
    # Example: [sound:my_audio.mp3]
    sound_matches = re.findall(r'\[sound:([^\]]+)\]', html_content)
    for filename_with_path in sound_matches:
        if filename_with_path:
            clean_filename = os.path.basename(filename_with_path)
            found_files.add(clean_filename)
            print(f"DEBUG: Found sound tag media: '{filename_with_path}', extracted: '{clean_filename}'")

    if not found_files:
        print("DEBUG: No media files found in this HTML content.")
    else:
        print(f"DEBUG: All extracted media filenames: {list(found_files)}")
    return list(found_files)

def download_media(media_filename, media_folder):
    """
    Download media file to a specified folder.
    Returns the media_filename (the original name Anki uses) on success, or None on failure.
    """
    os.makedirs(media_folder, exist_ok=True)
    
    print(f"DEBUG: Attempting to retrieve media file from AnkiConnect: '{media_filename}'")
    media_data_base64 = invoke("retrieveMediaFile", {"filename": media_filename})
    
    if media_data_base64 is None:
        print(f"ERROR: retrieveMediaFile for '{media_filename}' returned None. This usually means the file does not exist in Anki's media collection with this exact filename, or there was an AnkiConnect issue.")
        return None
    
    # AnkiConnect might return an empty string for non-existent files sometimes, instead of None.
    if not media_data_base64:
        print(f"WARNING: retrieveMediaFile for '{media_filename}' returned empty data. File might be empty or non-existent in Anki's media collection.")
        return None

    try:
        binary_data = base64.b64decode(media_data_base64)
    except Exception as e:
        print(f"ERROR: Could not base64 decode data for '{media_filename}': {e}. Data might be corrupt or not base64.")
        # Optionally, try to determine file type to ensure it's not a text file being mistaken
        # if imghdr.what(None, binary_data) is None and mimetypes.guess_type(media_filename)[0] is None:
        #     print(f"DEBUG: Failed base64 decode. Sample of raw data (first 50 bytes): {media_data_base64[:50]}")
        return None

    media_path = os.path.join(media_folder, media_filename)
    
    try:
        with open(media_path, "wb") as media_file:
            media_file.write(binary_data)
        print(f"INFO: Successfully downloaded and saved '{media_filename}' to '{media_path}'")
        return media_filename # Return the filename that was used to save
    except IOError as e:
        print(f"ERROR: Could not save media file '{media_filename}' to '{media_path}': {e}. Check folder permissions.")
        return None
    except Exception as e:
        print(f"ERROR: An unexpected error occurred while saving '{media_filename}': {e}")
        return None
    
def export_anki_data_to_json(deck_name=None, tag=None):
    """
    Export Anki cards' raw field data and associated media into a structured JSON file
    and a 'media' subfolder for re-importing.
    """
    card_ids = get_cards(deck_name, tag)
    if not card_ids:
        print(f"No cards found for deck '{deck_name}' or tag '{tag}'. Exiting export.")
        return

    # A note can have multiple cards. We want unique notes to avoid duplicate processing.
    note_ids_raw = invoke("cardsToNotes", {"cards": card_ids})
    if not note_ids_raw:
        print("No notes found for the retrieved cards. Exiting export.")
        return
    
    unique_note_ids = list(set(note_ids_raw)) 

    # Determine output folder name based on deck/tag
    base_folder_name = f"export_{deck_name if deck_name else tag}".replace("::", "_").replace(" ", "_").strip('_')
    if not base_folder_name: # Fallback if deck/tag name is empty or results in empty string
        base_folder_name = "anki_export"
        
    output_base_dir = os.path.join(os.getcwd(), base_folder_name)
    media_folder = os.path.join(output_base_dir, "media")
    os.makedirs(media_folder, exist_ok=True)
    print(f"INFO: Exporting to directory: '{output_base_dir}'")
    print(f"INFO: Media files will be saved in: '{media_folder}'")

    json_output_path = os.path.join(output_base_dir, "notes_data.json")
    exported_notes_data = []
    
    # Keep track of downloaded media (by its Anki filename) to avoid redundant downloads
    downloaded_media_filenames = set()

    print(f"\n--- Starting export of {len(unique_note_ids)} unique notes ---")

    for i, note_id in enumerate(unique_note_ids):
        print(f"\n--- Processing note {i + 1}/{len(unique_note_ids)} (Note ID: {note_id}) ---")
        note_data = get_note_info(note_id)
        if not note_data:
            print(f"WARNING: Could not retrieve full info for note ID {note_id}. Skipping this note.")
            continue

        model_name = note_data.get("modelName")
        if not model_name:
            print(f"WARNING: Note {note_id} has no modelName associated. Skipping this note.")
            continue

        fields_dict = {}
        # AnkiConnect 'notesInfo' returns fields as a dictionary like {"Field Name": {"value": "...", "order": ...}}
        for field_display_name, field_info in note_data.get("fields", {}).items():
            # field_display_name is like "Front", "Back", "MyCustomField"
            field_value = field_info.get("value", "")
            if field_display_name: # Ensure the field name is not empty
                fields_dict[field_display_name] = field_value
        
        if not fields_dict:
            print(f"WARNING: Note {note_id} has no accessible fields. Skipping this note.")
            continue

        print(f"DEBUG: Note {note_id} has fields: {list(fields_dict.keys())}")
        
        # Iterate through each field's content to find and download media
        for field_name, field_value in fields_dict.items():
            # Only process if the field has actual string content
            if isinstance(field_value, str) and field_value.strip(): 
                print(f"DEBUG: Checking field '{field_name}' for media references...")
                media_files_in_field = extract_media_filenames_from_html(field_value)
                for media_filename in media_files_in_field:
                    if media_filename: # Ensure filename is not empty
                        if media_filename not in downloaded_media_filenames:
                            # Attempt to download the media file
                            print(f"INFO: Media file '{media_filename}' found in field '{field_name}'. Attempting download...")
                            saved_filename = download_media(media_filename, media_folder)
                            if saved_filename:
                                downloaded_media_filenames.add(saved_filename)
                            else:
                                print(f"WARNING: Failed to download media '{media_filename}' (from field '{field_name}') for note {note_id}. Check previous ERROR messages.")
                        else:
                            print(f"DEBUG: Media file '{media_filename}' already downloaded. Skipping re-download for note {note_id}.")
                    else:
                        print(f"DEBUG: An empty media filename was detected in field '{field_name}' for note {note_id}. Skipping.")
        
        exported_notes_data.append({
            "noteId": note_id,
            "modelName": model_name,
            "tags": note_data.get("tags", []),
            "fields": fields_dict # All fields by name, HTML content as is (no path changes needed here)
        })
        if (i + 1) % 50 == 0: # Print progress every 50 notes
            print(f"--- Processed {i + 1}/{len(unique_note_ids)} notes ---")

    # Write the collected note data to a JSON file
    with open(json_output_path, "w", encoding="utf-8") as f:
        json.dump(exported_notes_data, f, ensure_ascii=False, indent=2)

    print(f"\n--- Export Summary ---")
    print(f"Total unique notes processed: {len(exported_notes_data)}")
    print(f"JSON data saved to: '{json_output_path}'")
    print(f"Media files saved to: '{media_folder}' ({len(downloaded_media_filenames)} unique files).")
    
    if len(downloaded_media_filenames) == 0 and len(exported_notes_data) > 0:
        print("WARNING: No media files were downloaded during the export. This could mean:")
        print("  1. Your Anki cards for the selected deck/tag do not contain any media (images/sounds).")
        print("  2. The media references in your cards are in an unusual format not captured by the script's extraction logic.")
        print("  3. AnkiConnect is not providing the media data correctly. Check Anki and AnkiConnect add-on status.")
        print("Please review the detailed 'DEBUG' and 'ERROR' output above to diagnose the issue.")
    elif len(exported_notes_data) == 0:
        print("INFO: No notes were exported. This is expected if no cards were found for the given deck/tag.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export Anki data to JSON for re-import")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-d", "--deck", help="Name of the deck to export (e.g., 'My Deck::Subdeck')")
    group.add_argument("-t", "--tag", help="Filter by tag hierarchy (e.g., 'tag1::subtag1::subsubtag1')")
    
    args = parser.parse_args()
    
    # Ensure Anki is running and AnkiConnect is installed before running this script!
    export_anki_data_to_json(args.deck, args.tag)