# Herdr packaging follow-up

The distributed ZIP is updated only when the user asks for a package update. Changes tested in the live profile can stay pending for that release. Keep independently selectable features and feature-tagged logs. Put common helpers and shared dependencies together in the package when incorporating future changes.

Public versioning started with `Herdr-Mod-Kit-Windows-x64-v1.0.zip`. The public filename is independent of the internal installer version used for upgrades.

Released in Windows x64 1.1.0: drag-to-split for document tabs and Files, automatic file refresh, continuous PDF scrolling, the Claude Retry-After policy, and the compact usage bars. Shared code is bundled in `common/`, with per-feature diagnostics retained.

Released in Windows x64 1.2.0: PDF and text link handling, splitting panes back into independent tabs, and a layout-scoped Ctrl+W. The installer logs the tabs feature separately and preserves existing Ctrl+W bindings.

Windows x64 v1.0 (internal 1.3.0) includes both the Windows progress-file lock fix and dragging individual files onto another folder or the current root. Moves stay on the same host and filesystem and preserve both files on name conflicts.

Windows x64 v1.4.0 includes the Files menu, pointer-anchored high-resolution PDF zoom, bounded previews and cache cleanup, and in-place upgrade checks for existing profiles. Omitted options preserve the selected features and usage host.

Windows x64 v1.5.0 adds independent saved usage sources for Codex and Claude Code, a compact kit version in the status bar, and source and destination feedback when dragging files within Files.

Windows x64 v1.6.0 adds per-pane file tabs, focuses an existing document when reopened in the same space, and adds a split layout chooser. Files supports single-click selection, Delete confirmation, Enter or double-click to open, and manual refresh of expanded folders. File dialogs use aligned action buttons.

Windows x64 v1.7.0 applies the security, resource and speed review. Transfers send 4 MiB chunks four at a time with the earlier sizes as fallback, continue across helper runs and after an interrupted link, and can be cancelled; same-computer transfers copy directly; uploads publish with the account's default mode or the replaced file's mode; stale staging files are swept. The PDF viewer renders missing pages in one helper run, reads two pages ahead, keeps twelve pages for scrolling back, computes text boxes from one transform per page, and retries failed pages a bounded number of times. Files lists every folder with one program on POSIX hosts, re-reads only folders a watch reports, pauses while hidden, and skips `git status` where the repository's own config names filter programs until the person trusts it. Helpers started with `python -c` run isolated (`-I`). Built and tested on Linux; the Windows checks listed in `HANDOFF.md` are still to run. Details are in `docs/changes-v1.7.0.md`.

Windows x64 v1.8.0 adds folder ZIP downloads and creation of files and folders from the Files context menu. Transfer continuation tokens preserve filesystem timestamp and identity precision across the JavaScript UI.

Windows x64 v1.9.0 adds a two-row Files toolbar with icon actions and a selection caption. HTML and HTM open in the native rich-text preview with a Source toggle. The Windows 0.1.18 desktop checks cover the installed toolbar, HTML preview, and a v1.8.0 upgrade and reinstall.

Windows x64 v1.9.1 adds replace and numbered-copy choices to file and folder ZIP downloads and closes the native Save As picker on cancellation. Increment the patch number for each subsequent release as requested.

Windows x64 v1.9.2 shows transfer progress bars and renders local and remote HTML documents with Microsoft Edge.
