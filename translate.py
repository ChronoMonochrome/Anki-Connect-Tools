import argparse
import json
import os
import time
import re
import requests
from bs4 import BeautifulSoup
from bs4 import element
import colorlog
import logging

try:
    import deepl
except ImportError:
    print("Error: The 'deepl-cli' Python package is not installed.")
    print("Please install it using: pip install deepl-cli beautifulsoup4 colorlog requests")
    exit(1)

# --- Configuration ---
DEFAULT_RETRY_COUNT = 20
RETRY_DELAY_SECONDS = 5
MAX_TEXT_CHUNK_LENGTH = 4500 # DeepL API has limits, keep chunks below 5000 characters for safety

# Fields that should NEVER be translated (e.g., IDs, internal data, media tags)
# This includes 'Other-Front', 'Other-Back', and any field starting with 'Jlab-' as per your request.
FIELDS_TO_SKIP_TRANSLATION = {
    "Source", "Version", "Sequence", "Audio", "Image", "QuestionLink", "References",
    "Other-Front", "Other-Back", "Jlab-Kanji", "Jlab-KanjiSpaced",
    "Jlab-Hiragana", "Jlab-KanjiCloze", "Jlab-Lemma", "Jlab-HiraganaCloze",
    "Jlab-Translation", "Jlab-DictionaryLookup", "Jlab-Metadata", "Jlab-Remarks",
    "Jlab-ListeningFront", "Jlab-ListeningBack", "Jlab-ClozeFront", "Jlab-ClozeBack",
}

# Fields that ALWAYS contain HTML (or might contain it) and need to be parsed
# 'RemarksFront' and 'RemarksBack' are now explicitly handled as HTML.
FIELDS_ALWAYS_HTML_TRANSLATION = {
    "RemarksFront",
    "RemarksBack"
}

# Fields that contain HTML content and should be parsed for translation, but only for specific model names
HTML_FIELDS_BY_MODEL_FOR_TRANSLATION = {
    "InfoNote": ["Text"] # Only 'Text' field for 'InfoNote' model needs HTML parsing based on your sample
}

# --- Logging Setup ---
def setup_logging():
    """Set up the logging configuration."""
    log_colors = {
        "DEBUG": "cyan",
        "INFO": "green",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "red,bg_white",
    }
    colorlog_format = "%(log_color)s%(levelname)-8s%(reset)s %(blue)s%(message)s"
    colorlog.basicConfig(
        level=logging.DEBUG, # Keep this at INFO for general use, change to DEBUG for detailed debugging
        format=colorlog_format,
        handlers=[colorlog.StreamHandler()]
    )
    return logging.getLogger()

logger = setup_logging()

# --- Translator Class ---
class DeepLTranslator:
    def __init__(self, target_lang, source_lang=None, proxy=None):
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.proxy = proxy
        self.dl = self._initialize_deepl()
        logger.info(f"Initialized DeepL Translator: Source='{source_lang if source_lang else 'auto'}', Target='{target_lang}'")
        if proxy:
            logger.info(f"Using proxy: {proxy}")

    def _initialize_deepl(self):
        try:
            proxy_config = {"server": self.proxy} if self.proxy else None
            return deepl.DeepLCLI("en", "ru", proxy={ "server": "http://127.0.0.1:18080" })
        except Exception as e:
            logger.critical(f"Failed to initialize DeepL CLI: {e}")
            logger.critical("Please check your DeepL CLI installation, API key (if required by your DeepL setup), and proxy settings.")
            exit(1)

    def translate(self, text, retries=DEFAULT_RETRY_COUNT, delay=RETRY_DELAY_SECONDS):
        if not text or not text.strip():
            return text

        if len(text) > MAX_TEXT_CHUNK_LENGTH:
            logger.warning(f"Text too long ({len(text)} chars) for DeepL. Attempting simple chunking. This might break context.")
            sentences = re.split(r'(?<=[.?!])\s+|\n+', text)
            
            chunks = []
            current_chunk = []
            current_length = 0

            for sentence in sentences:
                if current_length + len(sentence) + (1 if current_chunk else 0) > MAX_TEXT_CHUNK_LENGTH:
                    if current_chunk:
                        chunks.append(" ".join(current_chunk).strip())
                    current_chunk = [sentence]
                    current_length = len(sentence)
                else:
                    current_chunk.append(sentence)
                    current_length += len(sentence) + (1 if current_chunk else 0)
            
            if current_chunk:
                chunks.append(" ".join(current_chunk).strip())

            translated_chunks = []
            for i, chunk in enumerate(chunks):
                if not chunk.strip():
                    continue
                logger.info(f"Translating chunk {i+1}/{len(chunks)}...")
                translated_chunks.append(self._translate_single_chunk(chunk, retries, delay))
            return "".join(translated_chunks)
        else:
            return self._translate_single_chunk(text, retries, delay)

    def _translate_single_chunk(self, text_chunk, retries, delay):
        logger.info(f"translating chunk: {text_chunk}")
        for attempt in range(retries):
            try:
                # dl.translate returns a TranslationResult object, not just a string
                # We need to access .text attribute
                result = self.dl.translate(text_chunk)
                if result:
                    logger.info(f"translating chunk: result: {result}")
                    return result
                else:
                    logger.error(f"DeepLCLI translate result is empty for chunk: '{text_chunk[:50]}...'. Returning original content for this chunk.")
                    return text_chunk
            except requests.exceptions.RequestException as e:
                logger.warning(f"Network/Proxy error (attempt {attempt+1}/{retries}): {e}. Retrying in {delay}s...")
                time.sleep(delay)
            except Exception as e:
                logger.error(f"An unexpected error occurred during translation (attempt {attempt+1}/{retries}): {e}. Retrying in {delay}s...")
                time.sleep(delay)
        logger.error(f"Failed to translate text after {retries} attempts: '{text_chunk[:50]}...'")
        return text_chunk # Return original text on failure if all retries exhausted for other errors

# --- HTML Translation Logic ---
def translate_html_field(html_content, translator):
    """
    Parses HTML content, translates visible text nodes, and reassembles the HTML.
    This function is now used for any field that is identified as potentially containing HTML.
    """
    if not html_content or not html_content.strip():
        return html_content

    soup = BeautifulSoup(html_content, 'html.parser')

    # Find all text nodes that are not within script, style, or link tags
    for text_node in soup.find_all(string=True):
        # Check if the text node is visible (not in script, style, comment, etc.)
        # IMPORTANT FIX: Removed '[document]' from the exclusion list, and
        # directly check isinstance(..., Comment) for robustness.
        if text_node.parent.name not in ['script', 'style', 'head', 'title', 'meta'] \
           and not isinstance(text_node, element.Comment) \
           and text_node.strip():
            original_text = str(text_node).strip()
            if original_text:
                logger.debug(f"HTML field parsing: Found text node '{original_text[:100]}' (len: {len(original_text)}) for translation.")
                translated_text = translator.translate(original_text)
                text_node.replace_with(translated_text)
    
    # Return the modified HTML as a string
    return str(soup)

# --- Note Processing ---
def process_note(note_data, output_dir, translator, force_translate):
    """
    Processes a single note, translates specified fields, and saves it.
    """
    note_id = note_data.get("noteId")
    model_name = note_data.get("modelName")
    
    output_filepath = os.path.join(output_dir, f"note_{note_id}.json")

    if os.path.exists(output_filepath) and not force_translate:
        logger.info(f"Skipping note {note_id}: Translated file already exists at '{output_filepath}'. Use --force to re-translate.")
        return False

    logger.info(f"Processing note {note_id} (Model: {model_name})...")
    
    translated_fields = {}
    for field_name, field_value in note_data.get("fields", {}).items():
        # 1. Check if the field should be skipped entirely
        if field_name in FIELDS_TO_SKIP_TRANSLATION or field_name.startswith("Jlab-"):
            translated_fields[field_name] = field_value
            logger.info(f"Skipping translation for field '{field_name}' in note {note_id} (excluded or Jlab-*).")
            continue

        # 2. Check if the field is always treated as HTML for translation (e.g., RemarksBack)
        if field_name in FIELDS_ALWAYS_HTML_TRANSLATION:
            if field_value and field_value.strip():
                logger.info(f"Translating HTML-aware field '{field_name}' for note {note_id} (always HTML handled)...")
                translated_fields[field_name] = translate_html_field(field_value, translator)
            else:
                translated_fields[field_name] = field_value
            continue

        # 3. Check if the field is HTML-treated based on the model name (e.g., Text for InfoNote)
        if model_name in HTML_FIELDS_BY_MODEL_FOR_TRANSLATION and field_name in HTML_FIELDS_BY_MODEL_FOR_TRANSLATION[model_name]:
            if field_value and field_value.strip():
                logger.info(f"Translating HTML field '{field_name}' for note {note_id} (Model: {model_name})...")
                translated_fields[field_name] = translate_html_field(field_value, translator)
                logger.info(f"translated_fields[field_name] = {translated_fields[field_name] }")
            else:
                translated_fields[field_name] = field_value
            continue
        
        # 4. Handle other specific plain text fields (like 'Source' if it's confirmed to be plain text)
        if field_name == "Source": # 'Source' appears to be plain text based on your sample
            if field_value and field_value.strip():
                logger.info(f"Translating plain text field '{field_name}' for note {note_id}...")
                translated_fields[field_name] = translator.translate(field_value)
            else:
                translated_fields[field_name] = field_value
            continue

        # 5. For any other field not explicitly handled above, just copy its content
        translated_fields[field_name] = field_value
        logger.info(f"Copying field '{field_name}' for note {note_id} without translation (no specific rule matched).")

    note_data["fields"] = translated_fields
    
    # Save the individual translated note
    try:
        with open(output_filepath, "w", encoding="utf-8") as f:
            json.dump(note_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved translated note {note_id} to '{output_filepath}'")
    except Exception as e:
        logger.error(f"Failed to save translated note {note_id} to '{output_filepath}': {e}")
        return False
    return True

# --- Assembly Logic ---
def assemble_translated_notes(input_dir, output_json_path):
    """
    Assembles all individual translated note JSON files into a single JSON file.
    """
    logger.info(f"Assembling translated notes from '{input_dir}' into '{output_json_path}'...")
    assembled_notes = []
    
    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)

    json_files = sorted([f for f in os.listdir(input_dir) if f.startswith("note_") and f.endswith(".json")])

    if not json_files:
        logger.warning(f"No individual note JSON files found in '{input_dir}' to assemble.")
        return

    for filename in json_files:
        filepath = os.path.join(input_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                note_data = json.load(f)
                assembled_notes.append(note_data)
        except Exception as e:
            logger.error(f"Error loading individual note file '{filepath}': {e}. Skipping this file.")
            continue
    
    try:
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(assembled_notes, f, ensure_ascii=False, indent=2)
        logger.info(f"Successfully assembled {len(assembled_notes)} notes into '{output_json_path}'")
    except Exception as e:
        logger.error(f"Failed to assemble notes into '{output_json_path}': {e}")

# --- Main Script Logic ---
def main():
    parser = argparse.ArgumentParser(
        description="Translate Anki deck JSON notes using DeepLCLI and save them incrementally."
    )
    parser.add_argument(
        "input_json",
        type=str,
        help="Path to the input JSON file containing exported Anki note data (e.g., export_Jlab's_beginner_course/notes_data.json)"
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default="translated_notes_output",
        help="Directory to save individual translated notes. Defaults to 'translated_notes_output' in the input JSON's directory."
    )
    parser.add_argument(
        "--target-lang",
        "-t",
        type=str,
        required=True,
        help="Target language for translation (e.g., 'en', 'ru', 'de')."
    )
    parser.add_argument(
        "--source-lang",
        "-s",
        type=str,
        default="ja",
        help="Source language for translation (e.g., 'ja'). Defaults to 'ja'. (Required by DeepLCLI)."
    )
    parser.add_argument(
        "--deepl-proxy",
        type=str,
        default=None,
        help="Proxy server for DeepLCLI (e.g., 'http://127.0.0.1:18080')."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-translation of notes even if translated files already exist."
    )
    parser.add_argument(
        "--note-id",
        type=int,
        help="Translate only a specific note by its ID (e.g., 1600424960000)."
    )
    parser.add_argument(
        "--assemble-only",
        action="store_true",
        help="Only assemble existing translated notes from --output-dir into a single JSON, skip translation phase."
    )
    parser.add_argument(
        "--output-filename",
        type=str,
        default="translated_notes_data.json",
        help="Name of the final assembled JSON file."
    )

    args = parser.parse_args()

    json_input_dir = os.path.dirname(os.path.abspath(args.input_json))
    actual_output_dir = os.path.join(json_input_dir, args.output_dir)
    os.makedirs(actual_output_dir, exist_ok=True)
    logger.info(f"Individual translated notes will be saved in: '{actual_output_dir}'")
    
    final_assembled_json_path = os.path.join(json_input_dir, args.output_filename)

    if args.assemble_only:
        logger.info("Assembly-only mode activated. Skipping translation.")
        assemble_translated_notes(actual_output_dir, final_assembled_json_path)
        return

    translator = DeepLTranslator(
        target_lang=args.target_lang,
        source_lang=args.source_lang,
        proxy=args.deepl_proxy
    )

    logger.info(f"Loading notes from: {args.input_json}")
    try:
        with open(args.input_json, "r", encoding="utf-8") as f:
            all_notes_data = json.load(f)
    except FileNotFoundError:
        logger.critical(f"Error: Input JSON file not found at {args.input_json}")
        return
    except json.JSONDecodeError:
        logger.critical(f"Error: Invalid JSON format in {args.input_json}")
        return

    if not all_notes_data:
        logger.info("No notes found in the input JSON file. Exiting.")
        return

    notes_to_process = []
    if args.note_id:
        found = False
        for note in all_notes_data:
            if note.get("noteId") == args.note_id:
                notes_to_process.append(note)
                found = True
                break
        if not found:
            logger.error(f"Note with ID {args.note_id} not found in the input JSON.")
            return
        logger.info(f"Processing only note with ID: {args.note_id}")
    else:
        notes_to_process = all_notes_data
        logger.info(f"Processing all {len(notes_to_process)} notes.")

    for i, note in enumerate(notes_to_process):
        logger.info(f"--- Starting Note {i+1}/{len(notes_to_process)} ---")
        process_note(note, actual_output_dir, translator, args.force)
        
    logger.info("\n--- Translation Phase Complete ---")
    
    assemble_translated_notes(actual_output_dir, final_assembled_json_path)
    logger.info("Translation process finished.")

if __name__ == "__main__":
    main()