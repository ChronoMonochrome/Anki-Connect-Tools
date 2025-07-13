import json
import argparse
import os
import logging
import colorlog

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
        level=logging.INFO,
        format=colorlog_format,
        handlers=[colorlog.StreamHandler()]
    )
    return logging.getLogger()

logger = setup_logging()

def reorder_json_notes(reference_json_path, target_json_path, output_json_path):
    """
    Reorders notes in a target JSON file based on the order of notes in a reference JSON file.
    Notes are matched by 'noteId'.

    Args:
        reference_json_path (str): Path to the JSON file with the desired order (e.g., original notes_data.json).
        target_json_path (str): Path to the JSON file containing notes to be reordered (e.g., translated_notes_data.json).
        output_json_path (str): Path where the reordered JSON file will be saved.
    """
    logger.info(f"Loading reference notes from: '{reference_json_path}'")
    try:
        with open(reference_json_path, 'r', encoding='utf-8') as f:
            reference_notes = json.load(f)
    except FileNotFoundError:
        logger.critical(f"Error: Reference JSON file not found at '{reference_json_path}'")
        return
    except json.JSONDecodeError:
        logger.critical(f"Error: Invalid JSON format in '{reference_json_path}'")
        return

    if not isinstance(reference_notes, list):
        logger.critical(f"Error: Reference JSON file '{reference_json_path}' does not contain a list of notes.")
        return

    logger.info(f"Loading target notes from: '{target_json_path}'")
    try:
        with open(target_json_path, 'r', encoding='utf-8') as f:
            target_notes = json.load(f)
    except FileNotFoundError:
        logger.critical(f"Error: Target JSON file not found at '{target_json_path}'")
        return
    except json.JSONDecodeError:
        logger.critical(f"Error: Invalid JSON format in '{target_json_path}'")
        return

    if not isinstance(target_notes, list):
        logger.critical(f"Error: Target JSON file '{target_json_path}' does not contain a list of notes.")
        return

    # Create a dictionary for quick lookup of target notes by noteId
    target_notes_map = {note.get("noteId"): note for note in target_notes if note.get("noteId") is not None}
    
    reordered_notes = []
    missing_notes_count = 0

    logger.info(f"Attempting to reorder {len(target_notes)} notes based on {len(reference_notes)} reference notes...")

    for i, ref_note in enumerate(reference_notes):
        ref_note_id = ref_note.get("noteId")
        if ref_note_id is None:
            logger.warning(f"Reference note at index {i} has no 'noteId'. Skipping for ordering.")
            continue

        if ref_note_id in target_notes_map:
            reordered_notes.append(target_notes_map[ref_note_id])
        else:
            logger.warning(f"Note with ID '{ref_note_id}' from reference file not found in target file. Skipping this note.")
            missing_notes_count += 1
            # Optionally, you could append the original reference note here if desired
            # reordered_notes.append(ref_note)

    if missing_notes_count > 0:
        logger.warning(f"Completed reordering, but {missing_notes_count} notes from the reference file were not found in the target file.")
    
    if len(reordered_notes) != len(target_notes):
        logger.warning(f"Reordered notes count ({len(reordered_notes)}) does not match original target notes count ({len(target_notes)}). This might happen if some target notes did not have a matching reference note ID, or if reference notes were missing from target.")

    logger.info(f"Saving reordered notes to: '{output_json_path}'")
    try:
        os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(reordered_notes, f, ensure_ascii=False, indent=2)
        logger.info(f"Successfully reordered and saved {len(reordered_notes)} notes.")
    except Exception as e:
        logger.critical(f"Error saving reordered notes to '{output_json_path}': {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Reorder notes in a JSON file based on the order of another reference JSON file (matching by 'noteId')."
    )
    parser.add_argument(
        "reference_json",
        type=str,
        help="Path to the JSON file with the desired note order (e.g., your original notes_data.json)."
    )
    parser.add_argument(
        "target_json",
        type=str,
        help="Path to the JSON file containing notes to be reordered (e.g., your translated_notes_data.json)."
    )
    parser.add_argument(
        "--output-name",
        "-o",
        type=str,
        default="reordered_notes_data.json",
        help="Name of the output JSON file. Defaults to 'reordered_notes_data.json'."
    )

    args = parser.parse_args()

    # Determine the output path in the same directory as the target JSON
    target_dir = os.path.dirname(os.path.abspath(args.target_json))
    output_path = os.path.join(target_dir, args.output_name)

    reorder_json_notes(args.reference_json, args.target_json, output_path)

if __name__ == "__main__":
    main()