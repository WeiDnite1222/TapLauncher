"""Official Log4j configuration and streaming console XML support."""

import hashlib
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from weakref import WeakKeyDictionary, WeakSet
from xml.etree import ElementTree as ET

import requests


MAX_CONFIG_BYTES = 1024 * 1024
MAX_EVENT_CHARS = 1024 * 1024
EVENT_START = re.compile(r"<(?:log4j:)?Event\b")
EVENT_END = re.compile(r"</(?:log4j:)?Event\s*>|<!\[CDATA\[|<!--")


def _event_end(text: str) -> int | None:
    """Locate the closing tag without treating CDATA/message text as markup."""
    offset = 0
    while match := EVENT_END.search(text, offset):
        if match.group().startswith("</"):
            return match.end()
        terminator = "]]>" if match.group() == "<![CDATA[" else "-->"
        end = text.find(terminator, match.end())
        if end < 0:
            return None
        offset = end + len(terminator)
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _format_event(xml: str) -> list[tuple[str, str]]:
    # Minecraft's LegacyXMLLayout emits log4j-prefixed fragments without a root.
    if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise ValueError("Unsupported XML declaration in log event")
    root = ET.fromstring('<root xmlns:log4j="http://jakarta.apache.org/log4j/">' + xml + "</root>")
    event = root[0]
    level = event.get("level", "INFO").upper()
    thread = event.get("thread", "unknown")
    logger = event.get("logger", event.get("loggerName", ""))
    timestamp = event.get("timestamp", event.get("timeMillis"))
    time_text = ""
    if timestamp is not None:
        try:
            time_text = "[" + datetime.fromtimestamp(int(timestamp) / 1000).strftime("%H:%M:%S") + "] "
        except (ValueError, OverflowError, OSError):
            pass
    prefix = f"{time_text}[{thread}/{level}] "
    if logger:
        prefix += f"[{logger}] "
    messages = []
    throwables = []
    for child in event:
        name = _local_name(child.tag).lower()
        if name == "message":
            messages.append("".join(child.itertext()))
        elif name == "throwable":
            content = "".join(child.itertext()).strip()
            if content:
                throwables.append(content)
    message = "\n".join(messages)
    if throwables:
        message += ("\n" if message else "") + "\n".join(throwables)
    return [(level, prefix + message)]


class LogParser:
    def __init__(self, source: str):
        self.raw_type = "error" if source == "stderr" else "normal"
        self.pending = ""

    def _raw(self, text: str) -> list[tuple[str, str]]:
        return [(self.raw_type, line) for line in text.splitlines()]

    def feed(self, text: str | None) -> list[tuple[str, str]]:
        if text is None:
            pending, self.pending = self.pending, ""
            return self._raw(pending)
        if not self.pending and not EVENT_START.search(text):
            return [(self.raw_type, text)]
        self.pending += text + "\n"
        output = []
        while self.pending:
            start = EVENT_START.search(self.pending)
            if start is None:
                output.extend(self._raw(self.pending))
                self.pending = ""
                break
            prefix, self.pending = self.pending[:start.start()], self.pending[start.start():]
            if prefix.strip():
                output.extend(self._raw(prefix))
            end = _event_end(self.pending)
            if end is None:
                if len(self.pending) > MAX_EVENT_CHARS:
                    output.extend(self._raw(self.pending))
                    self.pending = ""
                break
            xml, self.pending = self.pending[:end], self.pending[end:]
            # The newline emitted after an XML fragment is a delimiter.
            self.pending = self.pending.removeprefix("\r\n").removeprefix("\n")
            try:
                output.extend(_format_event(xml))
            except (ET.ParseError, ValueError):
                output.extend(self._raw(xml))
        return output


class Log4jPlugin:
    def __init__(self, context):
        self.context = context
        self.parsers = WeakKeyDictionary()
        self.windows = WeakSet()
        self._download_lock = threading.Lock()

    def extra_arguments(self, profile, version_manifest: dict) -> dict[str, list[str]]:
        logging = version_manifest.get("logging", {}).get("client")
        if not logging:
            return {"jvm": [], "game": []}
        if logging.get("type") != "log4j2-xml":
            self.context.logger.warning("Unsupported client logging type: %s", logging.get("type"))
            return {"jvm": [], "game": []}
        path = self._prepare_config(logging["file"])
        argument = logging["argument"]
        if not isinstance(argument, str) or "${path}" not in argument:
            raise ValueError("Invalid client logging argument")
        # A Windows drive prefix (C:/...) can be interpreted as a URI scheme.
        # Use an explicit file URI, including escaping spaces and Unicode.
        return {"jvm": [argument.replace("${path}", path.as_uri())], "game": []}

    def _prepare_config(self, file: dict) -> Path:
        sha1 = file["sha1"].lower()
        if re.fullmatch(r"[0-9a-f]{40}", sha1) is None:
            raise ValueError("Invalid client logging SHA-1")
        expected_size = file["size"]
        if not isinstance(expected_size, int) or not 0 < expected_size <= MAX_CONFIG_BYTES:
            raise ValueError("Invalid client logging configuration size")
        # Content-addressed paths also avoid trusting a manifest filename as a path.
        path = (Path(self.context.data_dir) / "log_configs" / sha1 / "client.xml").resolve()

        def verified(data):
            return len(data) == expected_size and hashlib.sha1(data).hexdigest() == sha1

        with self._download_lock:
            if path.is_file() and path.stat().st_size == expected_size and verified(path.read_bytes()):
                return path
            data = bytearray()
            with requests.get(file["url"], stream=True, timeout=(10, 30)) as response:
                response.raise_for_status()
                for chunk in response.iter_content(8192):
                    data.extend(chunk)
                    if len(data) > expected_size:
                        raise ValueError("Client logging configuration exceeds expected size")
            if not verified(data):
                raise ValueError("Client logging configuration size or SHA-1 mismatch")
            ET.fromstring(data)  # Fail before launching if the configuration is invalid XML.
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(data)
                temporary.replace(path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return path

    def create_widget(self, window):
        from .log_widget import ColoredLogOutput

        self.windows.add(window)
        return ColoredLogOutput(window)

    def output(self, window, source: str, text: str | None) -> list[tuple[str, str]]:
        from .log_widget import ColoredLogOutput

        # Also upgrade windows that were opened before the plugin was enabled.
        if hasattr(window, "set_output_widget") and not isinstance(window.log_output, ColoredLogOutput):
            window.set_output_widget(self.create_widget(window))
        streams = self.parsers.setdefault(window, {})
        parser = streams.setdefault(source, LogParser(source))
        events = parser.feed(text)
        if text is None:
            streams.pop(source, None)
            if not streams:
                self.parsers.pop(window, None)
        return events

    def cleanup(self):
        # Overrides are restored before this callback by Wheel's reverse cleanup.
        for window, streams in list(self.parsers.items()):
            for parser in streams.values():
                for line_type, message in parser.feed(None):
                    window._append_output(line_type, message)
        self.parsers.clear()
        from .log_widget import ColoredLogOutput
        from pages.process_log import create_process_log_widget

        for window in list(self.windows):
            if isinstance(window.log_output, ColoredLogOutput):
                window.set_output_widget(create_process_log_widget(window))
        self.windows.clear()
