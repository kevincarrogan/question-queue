# Canvas

The project's idea canvas, published as a private Claude Design artifact:
<https://claude.ai/artifact/4WoaDyNhfYrBrUGYCPR4je>.

`project/` mirrors the artifact's published paths one to one:

- `canvas.json`: which boards exist, where each sits on the canvas, their
  order, and the sticky notes.
- `*.dc.html`: one board each, in the Design type's format. `support.js` is
  supplied by the type and is not kept here.

`assets/` holds images uploaded to the canvas's asset store, which boards
reference by `/_blob/<id>` rather than by path:

- `cut-down.png` → `/_blob/edbf0609bde1c0dd1311039276a3eb2a`
- `markdown-asking.png` → `/_blob/5442ad0ff325f6b5ce13d05840a9d1df`
- `built-todos.png` → `/_blob/6e7e068570a0a5a26ac91c1875476400`
- `two-panes.png` → `/_blob/85d30a10451a031949d775d5c031e88b`
- `ticks.png` → `/_blob/94ecacdd70dc1f2cbffd38affbd855a0`
- `palette.png` → `/_blob/b757953da2ee7953739885e8ef63d4b5`

They're TUI screenshots: Textual's SVG export, rendered and cropped to PNG.
A changed image is a new upload with a new id, so repoint the board.

Boards, in canvas order: `Main` (what qq is, its main keys and the file
behind them), `Roadmap` (ideas and next steps), `Tried` (the four versions
of the TUI so far, why each was replaced, and what's changed since),
`NextUp` (ticks and file references, as built), `Palette` (the ctrl+p
palette in each pane), `Decisions` (decisions so far, with the full
reasoning in `docs/design.md`).

## Changing it

1. **Pull before editing.** Boards and stickies can be edited in the browser.
   Read the artifact's files back (the Artifact tool, `action: read`, with
   the `project/…` paths) and bring any change into this folder first.
2. **Edit here, then publish from here.** With the Artifact tool: `url` the
   artifact above, `root` this folder, `file_path` one changed file, and
   `files` mapping each other changed `project/…` path to itself. Send
   `canvas.json` only when boards or notes change. Files left out are kept.
