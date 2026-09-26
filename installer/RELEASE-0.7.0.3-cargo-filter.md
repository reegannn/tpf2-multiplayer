### Unofficial test build: 0.7.0.3 + line stop cargo filters

This is **not** an official silver2127 release. It is 0.7.0.3 with one change,
built from [reegannn/tpf2-multiplayer](https://github.com/reegannn/tpf2-multiplayer).

- **Line stop cargo filters are kept.** A cargo filter set on a line stop in the line
  editor (which cargo loads or unloads there, and each cargo's maximum share) is now sent
  to every player. Before, every line edit reset it on every game.

**Not tested in a game yet.** Keep save backups.

**Everyone in the session needs this build.** It reports the same version as the
official 0.7.0.3, so official players can still join, and their games would drift out
of sync with yours. To go back, install the official release from
[silver2127/tpf2-multiplayer](https://github.com/silver2127/tpf2-multiplayer/releases/latest).

**Windows only.** The Linux / Proton installers attached here download the official
release, not this build.

If a filter does not carry over, send `tpf2_slice.log` and the mod log from
`%LOCALAPPDATA%\tpf2mp\logs\`. Look for `cargo filter not read`.
