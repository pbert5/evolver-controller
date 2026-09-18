from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import tui_test


def test_parser_exposes_native_commands() -> None:
    parser = tui_test.build_parser()

    assert parser.parse_args(["doctor"]).command == "doctor"
    assert parser.parse_args(["list", "--json"]).json_output is True
    assert parser.parse_args(["smoke", "--json"]).json_output is True
    assert parser.parse_args(["shell", "--page", "overview"]).page == "overview"
    assert parser.parse_args(["workflow", "--scenario", "waiting_for_input"]).scenario == "waiting_for_input"


def test_parser_rejects_retired_configured_command() -> None:
    with pytest.raises(SystemExit):
        tui_test.build_parser().parse_args(["configured", "--page", "overview"])


def test_source_records_reads_and_rejects_authority() -> None:
    source = tui_test.FakeTuiSource()

    assert source.status()["controller"]["id"] == "fixture-controller"
    assert source.request("instruments")
    with pytest.raises(tui_test.AuthorityViolation):
        source.request("mutate", action="start-run")
    assert [request.operation for request in source.requests] == ["status", "instruments", "mutate"]
    assert [request.operation for request in source.mutation_requests] == ["mutate"]


def test_aggregate_keeps_success_and_failure_records() -> None:
    result = tui_test.aggregate_results(
        [
            tui_test.SurfaceResult("good", "action", "PASS"),
            tui_test.SurfaceResult("bad", "action", "FAIL", error="boom"),
        ]
    )

    assert result.exit_code == 1
    assert [item.name for item in result.results] == ["good", "bad"]
    assert json.loads(result.to_json())["results"][1]["error"] == "boom"


def test_injected_exception_is_not_converted_to_pass() -> None:
    def broken(_: object) -> None:
        raise RuntimeError("renderer exploded")

    result = tui_test.run_actions([("native", broken)])

    assert result.exit_code == 1
    assert result.results[0].status == "FAIL"
    assert "renderer exploded" in result.results[0].error


def test_native_factory_receives_real_app_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class NativeModule:
        @staticmethod
        def create_app(**kwargs: object) -> object:
            calls.append(kwargs)
            return object()

    monkeypatch.setattr(tui_test, "_native_module", lambda: NativeModule)
    source = tui_test.FakeTuiSource()
    host = object()

    assert tui_test.create_native_app(source=source, workflow_host=host, initial_view="workflows") is not None
    assert calls == [{"source": source, "workflow_host": host, "initial_view": "workflows"}]


def test_workflow_mode_deep_links_to_same_native_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, object]] = []

    class App:
        def run(self) -> None:
            seen.append({"ran": True})

    monkeypatch.setattr(tui_test, "create_native_app", lambda **kwargs: seen.append(kwargs) or App())
    monkeypatch.setattr(tui_test, "scenario_host", lambda name: ("host", name))

    assert tui_test.run_interactive("workflow", scenario="waiting_for_input") == 0
    assert seen[0]["initial_view"] == "workflows"
    assert seen[0]["workflow_host"] == ("host", "waiting_for_input")
    assert seen[1] == {"ran": True}


def test_wrapper_uses_repository_uv_environment() -> None:
    wrapper = Path(tui_test.ROOT / "tools" / "tui-test").read_text(encoding="utf-8")

    assert "uv run --all-packages --all-extras python" in wrapper
    assert "exec python3" not in wrapper


def test_harness_does_not_reference_retired_configured_surfaces() -> None:
    source = Path(tui_test.__file__).read_text(encoding="utf-8")

    for retired in ("config_compiler", "meta_webui_ui_runtime_textual", "app.yaml", "configured"):
        assert retired not in source


def test_pilot_settling_is_explicit_and_never_sleep_based() -> None:
    source = Path(tui_test.__file__).read_text(encoding="utf-8")

    assert "await pilot.pause()" in source
    assert "sleep(" not in source
