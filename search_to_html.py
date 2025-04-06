import os
import re
import shutil
import argparse
import requests
import base64
import html
import imghdr
import webbrowser
import threading
from http.server import SimpleHTTPRequestHandler
from socketserver import TCPServer

EXPORT_DIR = "."

def anki_request(action, **params):
    response = requests.post("http://localhost:8765", json={
        "action": action,
        "version": 6,
        "params": params
    }).json()
    if response.get("error") is not None:
        raise Exception(f"AnkiConnect error: {response['error']}")
    return response["result"]

def find_cards_by_terms(terms):
    query_parts = []
    for term in terms:
        query_parts.append(f'"{term}"')
        query_parts.append(f'tag:*{term}*')
        query_parts.append(f'deck:*{term}*')
    query = " or ".join(query_parts)
    return anki_request("findCards", query=query)

def get_card_info(card_ids):
    return anki_request("cardsInfo", cards=card_ids)

def get_unique_tags(notes):
    tag_set = set()
    for note in notes:
        tag_set.update(note.get("tags", []))
    return sorted(tag_set)

def filter_cards_by_top_deck(cards, deck_name):
    if not deck_name:
        return cards
    return [card for card in cards if card["deckName"].split("::")[0] == deck_name]

def extract_media_filenames(html_content):
    return re.findall(r'src="([^"]+)"', html_content)

def download_media(media_filename, media_folder):
    os.makedirs(media_folder, exist_ok=True)
    media_data = anki_request("retrieveMediaFile", filename=media_filename)
    if media_data:
        try:
            binary_data = base64.b64decode(media_data, validate=True)
            if not imghdr.what(None, binary_data):
                return None
            media_path = os.path.join(media_folder, media_filename)
            with open(media_path, "wb") as media_file:
                media_file.write(binary_data)
            return f"media/{media_filename}"
        except Exception:
            return None
    return None

def make_handler():
    class CustomHandler(SimpleHTTPRequestHandler):
        def log_message(self, format, *args_inner):
            pass
    return CustomHandler

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--terms", required=True, help="Comma-separated list of search terms.")
    parser.add_argument("--deck", help="Optional deck name to filter by.")
    parser.add_argument("--cleanup", action="store_true", help="Delete export folder after server stops")
    parser.add_argument("--port", type=int, default=8080, help="Port for local server (default: 8080)")
    args = parser.parse_args()

    terms = [term.strip() for term in args.terms.split(",")]
    safe_name = "_".join(terms).lower().replace(" ", "_")
    output_path = os.path.abspath(os.path.join(EXPORT_DIR, safe_name))
    os.makedirs(output_path, exist_ok=True)

    print(f" Searching terms: {terms}")
    card_ids = find_cards_by_terms(terms)
    print(f" Found {len(card_ids)} matching cards")
    if not card_ids:
        return

    cards = get_card_info(card_ids)
    cards = filter_cards_by_top_deck(cards, args.deck)
    print(f" Filtered by deck: {len(cards)} cards in '{args.deck}'" if args.deck else f"📦 No deck filtering applied")

    note_ids = list({card["note"] for card in cards})
    notes = anki_request("notesInfo", notes=note_ids)

    unique_tags = get_unique_tags(notes)
    if unique_tags:
        print(f"  Unique tags in notes:")
        for tag in unique_tags:
            print(f"   - {tag}")
    else:
        print("  No tags found in matching notes.")

    media_folder = os.path.join(output_path, "media")
    css_folder = os.path.join(output_path, "css")
    os.makedirs(media_folder, exist_ok=True)
    os.makedirs(css_folder, exist_ok=True)

    with open(os.path.join(css_folder, "styles.css"), "w", encoding="utf-8") as f:
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

    html_file = os.path.join(output_path, "index.html")
    with open(html_file, "w", encoding="utf-8") as html_out:
        html_out.write("<html><head><meta charset='UTF-8'><title>Exported Cards</title>")
        html_out.write("<link rel='stylesheet' type='text/css' href='css/styles.css'>")
        html_out.write("<script>")
        html_out.write("""
        function openExtraInfo(content, isImage) {
            let w = window.open("", "_blank", "width=600,height=400");
            if (isImage) {
                w.document.write("<img src='" + content + "' style='max-width:100%;'>");
            } else {
                w.document.write("<p style='font-size:16px; white-space:pre-wrap;'>" + content + "</p>");
            }
            w.document.close();
        }
        """)
        html_out.write("</script></head><body>")

        for card in cards:
            card_id = card["cardId"]
            answer = card.get("answer", "")
            
            # Remove tag container injected by card template
            answer = re.sub(r'<div id="tags-container".*?>.*?</div>', '', answer, flags=re.DOTALL | re.IGNORECASE)

            fields = card.get("fields", {})
            tags = card.get("tags", [])

            media_files = extract_media_filenames(answer)
            for media_file in media_files:
                media_path = download_media(media_file, media_folder)
                if media_path:
                    answer = answer.replace(media_file, media_path)

            answer = re.sub(r'<button .*?>.*?</button>', '', answer)
            html_out.write(f"<div class='card'>")
            html_out.write(f"<a href='#{card_id}' class='card-id' id='{card_id}'>Card ID: {card_id}</a>")
            html_out.write(f"<p>{answer}</p>")

            for field_name, field_data in fields.items():
                value = field_data.get("value", "").strip()
                if not value or value in answer or field_name.lower() in ["front", "question"]:
                    continue
                hidden_media = extract_media_filenames(value)
                if hidden_media:
                    for m in hidden_media:
                        media_path = download_media(m, media_folder)
                        if media_path:
                            html_out.write(f"<button class='extra-info-button' onclick=\"openExtraInfo('{media_path}', true)\">{html.escape(field_name)}</button>")
                else:
                    safe_content = html.escape(value).replace("{", "&#123;").replace("}", "&#125;")
                    html_out.write(f"<button class='extra-info-button' onclick=\"openExtraInfo('{safe_content}', false)\">{html.escape(field_name)}</button>")

            html_out.write(f"<p class='tags'>Tags: {', '.join(tags)}</p>")
            html_out.write("</div>")

        html_out.write("</body></html>")

    print(f" Opening HTML in browser...")
    os.chdir(output_path)
    webbrowser.open(f"http://localhost:{args.port}")
    HandlerClass = make_handler()

    with TCPServer(("", args.port), HandlerClass) as httpd:
        def serve():
            httpd.serve_forever()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()

        print("🔌 Server is running. Press ENTER to stop...")
        input()
        httpd.shutdown()
        thread.join()
        httpd.server_close()
        httpd.socket.close() 

    if args.cleanup and os.path.exists(output_path):
        os.chdir(os.path.dirname(output_path))
        shutil.rmtree(output_path)
        print(f" Folder {output_path} was deleted after serving.")

if __name__ == "__main__":
    main()

