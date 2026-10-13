# Canvas

The project's idea canvas, published as a private Claude Design artifact:
<https://claude.ai/artifact/4WoaDyNhfYrBrUGYCPR4je>.

`project/` mirrors the artifact's published paths one to one:

- `canvas.json`: which boards exist, where each sits on the canvas, their
  order, and the sticky notes.
- `*.dc.html`: one board each, in the Design type's format. `support.js` is
  supplied by the type and is not kept here.

Boards: `Main` (what v1 is), `Roadmap` (ideas and next steps), `NextOpen`
(how next open moves), `Decisions` (decisions so far, with the full reasoning
in `docs/design.md`).

## Changing it

1. **Pull before editing.** Boards and stickies can be edited in the browser.
   Read the artifact's files back (the Artifact tool, `action: read`, with
   the `project/…` paths) and bring any change into this folder first.
2. **Edit here, then publish from here.** With the Artifact tool: `url` the
   artifact above, `root` this folder, `file_path` one changed file, and
   `files` mapping each other changed `project/…` path to itself. Send
   `canvas.json` only when boards or notes change. Files left out are kept.
