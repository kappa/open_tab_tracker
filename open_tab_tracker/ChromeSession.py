import os
import struct
from dataclasses import dataclass
from typing import List, Dict, Optional
import io
import json

# Chrome session command constants
COMMAND_UPDATE_TAB_NAVIGATION = 6
COMMAND_SET_SELECTED_TAB_IN_INDEX = 8
COMMAND_SET_TAB_WINDOW = 0
COMMAND_SET_TAB_GROUP = 25
COMMAND_SET_TAB_GROUP_METADATA2 = 27
COMMAND_SET_SELECTED_NAVIGATION_INDEX = 7
COMMAND_TAB_CLOSED = 16
COMMAND_WINDOW_CLOSED = 17
COMMAND_SET_TAB_INDEX_IN_WINDOW = 2
COMMAND_SET_ACTIVE_WINDOW = 20
COMMAND_LAST_ACTIVE_TIME = 21

@dataclass
class Group:
    high: int
    low: int
    name: str = ""

@dataclass
class HistoryItem:
    idx: int
    url: str = ""
    title: str = ""

@dataclass
class Tab:
    id: int
    history: List[HistoryItem]
    idx: int = 0  # Tab position in window
    win: int = 0  # Window ID
    deleted: bool = False
    current_history_idx: int = 0
    group: Optional[Group] = None

@dataclass
class Window:
    id: int
    active_tab_idx: int = 0
    deleted: bool = False
    tabs: List[Tab] = None

    def __post_init__(self):
        if self.tabs is None:
            self.tabs = []

# Result classes for JSON output
@dataclass
class ResultHistoryItem:
    url: str
    title: str

@dataclass
class ResultTab:
    active: bool
    history: List[ResultHistoryItem]
    url: str
    title: str
    deleted: bool
    group: str

@dataclass
class ResultWindow:
    tabs: List[ResultTab]
    active: bool
    deleted: bool

@dataclass
class Result:
    windows: List[ResultWindow]

def read_uint8(reader: io.BufferedReader) -> int:
    return struct.unpack('<B', reader.read(1))[0]

def read_uint16(reader: io.BufferedReader) -> int:
    return struct.unpack('<H', reader.read(2))[0]

def read_uint32(reader: io.BufferedReader) -> int:
    return struct.unpack('<I', reader.read(4))[0]

def read_uint64(reader: io.BufferedReader) -> int:
    return struct.unpack('<Q', reader.read(8))[0]

def read_string(reader: io.BufferedReader) -> str:
    size = read_uint32(reader)
    read_size = size
    if read_size % 4 != 0:  # Chrome 32bit aligns pickled data
        read_size += 4 - (read_size % 4)
    
    data = reader.read(read_size)
    return data[:size].decode('utf-8')

def read_string16(reader: io.BufferedReader) -> str:
    size = read_uint32(reader)
    read_size = size * 2
    if read_size % 4 != 0:  # Chrome 32bit aligns pickled data
        read_size += 4 - (read_size % 4)
    
    data = reader.read(read_size)
    if len(data) != read_size:
        raise Exception("Failed to read string")
    
    # Create array of uint16 values exactly as Go does
    chars = []
    for i in range(0, size * 2, 2):
        # Combine bytes in same order: data[i+1]<<8 | data[i]
        chars.append((data[i+1] << 8) | data[i])
    
    # Convert UTF-16 code units to string
    return ''.join(map(chr, chars))

def parse(path: str) -> Result:
    tabs: Dict[int, Tab] = {}
    windows: Dict[int, Window] = {}
    groups: Dict[str, Group] = {}
    active_window = None

    def get_window(id: int) -> Window:
        if id not in windows:
            windows[id] = Window(id=id)
        return windows[id]

    def get_group(high: int, low: int) -> Group:
        key = f"{high:x}{low:x}"
        if key not in groups:
            groups[key] = Group(high=high, low=low)
        return groups[key]

    def get_tab(id: int) -> Tab:
        if id not in tabs:
            tabs[id] = Tab(id=id, history=[])
        return tabs[id]

    with open(path, 'rb') as fh:
        # Read magic number "SNSS"
        magic = fh.read(4)
        if magic != b'SNSS':
            raise ValueError("Invalid SNSS file")

        # Read version
        version = read_uint32(fh)
        if version not in (1, 3):
            raise ValueError(f"Invalid SNSS version: {version}")

        # Read commands until EOF
        while True:
            try:
                # Read command size and type
                cmd_data = fh.read(2)
                if not cmd_data or len(cmd_data) < 2:  # EOF check
                    break
                size = struct.unpack('<H', cmd_data)[0] - 1
                cmd_type = read_uint8(fh)
                data = io.BytesIO(fh.read(size))
            except EOFError:
                break

            # Process command based on type
            if cmd_type == COMMAND_UPDATE_TAB_NAVIGATION:
                read_uint32(data)  # size of the data (again)
                id = read_uint32(data)
                hist_idx = read_uint32(data)
                url = read_string(data)
                title = read_string16(data)

                tab = get_tab(id)
                item = next((h for h in tab.history if h.idx == hist_idx), None)
                
                if item is None:
                    item = HistoryItem(idx=hist_idx)
                    tab.history.append(item)
                
                item.url = url
                item.title = title

            elif cmd_type == COMMAND_SET_SELECTED_TAB_IN_INDEX:
                id = read_uint32(data)
                idx = read_uint32(data)
                get_window(id).active_tab_idx = idx

            elif cmd_type == COMMAND_SET_TAB_GROUP_METADATA2:
                read_uint32(data)  # Size
                high = read_uint64(data)
                low = read_uint64(data)
                name = read_string16(data)
                get_group(high, low).name = name

            elif cmd_type == COMMAND_SET_TAB_GROUP:
                id = read_uint32(data)
                read_uint32(data)  # Struct padding
                high = read_uint64(data)
                low = read_uint64(data)
                get_tab(id).group = get_group(high, low)

            elif cmd_type == COMMAND_SET_TAB_WINDOW:
                win = read_uint32(data)
                id = read_uint32(data)
                get_tab(id).win = win

            elif cmd_type == COMMAND_WINDOW_CLOSED:
                id = read_uint32(data)
                get_window(id).deleted = True

            elif cmd_type == COMMAND_TAB_CLOSED:
                id = read_uint32(data)
                get_tab(id).deleted = True

            elif cmd_type == COMMAND_SET_TAB_INDEX_IN_WINDOW:
                id = read_uint32(data)
                index = read_uint32(data)
                get_tab(id).idx = index

            elif cmd_type == COMMAND_SET_ACTIVE_WINDOW:
                id = read_uint32(data)
                active_window = get_window(id)

            elif cmd_type == COMMAND_SET_SELECTED_NAVIGATION_INDEX:
                id = read_uint32(data)
                idx = read_uint32(data)
                get_tab(id).current_history_idx = idx

        # Sort and organize the final data structures
        for tab in tabs.values():
            tab.history.sort(key=lambda x: x.idx)
            window = get_window(tab.win)
            window.tabs.append(tab)

        for window in windows.values():
            window.tabs.sort(key=lambda x: x.idx)

        # Build the result structure
        result_windows = []
        for window in windows.values():
            result_window = ResultWindow(
                tabs=[],
                active=(window == active_window),
                deleted=window.deleted
            )

            idx = 0
            for tab in window.tabs:
                group_name = tab.group.name if tab.group else ""
                
                result_tab = ResultTab(
                    active=(idx == window.active_tab_idx),
                    deleted=tab.deleted,
                    group=group_name,
                    history=[],
                    url="",
                    title=""
                )

                for hist in tab.history:
                    result_tab.history.append(ResultHistoryItem(hist.url, hist.title))
                    if hist.idx == tab.current_history_idx:
                        result_tab.url = hist.url
                        result_tab.title = hist.title
                        break

                result_window.tabs.append(result_tab)
                if not tab.deleted:
                    idx += 1

            result_windows.append(result_window)

        return Result(result_windows)

def find_session(path):
    """
    Find the most recent Chrome session file in the given directory path.
    Returns the full path to the session file, or empty string if none found.
    """
    candidate_file = ""
    latest_mtime = 0

    try:
        for root, _, files in os.walk(path):
            for file in files:
                if file.startswith("Session_"):
                    full_path = os.path.join(root, file)
                    mtime = os.stat(full_path).st_mtime
                    if mtime > latest_mtime:
                        latest_mtime = mtime
                        candidate_file = full_path

        return candidate_file

    except OSError:
        return ""

def get_chrome_session_file():
    # Default target path
    target = os.path.expandvars('$HOME/.config/chromium')

    # Try alternative paths if default doesn't exist
    if not os.path.exists(target):
        target = os.path.expandvars('$HOME/.config/google-chrome')
    if not os.path.exists(target):
        target = os.path.expandvars('$HOME/.config/chrome')

    # Handle directory vs file
    if os.path.isdir(target):
        target = find_session(target)

    if not target:
        raise RuntimeError("Unable to find session file.")

    return target


def main():
    session_file = get_chrome_session_file()
    print(f"Reading session from: {session_file}")

    data = parse(session_file)
    print("Full session data:")
    print(json.dumps(data, default=lambda o: o.__dict__, indent=2))
    
    # Count total tabs
    total_tabs = 0
    for window in data.windows:
        if not window.deleted:
            for tab in window.tabs:
                if not tab.deleted:
                    total_tabs += 1

    print(f"\nTotal tabs: {total_tabs}")

if __name__ == "__main__":
    main()
