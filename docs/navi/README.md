# Navi cheatsheets

The files in `cheatsheets/` are the editable source for this repository's
[Navi](https://github.com/denisidoro/navi) catalog. The checked-in
`generated/meta-ball.cheat` file is produced by:

```text
tools/generate-navi-cheats
```

Generation is deterministic: source files are read in bytewise path order and
the output has a stable header and newline policy. CI and local tests use
`tools/generate-navi-cheats --check` to detect stale generated content.

The container zsh profiles set `NAVI_PATH` to the generated directory and load
`tools/navi-widget.zsh`. Pressing Enter on an empty prompt opens Navi and puts
the selected command into the prompt; it does not execute the selected command.
If Navi is not installed, or the selection is cancelled, the widget leaves the
prompt unchanged. Enter continues to work normally for non-empty prompts.
