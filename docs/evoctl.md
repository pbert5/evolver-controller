# evoctl operator documentation

This page is the compatibility entry point for the complete controller-local
operator guide. Start with [the guide](evoctl/README.md), then use the
[generated command reference](evoctl/reference.md). The reference is derived
from the controller parser and is checked in CI so help, examples, and docs
cannot silently drift apart.

`evoctl` is edge-local. Use [metactl](metactl/README.md) for central fleet
operation. In an Edge Dev Container run `evoctl ...`; from the host use
`tools/dev-env evolver-edge exec evoctl ...`.

Lifecycle terminology shared with the runtime QoL work remains explicit:

```text
evoctl update apply RELEASE       # explicit governed release
evoctl upgrade                    # governed latest/recommended shortcut (when #114 lands)
tools/evolver-edge upgrade        # developer checkout fast-forward + rebuild (when landed)
```

The latter two shortcuts are documented contracts, not claims that the current
parser already accepts them. The lifecycle source of truth is #112/#114 and its
PR #120 documentation; final integration must reconcile that material on the
then-current `hardware-testing` head. This standalone #107 branch intentionally
does not copy a sibling PR's file or implement lifecycle aliases. It does not
add firmware flashing, host-runtime lifecycle authority, TUI behavior, or
physical actuation.
