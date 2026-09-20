"""Thin live API workbench over the controller-owned operator contract."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .operator import OperatorClient

_SENSITIVE_PARTS = ("credential", "password", "secret", "token", "private_key", "api_key", "authorization")


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: ("<redacted>" if any(part in str(key).lower() for part in _SENSITIVE_PARTS)
                      else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def operation_descriptors(capabilities: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return controller-provided operation metadata in stable registry order."""
    operations = capabilities.get("operations")
    if not isinstance(operations, Mapping):
        raise ValueError("controller capabilities did not include operation metadata")
    descriptors = []
    for name, metadata in operations.items():
        if not isinstance(name, str) or not isinstance(metadata, Mapping):
            continue
        descriptors.append({"name": name, **dict(metadata)})
    return descriptors


def _parse_value(field: Mapping[str, Any], value: Any) -> Any:
    if not isinstance(value, str):
        return value
    kind = field.get("type", "string")
    if kind == "string":
        return value
    if kind == "integer":
        try:
            return int(value)
        except ValueError as error:
            raise ValueError(f"{field['name']} must be an integer") from error
    if kind == "number":
        try:
            return float(value)
        except ValueError as error:
            raise ValueError(f"{field['name']} must be a number") from error
    if kind == "boolean":
        if value.lower() in {"true", "yes", "1"}:
            return True
        if value.lower() in {"false", "no", "0"}:
            return False
        raise ValueError(f"{field['name']} must be true or false")
    if kind in {"object", "array"}:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"{field['name']} must be valid JSON") from error
        if kind == "object" and not isinstance(parsed, dict):
            raise ValueError(f"{field['name']} must be a JSON object")
        if kind == "array" and not isinstance(parsed, list):
            raise ValueError(f"{field['name']} must be a JSON array")
        return parsed
    raise ValueError(f"unsupported parameter type: {kind}")


def build_request(descriptor: Mapping[str, Any], values: Mapping[str, Any]) -> dict[str, Any]:
    """Validate/coerce UI field values using the controller's descriptive schema."""
    fields = descriptor.get("parameters", [])
    if not isinstance(fields, list):
        raise ValueError("operation metadata has invalid parameters")
    known = {field.get("name") for field in fields if isinstance(field, Mapping)}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ValueError(f"unknown parameters: {', '.join(unknown)}")
    action = values.get("action")
    result: dict[str, Any] = {}
    for field in fields:
        if not isinstance(field, Mapping) or not isinstance(field.get("name"), str):
            continue
        name = field["name"]
        if name in values and values[name] not in (None, ""):
            value = _parse_value(field, values[name])
        elif "default" in field and (not field.get("default_for") or action in field["default_for"]):
            value = field["default"]
        else:
            value = None
        required = bool(field.get("required"))
        required_for = field.get("required_for", [])
        if action in required_for:
            required = True
        if required and value is None:
            raise ValueError(f"{name} is required")
        if value is None:
            continue
        enum = field.get("enum", [])
        if enum and value not in enum:
            raise ValueError(f"{name} must be one of: {', '.join(enum)}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if field.get("minimum") is not None and value < field["minimum"]:
                raise ValueError(f"{name} must be at least {field['minimum']}")
            if field.get("maximum") is not None and value > field["maximum"]:
                raise ValueError(f"{name} must be at most {field['maximum']}")
        result[name] = value
    return result


def _readable(value: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, Mapping):
        return "\n".join(f"{prefix}{key}: {_readable(item, indent + 2).lstrip()}" for key, item in value.items()) or f"{prefix}(empty)"
    if isinstance(value, list):
        return "\n".join(f"{prefix}- {_readable(item, indent + 2).lstrip()}" for item in value) or f"{prefix}(empty)"
    return str(value)


def format_response(value: Any) -> dict[str, Any]:
    safe = _redact(value)
    return {"structured": safe,
            "raw": json.dumps(safe, indent=2, sort_keys=True, default=str),
            "readable": _readable(safe)}


def format_request(operation: str, params: Mapping[str, Any]) -> str:
    """Render a request preview without exposing credentials or lease tokens."""
    return json.dumps(_redact({"operation": operation, "params": dict(params)}),
                      sort_keys=True, default=str)


class ApiWorkbenchSource:
    """The workbench's only source: capabilities and requests via OperatorClient."""

    def __init__(self, client: OperatorClient):
        self.client = client
        self._capabilities: Mapping[str, Any] | None = None

    def capabilities(self) -> Mapping[str, Any]:
        if self._capabilities is None:
            result = self.client.request("capabilities")
            if not isinstance(result, Mapping):
                raise ValueError("controller capabilities response was not an object")
            self._capabilities = result
        return self._capabilities

    def list(self) -> list[dict[str, Any]]:
        return operation_descriptors(self.capabilities())

    def show(self, operation: str) -> dict[str, Any]:
        for descriptor in self.list():
            if descriptor["name"] == operation:
                return descriptor
        raise ValueError(f"controller does not advertise operation: {operation}")

    def call(self, operation: str, params: Mapping[str, Any]) -> Any:
        self.show(operation)
        return self.client.request(operation, params=dict(params))


def create_app(source: ApiWorkbenchSource) -> Any:
    """Create the optional Textual workbench without importing Textual at module load."""
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical, VerticalScroll
        from textual.widgets import Button, Footer, Header, Input, Select, Static, TabbedContent, TabPane
    except (ImportError, ModuleNotFoundError) as error:
        raise RuntimeError("the API workbench is unavailable; install evoctl[tui]") from error

    class ApiWorkbenchApp(App[None]):
        TITLE = "evoctl API Workbench"
        CSS = """
        #search { width: 1fr; }
        #operations { width: 28; }
        #request { width: 1fr; }
        #response { width: 2fr; }
        #request-fields { height: 1fr; border: solid $surface; padding: 1; }
        #operation-summary { height: auto; padding: 1; }
        """

        def __init__(self) -> None:
            super().__init__()
            self.source = source
            self.descriptors: list[dict[str, Any]] = []
            self.current: dict[str, Any] | None = None
            self.error: str | None = None
            self._mutation_confirmed = False

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            yield Input(placeholder="Search controller operations", id="search")
            with Horizontal():
                with Vertical(id="operations"):
                    yield Select([], id="operation-list", allow_blank=True)
                with Vertical(id="request"):
                    yield Static("Select an operation", id="operation-summary")
                    yield Static("Request: {}", id="request-raw")
                    with VerticalScroll(id="request-fields"):
                        yield Static("Loading controller capabilities…")
                    yield Button("Execute", id="execute", variant="primary")
                with Vertical(id="response"):
                    with TabbedContent():
                        with TabPane("Readable"):
                            yield Static("No response", id="readable")
                        with TabPane("Structured"):
                            yield Static("No response", id="structured")
                        with TabPane("Raw"):
                            yield Static("No response", id="raw")
            yield Footer()

        def on_mount(self) -> None:
            try:
                self.descriptors = self.source.list()
                self._update_options()
            except Exception as error:
                self.error = str(error)
                self.query_one("#operation-summary", Static).update(f"Unavailable: {error}")
                self.query_one("#request-fields", VerticalScroll).remove_children()
                self.query_one("#request-fields", VerticalScroll).mount(Static("Controller operator API is unavailable; no local fallback is used."))

        def _update_options(self, query: str = "") -> None:
            options = [(f"{item['name']} · {item.get('access', 'unknown')}", item["name"])
                       for item in self.descriptors if query.lower() in item["name"].lower()]
            self.query_one("#operation-list", Select).set_options(options)
            if options:
                self.current = self.source.show(options[0][1])
                self._render_current()

        def on_input_changed(self, event: Input.Changed) -> None:
            if event.input.id == "search":
                self._update_options(event.value)
            elif event.input.id and event.input.id.startswith("param-"):
                self._mutation_confirmed = False

        def on_select_changed(self, event: Select.Changed) -> None:
            if event.select.id == "operation-list" and isinstance(event.value, str):
                self.current = self.source.show(event.value)
                self._mutation_confirmed = False
                self._render_current()

        def _render_current(self) -> None:
            if self.current is None:
                return
            availability = self.current.get("availability")
            availability_text = ""
            if isinstance(availability, Mapping) and availability.get("available") is False:
                availability_text = f"\nUnavailable: {availability.get('reason', 'controller did not provide a reason')}"
            safety = self.current.get("safety", {})
            safety_text = ""
            if isinstance(safety, Mapping) and safety.get("requires_explicit_confirmation"):
                safety_text = "\nMutation: press Execute twice to confirm; controller permissions remain authoritative."
            self.query_one("#operation-summary", Static).update(
                f"{self.current['name']} · {self.current.get('access', 'unknown')} · {self.current.get('summary', '')}\n"
                f"{self.current.get('confirmation', 'No extra confirmation metadata reported.')}{safety_text}{availability_text}")
            fields = self.query_one("#request-fields", VerticalScroll)
            fields.remove_children()
            for field in self.current.get("parameters", []):
                if not isinstance(field, Mapping):
                    continue
                label = f"{field['name']} ({field.get('type', 'string')})"
                if field.get("required"):
                    label += " *"
                default = field.get("default", "")
                if field.get("default_for"):
                    default = ""
                fields.mount(Input(value=str(default), placeholder=label,
                                   id=f"param-{field['name']}"))

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id != "execute" or self.current is None:
                return
            values = {}
            for field in self.current.get("parameters", []):
                name = field["name"]
                values[name] = self.query_one(f"#param-{name}", Input).value
            try:
                params = build_request(self.current, values)
                safety = self.current.get("safety", {})
                if (isinstance(safety, Mapping) and safety.get("requires_explicit_confirmation")
                        and not self._mutation_confirmed):
                    self._mutation_confirmed = True
                    self.query_one("#readable", Static).update(
                        "Confirmation required for this controller mutation. Press Execute again to submit.")
                    return
                self._mutation_confirmed = False
                self.query_one("#request-raw", Static).update(
                    f"Request: {format_request(self.current['name'], params)}")
                result = format_response(self.source.call(self.current["name"], params))
                self.query_one("#readable", Static).update(result["readable"])
                self.query_one("#structured", Static).update(json.dumps(result["structured"], indent=2, sort_keys=True))
                self.query_one("#raw", Static).update(result["raw"])
            except Exception as error:
                self.query_one("#readable", Static).update(f"Error: {error}")

    return ApiWorkbenchApp()


def run(client: OperatorClient) -> int:
    app = create_app(ApiWorkbenchSource(client))
    app.run()
    return 0
