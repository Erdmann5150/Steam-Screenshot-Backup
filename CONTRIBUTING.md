# Contributing

This is a solo hobby project (see the [Disclaimer](README.md#disclaimer) in
the README), so keep expectations modest, but bug reports, feature requests,
and pull requests are all welcome.

## Bug reports and feature requests

Use the [issue templates](../../issues/new/choose) - they ask for the
details that are actually useful here (app version, Windows version, log
excerpt). For anything security-related, see [SECURITY.md](SECURITY.md)
instead of opening a public issue.

## Pull requests

- For small fixes (typos, obvious bugs), just open a PR.
- For anything larger - new features, behavior changes - open an issue first
  to discuss the approach before writing code, so you don't end up building
  something that doesn't fit.
- Match the existing code style. Notably: `app/*.cs` and `*.ps1` files must
  stay pure ASCII (no smart quotes, em dashes, etc. - use `\uXXXX` escapes),
  because of a past mojibake encoding bug. See `CLAUDE.md` for the full
  rationale and the verification snippet.
- Build and run locally before submitting: `.\build.ps1` (requires the .NET 8
  SDK and Inno Setup 6 - see [Building from source](README.md#building-from-source)),
  or `dotnet run` inside `app\` for a quick dev loop.
- Test against a throwaway folder, never against a real Steam screenshot
  library.

## What this project is built with

The app and script are developed with [Claude Code](https://claude.com/claude-code)
under human direction and testing - `CLAUDE.md` documents the working
conventions used during that process (encoding rules, build/release steps,
safe testing patterns). It's a useful reference even if you're contributing
by hand.
