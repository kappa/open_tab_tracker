from .Browser import Browser
from ..ChromeSession import parse, get_chrome_session_file
from open_tab_tracker.Platform import OS


class Chrome(Browser):
    """Chrome browser implementation."""

    def __init__(self, current_os: OS):
        super().__init__(current_os)

    @classmethod
    def get_tab_count(self) -> int:
        """Returns an integer representing the number of active tabs in Chrome."""
        try:
            session_file = get_chrome_session_file()
            data = parse(session_file)
            
            total_tabs = 0
            for window in data.windows:
                if not window.deleted:
                    for tab in window.tabs:
                        if not tab.deleted:
                            total_tabs += 1
            
            return total_tabs
        except Exception:
            return 0
