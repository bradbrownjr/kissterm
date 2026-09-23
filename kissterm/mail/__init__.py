"""The message store behind the Mail, Bulletins and Files tabs (ROADMAP P2).

`message.py` is one message as a plain-text file; `store.py` is the folder
tree those files live in. No UI and no network here.
"""

from .message import KIND_BULLETIN, KIND_MAIL, Message, format_message, parse_message
from .store import MessageStore, Summary, check_folder

__all__ = [
    "KIND_BULLETIN",
    "KIND_MAIL",
    "Message",
    "MessageStore",
    "Summary",
    "check_folder",
    "format_message",
    "parse_message",
]
