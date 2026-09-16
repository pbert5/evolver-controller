# Navi cheatsheets

The files in `cheatsheets/` are the editable source for this repository's
[Navi](https://github.com/denisidoro/navi) catalog. The checked-in
`generated/meta-ball.cheat` file is produced by:

```text
tools/generate_navi_cheats
```

Generation is deterministic: source files are read in bytewise path order and
the output has a stable header and newline policy. CI and local tests use
`tools/generate_navi_cheats --check` to detect stale generated content.

The generator derives human command paths from metactl's first-class
presentation model at
[`metactl-cli.json`](../../metactl/applications/deployment/metactl-cli.json).
Each entry retains its stable action ID as metadata. The action catalog remains
authoritative for lifecycle status and other action facts; actions without a
presentation path remain available through the low-level ID inventory. See the
[metactl CLI reference](../metactl/cli.md) and [Human Command Path](../_concepts/human-command-path.md)
for the distinction between presentation and capability.

The container zsh profiles set `NAVI_PATH` to the generated directory and load
`tools/navi-widget.zsh`. Pressing Enter on an empty prompt opens Navi and puts
the selected command into the prompt; it does not execute the selected command.
If Navi is not installed, or the selection is cancelled, the widget leaves the
prompt unchanged. Enter continues to work normally for non-empty prompts.
