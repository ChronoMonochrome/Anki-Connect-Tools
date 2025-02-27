import json
import requests
import sys
import curses

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

def list_all_tags():
    """Retrieve a list of all available tags from Anki."""
    return invoke("getTags") or []

def get_hierarchical_tags(tags):
    """Organizes tags into a hierarchical dictionary."""
    tag_tree = {}
    
    for tag in tags:
        parts = tag.split(":")
        level = tag_tree

        for part in parts:
            if part not in level:
                level[part] = {}
            level = level[part]
    
    return tag_tree

def get_level_tags(tag_tree, path):
    """Retrieve tags at a specific hierarchy level based on path."""
    level = tag_tree
    for key in path:
        if key in level:
            level = level[key]
        else:
            return {}
    return level

def tag_explorer(stdscr):
    """Runs the interactive tag explorer using curses."""
    curses.curs_set(0)  # Hide cursor
    stdscr.clear()
    
    # Initialize colors
    curses.start_color()
    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)  # Tag path
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # Selected tag
    curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLACK)  # Instructions
    
    tags = list_all_tags()
    tag_tree = get_hierarchical_tags(tags)
    
    path = []  # Keeps track of selected tag levels
    selected_index = 0
    scroll_offset = 0  # Enables scrolling when needed

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()  # Get terminal size
        
        # Correctly formatted full tag path (no extra colons)
        tag_path = ":".join(path) if path else "Top Level"
        stdscr.addstr(0, 0, "Path: ", curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(0, 6, tag_path, curses.color_pair(1))

        # Display instructions
        stdscr.addstr(1, 0, "Use ↑/↓ to navigate, ENTER to expand, ESC to collapse, Q to quit", curses.color_pair(3))

        # Get current level tags
        current_tags = list(get_level_tags(tag_tree, path).keys())

        # Ensure selected index is within range
        if selected_index >= len(current_tags):
            selected_index = max(0, len(current_tags) - 1)

        # Handle scrolling
        max_displayable_tags = height - 3  # Space for header & instructions
        if selected_index < scroll_offset:
            scroll_offset = selected_index
        elif selected_index >= scroll_offset + max_displayable_tags:
            scroll_offset = selected_index - max_displayable_tags + 1

        # Display visible tags
        for i, tag in enumerate(current_tags[scroll_offset:scroll_offset + max_displayable_tags]):
            line_position = i + 3
            if i + scroll_offset == selected_index:
                stdscr.addstr(line_position, 0, f"> {tag}", curses.color_pair(2) | curses.A_BOLD)
            else:
                stdscr.addstr(line_position, 0, f"  {tag}")

        stdscr.refresh()

        key = stdscr.getch()

        if key == curses.KEY_UP and selected_index > 0:
            selected_index -= 1
        elif key == curses.KEY_DOWN and selected_index < len(current_tags) - 1:
            selected_index += 1
        elif key == 10:  # Enter key (Fix for double enter issue)
            if selected_index < len(current_tags):  # Ensure selection is valid
                path.append(current_tags[selected_index])
                selected_index = 0  # Reset selection for new level
                scroll_offset = 0  # Reset scrolling
        elif key == 27:  # Escape key (Fix for going back properly)
            if path:
                path.pop()
                selected_index = 0  # Reset selection for previous level
                scroll_offset = 0  # Reset scrolling
        elif key == ord('q'):
            break

def main():
    curses.wrapper(tag_explorer)

if __name__ == "__main__":
    main()

