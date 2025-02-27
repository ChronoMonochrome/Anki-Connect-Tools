import json
import requests
import argparse
import os
import re
import base64
import imghdr

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
    response_json = response.json()
    return response_json.get("result")

def get_cards(deck_name=None, tag=None):
    """Retrieve all card IDs from a specified deck or by tag across all decks."""
    if tag:
        query = f'tag:"{tag}"'  # Search for cards by tag across all decks
    elif deck_name:
        query = f'deck:"{deck_name}"'
    else:
        raise ValueError("Either deck name or tag must be provided.")
    
    card_ids = invoke("findCards", {"query": query})
    return card_ids if card_ids else []

def get_card_info(card_id):
    """Retrieve card information including fields and templates."""
    card_info = invoke("cardsInfo", {"cards": [card_id]})
    return card_info[0] if card_info and isinstance(card_info, list) else None

def extract_tags(card_data):
    """Extract tags from the card data."""
    tags = card_data.get("tags", [])
    return tags if tags else ["-"]  # Ensures tags are displayed properly

def extract_media_filenames(html_content):
    """Extract media filenames from HTML content."""
    return re.findall(r'src="([^"]+)"', html_content)

def download_media(media_filename, media_folder):
    """Download media file to a specified folder and return the correct relative path."""
    os.makedirs(media_folder, exist_ok=True)
    media_data = invoke("retrieveMediaFile", {"filename": media_filename})
    if media_data:
        try:
            binary_data = base64.b64decode(media_data, validate=True)
            image_format = imghdr.what(None, binary_data)
            if image_format is None:
                return None
            media_path = os.path.join(media_folder, media_filename)
            with open(media_path, "wb") as media_file:
                media_file.write(binary_data)
            return f"media/{media_filename}"
        except Exception:
            return None
    return None
    
import html  # To escape special HTML characters safely

def export_to_html(deck_name=None, tag=None):
    """Export cards to an HTML file, supporting deck or tag-based retrieval."""
    card_ids = get_cards(deck_name, tag)
    if not card_ids:
        print(f"No cards found for deck '{deck_name}' or tag '{tag}'.")
        return

    base_folder = f"export_{deck_name if deck_name else tag}".replace("::", "_")
    media_folder = os.path.join(base_folder, "media")
    css_folder = os.path.join(base_folder, "css")
    os.makedirs(media_folder, exist_ok=True)
    os.makedirs(css_folder, exist_ok=True)

    output_file = os.path.join(base_folder, "index.html")
    css_file = os.path.join(css_folder, "styles.css")

    # Writing CSS
    with open(css_file, "w", encoding="utf-8") as f:
        f.write("""
        body {
            font-family: Arial, sans-serif;
            background: #121212;
            color: #ffffff;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px;
        }
        .card {
            border: 1px solid #444;
            padding: 20px;
            margin: 10px;
            border-radius: 8px;
            background: #1e1e1e;
            width: 60%;
            text-align: center;
            position: relative;
        }
        .card-id {
            font-size: 12px;
            color: #aaa;
            text-decoration: none;
            position: absolute;
            top: 5px;
            right: 10px;
        }
        .tags {
            font-size: 12px;
            color: #aaa;
            margin-top: 10px;
            border-top: 1px solid #444;
            padding-top: 5px;
        }
        img {
            max-width: 100%;
            display: block;
            margin: 10px auto;
        }
        .extra-info-button {
            background-color: #333;
            color: #fff;
            border: none;
            padding: 5px 10px;
            cursor: pointer;
            margin-top: 5px;
            border-radius: 5px;
            text-decoration: none;
            display: inline-block;
        }
        .extra-info-button:hover {
            background-color: #555;
        }
        """)

    # Writing HTML file
    with open(output_file, "w", encoding="utf-8") as html_file:
        html_file.write("<html><head><title>Exported Cards</title>")
        html_file.write("<link rel='stylesheet' type='text/css' href='css/styles.css'>")
        html_file.write("<script>")
        html_file.write("""
        function openExtraInfo(content, isImage) {
            let newWindow = window.open("", "_blank", "width=600,height=400");
            newWindow.document.write("<html><head><title>Extra Info</title></head><body>");
            if (isImage) {
                newWindow.document.write("<img src='" + content + "' style='max-width:100%;'>");
            } else {
                newWindow.document.write("<p style='font-size:16px; white-space:pre-wrap;'>" + content + "</p>");
            }
            newWindow.document.write("</body></html>");
            newWindow.document.close();
        }
        """)
        html_file.write("</script>")
        html_file.write("</head><body>")

        for card_id in card_ids:
            card_data = get_card_info(card_id)
            if not card_data:
                continue

            answer = card_data.get("answer", "")
            fields = card_data.get("fields", {})
            tags = extract_tags(card_data)

            # Extract media files
            media_files = extract_media_filenames(answer)
            for media_file in media_files:
                media_path = download_media(media_file, media_folder)
                if media_path:
                    answer = answer.replace(media_file, media_path)

            # Remove old cloze-related buttons from answer
            answer = re.sub(r'<button .*?>.*?</button>', '', answer)

            # Write card content
            html_file.write(f"<div class='card'>")
            html_file.write(f"<a href='#{card_id}' class='card-id' id='{card_id}'>Card ID: {card_id}</a>")
            html_file.write(f"<p>{answer}</p>")

            # Process extra hidden fields (not already displayed in main card layout)
            for field_name, field_content in fields.items():
                field_value = field_content.get("value", "").strip()
                
                # Skip empty fields, already displayed content, or card front text
                if not field_value or field_value in answer or field_name.lower() in ["front", "question"]:
                    continue  

                hidden_media_files = extract_media_filenames(field_value)
                if hidden_media_files:  # If media files exist in the field
                    for media_file in hidden_media_files:
                        media_path = download_media(media_file, media_folder)
                        if media_path:
                            html_file.write(f"<button class='extra-info-button' onclick=\"openExtraInfo('{media_path}', true)\">{html.escape(field_name)}</button>")
                else:  # If it's just text, escape curly braces and other special characters
                    safe_text_content = html.escape(field_value).replace("{", "&#123;").replace("}", "&#125;")
                    html_file.write(f"<button class='extra-info-button' onclick=\"openExtraInfo('{safe_text_content}', false)\">{html.escape(field_name)}</button>")

            # Display tags at the bottom
            html_file.write(f"<p class='tags'>Tags: {', '.join(tags)}</p>")
            html_file.write("</div>")

        html_file.write("</body></html>")

    print(f"Cards exported to {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export Anki deck to HTML")
    parser.add_argument("-d", action="store_true", help="Enable deck export mode")
    parser.add_argument("-t", "--tag", help="Filter by tag hierarchy (e.g., tag1::subtag1::subsubtag1)")
    parser.add_argument("deck", nargs="?", help="Name of the deck to export (optional if using -t)")
    args = parser.parse_args()
    
    export_to_html(args.deck, args.tag)

