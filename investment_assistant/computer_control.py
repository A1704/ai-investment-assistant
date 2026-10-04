import ipaddress
import os
import re
import shutil
import subprocess
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus, urlsplit, urlunsplit


class ComputerControlError(ValueError):
    """Raised when a requested computer action is unsupported or unsafe."""


@dataclass(frozen=True)
class ComputerCommand:
    action: str
    argument: str = ""


_SEARCH_QUERY_MAX_LENGTH = 500
_URL_MAX_LENGTH = 2048
_DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_BLOCKED_DOMAIN_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".lan",
    ".home",
    ".test",
)
_COMPUTER_COMMAND_PREFIX = re.compile(
    r"^(?:please\s+)?(?:open|launch|start|run|execute|search|browse|visit|"
    r"navigate\s+to|go\s+to|close|shutdown|restart|delete|remove|click|"
    r"press|type)\b",
    re.IGNORECASE,
)


def parse_computer_command(text):
    if not isinstance(text, str) or not text.strip():
        return None

    command = " ".join(text.strip().split())
    command_lower = command.casefold().rstrip(".!?")
    fixed_commands = {
        "open google": ComputerCommand("open_google"),
        "open google.com": ComputerCommand("open_google"),
        "launch google": ComputerCommand("open_google"),
        "go to google": ComputerCommand("open_google"),
        "open chrome": ComputerCommand("open_chrome"),
        "launch chrome": ComputerCommand("open_chrome"),
        "start chrome": ComputerCommand("open_chrome"),
        "open youtube": ComputerCommand("open_youtube"),
        "open youtube.com": ComputerCommand("open_youtube"),
        "launch youtube": ComputerCommand("open_youtube"),
        "go to youtube": ComputerCommand("open_youtube"),
    }
    if command_lower in fixed_commands:
        return fixed_commands[command_lower]

    search_match = re.fullmatch(
        r"(?:please\s+)?search\s+google\s+for\s+(.+)",
        command,
        re.IGNORECASE,
    )
    if search_match:
        query = search_match.group(1).strip()
        if not query:
            raise ComputerControlError("Please provide a Google search query.")
        if len(query) > _SEARCH_QUERY_MAX_LENGTH:
            raise ComputerControlError("The Google search query is too long.")
        return ComputerCommand("search_google", query)

    url_match = re.fullmatch(
        r"(?:please\s+)?(?:open|visit)\s+(https?://\S+)",
        command,
        re.IGNORECASE,
    )
    if url_match:
        return ComputerCommand("open_url", validate_safe_url(url_match.group(1)))

    if _COMPUTER_COMMAND_PREFIX.match(command):
        raise ComputerControlError(
            "That computer command is not supported. "
            "Supported actions are opening Google, Chrome, YouTube, "
            "searching Google, or opening a safe HTTP(S) URL."
        )

    return None


def validate_safe_url(url):
    if not isinstance(url, str) or not url or len(url) > _URL_MAX_LENGTH:
        raise ComputerControlError("Provide a valid HTTP or HTTPS URL.")
    if any(character.isspace() or ord(character) < 32 for character in url):
        raise ComputerControlError("The URL contains invalid characters.")

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ComputerControlError("Provide a valid HTTP or HTTPS URL.") from error

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https") or not hostname:
        raise ComputerControlError("Only complete HTTP or HTTPS URLs are allowed.")
    if parsed.username is not None or parsed.password is not None:
        raise ComputerControlError("URLs containing credentials are not allowed.")
    if port is not None and port not in (80, 443):
        raise ComputerControlError("Only standard HTTP and HTTPS ports are allowed.")

    try:
        normalized_host = hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise ComputerControlError("The URL hostname is invalid.") from error

    if (
        not normalized_host
        or normalized_host == "localhost"
        or any(normalized_host.endswith(suffix) for suffix in _BLOCKED_DOMAIN_SUFFIXES)
    ):
        raise ComputerControlError("Local or private network URLs are not allowed.")

    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        labels = normalized_host.split(".")
        if len(labels) < 2 or any(not _DOMAIN_LABEL.fullmatch(label) for label in labels):
            raise ComputerControlError("The URL hostname is invalid.")
    else:
        if not address.is_global:
            raise ComputerControlError("Local or private network URLs are not allowed.")

    netloc = normalized_host
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, parsed.fragment))


def _chrome_executable_path():
    executable = shutil.which("chrome") or shutil.which("chrome.exe")
    if executable:
        return executable

    candidates = (
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    )
    return next((str(path) for path in candidates if path.is_file()), None)


def _open_browser_url(url):
    if not webbrowser.open(url, new=2):
        raise ComputerControlError(
            "The browser could not open the requested page."
        )


def open_google():
    _open_browser_url("https://www.google.com/")
    return "Opened Google."


def open_chrome():
    chrome_path = _chrome_executable_path()
    if not chrome_path:
        raise ComputerControlError(
            "Google Chrome was not found on this computer."
        )

    subprocess.Popen([chrome_path], shell=False)
    return "Opened Google Chrome."


def open_youtube():
    _open_browser_url("https://www.youtube.com/")
    return "Opened YouTube."


def search_google(query):
    if not isinstance(query, str) or not query.strip():
        raise ComputerControlError("Please provide a Google search query.")
    query = query.strip()
    if len(query) > _SEARCH_QUERY_MAX_LENGTH:
        raise ComputerControlError("The Google search query is too long.")

    _open_browser_url(
        "https://www.google.com/search?q=" + quote_plus(query)
    )
    return "Opened Google search results for your query."


def open_url(url):
    safe_url = validate_safe_url(url)
    _open_browser_url(safe_url)
    return f"Opened {safe_url}."


def execute_computer_command(command):
    if not isinstance(command, ComputerCommand):
        raise ComputerControlError("Unsupported computer action.")

    actions = {
        "open_google": open_google,
        "open_chrome": open_chrome,
        "open_youtube": open_youtube,
        "search_google": lambda: search_google(command.argument),
        "open_url": lambda: open_url(command.argument),
    }
    action = actions.get(command.action)
    if action is None:
        raise ComputerControlError("Unsupported computer action.")
    return action()
