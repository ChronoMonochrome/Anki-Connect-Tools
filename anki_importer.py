# -*- coding: utf-8 -*-
import argparse
import json
import random
import os
import genanki
import logging
import colorlog
import re
import shutil # For copying media files
import hashlib # Import hashlib for consistent ID generation

# Configure logging
def setup_logging():
    """Set up the logging configuration."""
    log_colors = {
        "DEBUG": "cyan",
        "INFO": "green",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "red,bg_white",
    }

    colorlog_format = "%(log_color)s%(levelname)-8s%(reset)s " "%(blue)s%(message)s"

    colorlog.basicConfig(
        level=logging.INFO, # Set to INFO for less verbose output by default
        format=colorlog_format, 
        handlers=[colorlog.StreamHandler()]
    )

setup_logging()
logger = logging.getLogger()

# --- EXTRACTED ANKI CARD TEMPLATES ---
# This dictionary holds the front, back, and styling for each note model.
# You can update this if you extract more note types or if templates change.
ANKI_CARD_TEMPLATES = {
    "JlabNote-JlabConverted-1": {
        "Front Template": "{{Audio}}<br>\n{{Image}}<br><br>\n{{furigana:Jlab-ListeningFront}}<br><br>\n<div class=kanjipopup>{{furigana:Other-Front}}</div>\n<p style=\"font-size:50%;color=#C4C4C4\">Наведите/нажмите на кандзи, чтобы показать <a href=\"https://www.japanese-like-a-breeze.com/dont-learn-kanji-readings\">фуригану</a><p>{{RemarksFront}}\n<p style=\"font-size:70%;color:grey\">Источник этой карточки: {{Source}}<br>Измените текст с помощью <a href = \"https://www.japanese-like-a-breeze.com/addon-manual/\">дополнения Jlab (2110939339)</a> или <a href = \"https://www.japanese-like-a-breeze.com/course-without-addon/\">без дополнения</a>.</p>\n<p style=\"font-size:70%; color:grey\">Версия вашей колоды: <strong>{{Version}}</strong><br> Проверьте обновления <a href = \"https://www.japanese-like-a-breeze.com/guide-for-beginners/\">здесь.</a></p>\n<p style=\"font-size:70%; color:grey\">Вы можете поддержать Jlab на <a href=\"https://www.patreon.com/jlabjapanese/\">Patreon</a> - спасибо!</p><br>",
        "Back Template": "<div style=\"text-align: left;\">{{RemarksBack}}<br>\n{{Jlab-Remarks}}<br>\nСсылки:<br>\n{{References}}<br>\n{{Other-Back}}<br>\n<p style=\"font-size:70%;color:grey\">Что-то неясно? Задайте вопрос, связанный с этой карточкой, используя эту {{QuestionLink}}.</p>\n<p style=\"font-size:70%; color:grey\">Вы можете поддержать Jlab на <a href=\"https://www.patreon.com/jlabjapanese/\">Patreon</a> - спасибо!</p></div>",
        "Styling": ".card {\n font-family: arial;\n font-size: 20px;\n max-width: 800px;\n text-align: center;\n margin-left: auto;\n margin-right: auto;\n}\n.kanjipopup {\n font-family: arial;\n font-size: 20px;\n text-align: center;\n}\n.kanjipopup ruby rt { visibility: hidden; }\n.kanjipopup ruby:active rt { visibility: visible; }\n.kanjipopup ruby:hover rt { visibility: visible; }"
    },
    "InfoNote": {
        "Front Template": "{{Image}}<br>{{Text}}",
        "Back Template": "{{FrontSide}}",
        "Styling": ".card {\n font-family: arial;\n font-size: 20px;\n max-width: 800px;\n text-align: left;\n margin-left: auto;\n margin-right: auto;\n color: black;\n background-color: white;\n}"
    }
}
# --- END EXTRACTED ANKI CARD TEMPLATES ---


# Helper function to generate a consistent integer ID from a string
def generate_id_from_string(text_string):
    """Generates a consistent 32-bit integer ID from a string."""
    # Use SHA1 hash to get a consistent byte string
    hash_object = hashlib.sha1(text_string.encode('utf-8'))
    hex_dig = hash_object.hexdigest()
    # Take the first 8 characters (32 bits) of the hash and convert to int
    return int(hex_dig[:8], 16) % (1 << 31) # Ensure positive and within typical genanki ID range

def import_json_to_anki_deck(json_file_path, output_apkg_name="reimported_deck.apkg", media_folder="media"):
    """
    Imports notes from a JSON file (exported by anki_exporter.py) into an Anki deck.
    """
    logger.info(f"Loading notes from: {json_file_path}")
    try:
        with open(json_file_path, "r", encoding="utf-8") as f:
            notes_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Error: JSON file not found at {json_file_path}")
        return
    except json.JSONDecodeError:
        logger.error(f"Error: Invalid JSON format in {json_file_path}")
        return

    if not notes_data:
        logger.info("No notes found in the JSON file. Exiting.")
        return

    # Dynamically determine the deck name from the source folder name
    # e.g., if json_file_path is 'export_MyDeck/notes_data.json', deck_name becomes 'MyDeck'
    source_folder_name = os.path.basename(os.path.dirname(json_file_path))
    deck_name_from_folder = source_folder_name.replace("export_", "").replace("_", " ").strip()
    if not deck_name_from_folder:
        deck_name_from_folder = "Reimported Anki Deck"

    # Generate a consistent deck ID based on the deck name
    deck_id = generate_id_from_string(deck_name_from_folder)

    deck = genanki.Deck(
        deck_id, # Use the generated consistent ID
        deck_name_from_folder
    )

    models = {} # Cache models to avoid recreating them for each note of the same type
    media_files_to_package = set() # Collect all media files to be included in the .apkg

    logger.info(f"Processing {len(notes_data)} notes...")

    for note_info in notes_data:
        note_id = note_info.get("noteId")
        model_name = note_info.get("modelName")
        tags = note_info.get("tags", [])
        fields_dict = note_info.get("fields", {})

        if not model_name:
            logger.warning(f"Skipping note {note_id} due to missing modelName.")
            continue

        if model_name not in models:
            # Dynamically create the Genanki Model based on the actual field names
            field_names = list(fields_dict.keys())
            if not field_names:
                logger.warning(f"Model '{model_name}' for note {note_id} has no fields. Skipping.")
                continue

            # Generate model ID based on hash of model name and field names for consistency
            # Concatenate model name and sorted field names for a stable hash input
            model_hash_input = model_name + ",".join(sorted(field_names))
            model_id = generate_id_from_string(model_hash_input) # Use our custom ID generation

            # --- START: CUSTOM TEMPLATE INTEGRATION ---
            qfmt = ANKI_CARD_TEMPLATES.get(model_name, {}).get("Front Template")
            afmt = ANKI_CARD_TEMPLATES.get(model_name, {}).get("Back Template")
            css = ANKI_CARD_TEMPLATES.get(model_name, {}).get("Styling")

            if not qfmt or not afmt or not css:
                logger.warning(f"Warning: Custom templates not found for model '{model_name}'. Using generic templates. Card display may be incorrect.")
                # Fallback to generic templates if custom ones aren't found
                qfmt = "<br>".join([f"{{{{{name}}}}}" for name in field_names])
                afmt = f'{{{{FrontSide}}}}<hr id="answer">{"<br>".join([f"{{{{{name}}}}}" for name in field_names])}'
                css = """.card { font-family: arial; font-size: 20px; text-align: center; color: black; background-color: white; }"""
            # --- END: CUSTOM TEMPLATE INTEGRATION ---
            
            model = genanki.Model(
                model_id,
                model_name,
                fields=[{"name": name} for name in field_names],
                templates=[
                    {
                        "name": "Card 1", # Assuming all models have a single card type named "Card 1"
                        "qfmt": qfmt,
                        "afmt": afmt,
                    },
                ],
                css=css
            )
            models[model_name] = model
            logger.info(f"Created Anki Model: '{model_name}' (ID: {model_id}) with fields: {', '.join(field_names)}")
        else:
            model = models[model_name]
            
        # Prepare fields for genanki.Note
        # Ensure the order of fields matches the model's field order
        field_values_ordered = [fields_dict.get(field["name"], "") for field in model.fields]

        note = genanki.Note(
            model=model,
            fields=field_values_ordered,
            tags=tags,
            guid=genanki.guid_for(str(note_id)) # Use original note ID for GUID for consistency
        )
        deck.add_note(note)

        # Collect media files associated with this note's fields
        for field_content in field_values_ordered:
            if isinstance(field_content, str):
                # Anki media are typically just filenames directly embedded in HTML
                # e.g., <img src="image.png"> or [sound:audio.mp3]
                # We need to find these filenames and add them to the package.
                # Updated regex to correctly capture filenames
                media_matches = re.findall(r'(?:src=["\']|\[sound:)([^"\'\]]+)', field_content, re.IGNORECASE)
                for media_filename_with_path in media_matches:
                    # Use os.path.basename to get just the filename without any path prefixes
                    media_filename = os.path.basename(media_filename_with_path)
                    
                    # Construct full path to original downloaded media
                    # media_folder is already joined with json_dir outside this function
                    original_media_path = os.path.join(media_folder, media_filename)
                    if os.path.exists(original_media_path):
                        media_files_to_package.add(original_media_path)
                    else:
                        logger.warning(f"Media file not found: '{original_media_path}' (referenced as '{media_filename_with_path}') for note {note_id}. It will not be included in the .apkg.")

    logger.info(f"Creating Anki package '{output_apkg_name}' with {len(media_files_to_package)} media files...")
    package = genanki.Package(deck)
    
    # Add all unique media files to the package
    for media_path in media_files_to_package:
        package.media_files.append(media_path)

    try:
        package.write_to_file(output_apkg_name)
        logger.info(f"Successfully created Anki deck: {output_apkg_name}")
    except Exception as e:
        logger.error(f"Error writing Anki deck to file: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import JSON data into an Anki deck")
    parser.add_argument(
        "json_file",
        type=str,
        help="Path to the JSON file containing exported Anki note data (e.g., export_MyDeck/notes_data.json)"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="reimported_deck.apkg",
        help="Name of the output Anki deck file (e.g., my_reimported_deck.apkg)"
    )
    parser.add_argument(
        "--media_folder",
        "-m",
        type=str,
        default="media", # Assumes media folder is 'media' relative to the JSON file
        help="Name of the folder containing media files relative to the JSON file's directory."
    )
    
    args = parser.parse_args()

    # Determine the full path to the media folder based on the JSON file's directory
    json_dir = os.path.dirname(args.json_file)
    actual_media_folder = os.path.join(json_dir, args.media_folder)

    import_json_to_anki_deck(args.json_file, args.output, actual_media_folder)