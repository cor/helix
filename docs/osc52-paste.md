# Native OSC 52 clipboard reads

Configure `editor.clipboard-provider = "termcode"` to read and write the terminal
clipboard without a clipboard subprocess. See the clipboard-provider section of
the user manual for configuration and terminal requirements.

The workspace pins [cor/termina](https://github.com/cor/termina/tree/d5d797a83363f859b204ca46429911ef9850869d)
at commit `d5d797a83363f859b204ca46429911ef9850869d` in both `Cargo.toml` and `Cargo.lock`.
The fork is based on upstream Termina 0.3.3, commit
`6f7871364af18f2a36a2be28cfc658fea130992c`, with five changed source files:

- `src/escape/osc.rs`: an owned selection-response variant.
- `src/base64.rs`: strict RFC 4648 decoding and regression tests.
- `src/parse.rs`: BEL/ST clipboard responses, fragmented-input tests,
  incremental scanning for large responses, and Escape-key preservation.
- `src/event/reader.rs` and `src/event/source/unix.rs`: retain ambiguous Escape
  fragments while a clipboard query is outstanding, with a guard that restores
  normal key handling on success, errors, and timeouts.

Both Cargo and Nix fetch the exact Git revision. No dependency source is vendored
in Helix, and the other dependency versions are unchanged. Once these changes
are available in an upstream Termina release, replace the Git dependency with
that release and update the lockfile after running the checks below.

```sh
cargo test --locked -p termina --lib
cargo build --locked --bin hx
python3 contrib/test-osc52-paste.py --helix target/debug/hx
nix build .#default
```

The standalone PTY check runs real Helix with an emulated terminal. It covers
focus/mouse events and a save key arriving before the clipboard response,
fragmented Unicode including the leading Escape, empty and primary clipboards,
a 160 KiB clipboard, and recovery after a denied read. It does not access the
desktop clipboard. The Nix release binary is also tested through a real Ghostty
terminal and Herdr, checking both paste shortcuts and clipboard copy.
