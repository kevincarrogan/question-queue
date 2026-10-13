# Question Queue: v1 design

This is the record of how v1 works and why, written for whoever builds the
next front end (the MCP server, the VS Code extension, remote access). The
README covers how to use it; this covers how it fits together.

## What it is

A keyboard-driven tool for thinking through a problem by writing yourself
questions and answering them in your own voice. Questions nest under the
questions that raised them, which records the trail of ideas. You work on one
question at a time and park new ones as they come up.

v1 is a Textual TUI over a single markdown file. There is no database: the
file is the only source of truth, and it has to stay pleasant to read and edit
by hand.

## Naming

| Thing | Name |
| --- | --- |
| Product | Question Queue |
| PyPI distribution | `question-queue` |
| Import package | `questionqueue` |
| Command | `qq` |

The initials spell the command. `quarry` (the working folder name) and `qq`
are taken on PyPI by unrelated projects; `interrobang` was considered and
dropped because it doesn't match `qq`. The folder is still called `quarry`
and will be renamed to `question-queue`.

## Layout

```
src/questionqueue/
  cli.py            qq entry point
  core/             no UI imports; what every front end builds on
    model.py        Question, RawLine, Document
    parser.py       markdown → Document
    serialise.py    Document → markdown
    ops.py          tree operations
    store.py        load, atomic save, conflict detection, watching
    ids.py          short ID generation
    errors.py       QuestionNotFound, InvalidMove, ExternalChange
  tui/
    app.py          QQApp: bindings, autosave, reload handling
    focus.py        focus view and the answer editor
    outline.py      outline view
    modals.py       park input and y/n-style choices
    app.tcss
tests/
  core/             round-trip, ops, next_open, store
  tui/              pilot tests against the real app
  fixtures/         messy real-world markdown
```

`core` is the boundary that matters. The TUI only ever calls `core.ops`
and `DocumentFile`, and every operation takes and returns question IDs, never
positions in the file, so a tool-calling LLM can drive it as-is.

Runtime dependencies are Textual and watchfiles. Dev dependencies are pytest,
ruff, mypy (strict) and pre-commit. Pilot tests run Textual's `run_test()`
inside `asyncio.run()`, which avoids needing pytest-asyncio.

## The markdown format

```markdown
- ? How should the essay open? <!-- q:a1b2 -->
  > Start with the story, it's concrete.
  - ? Which anecdote exactly? <!-- q:c3d4 -->
  - ?x Does it need background first? <!-- q:e5f6 -->
    > No, link out instead.
- ? Who's the audience? <!-- q:g7h8 -->
```

### What the parser recognises

- **Question:** a list item (`-`, `*` or `+`, then one space) whose text starts
  with `? ` (open) or `?x ` (answered). `- ?x` needs the space after the `x`,
  so `- ?xylophone` is not a question. A question with no text is not a
  question.
- **ID:** an HTML comment at the very end of the question line,
  `<!-- q:… -->`. Any `[A-Za-z0-9_-]+` is accepted when reading; new IDs are
  4 random hex characters, longer only if the short ones run out. A comment
  in the middle of the text is just text.
- **Answer:** consecutive `>` lines directly under the question line,
  indented further than the question. The parser strips the `>` and at most one
  following space, and nothing else. A bare `>` is a blank line in the
  answer.
- **Nesting:** worked out from relative indentation (tabs count as 4 columns),
  so 2-space, 4-space and tab-indented notes all parse. New lines are written
  with 2 spaces, or to match existing siblings.

Everything else is a **raw line**, kept verbatim.

### Round-trip fidelity

This was the hardest requirement: existing notes must survive load → save
unchanged apart from added IDs.

- **Source lines are remembered.** Each question stores the exact lines it was
  parsed from. Until its text, status or answer changes, the serialiser writes
  those lines back byte for byte. Changing one part re-renders only that part:
  editing an answer leaves the question line alone, and vice versa.
- **Raw lines stay in position.** A non-blank raw line belongs to the innermost
  question indented less than it, so prose under a question travels with it
  when the question moves. Blank lines belong to whatever the next non-blank
  line belongs to. A fenced code block (```` ``` ```` or `~~~`) stays whole in
  the container where it opens, and nothing inside it is parsed.
- **File details are kept.** Line endings (`\n` or `\r\n`), the presence or
  absence of a final newline, and the original list marker all survive.
- **Missing IDs are appended** as ` <!-- q:xxxx -->` after the line's trailing
  whitespace is trimmed. If the same ID appears twice (usually from
  copy-paste), the second copy gets a fresh ID in place.
- **Moves re-indent the subtree.** Moving a question to a new depth shifts every
  line in its subtree, raw lines and answer lines included, by the
  difference. Answer content is never touched.

The fixtures in `tests/fixtures/` are the contract. `messy.md` covers front
matter, headings, trailing spaces, plain bullets, questions under plain
bullets, a multi-line answer with a blank `>` line and odd internal spacing,
code fences containing fake questions, a blockquote after a blank line, star
and plus markers, 4-space nesting and no final newline. `crlf_tabs.md` covers
Windows line endings and tab indentation.

**Known edge:** `>` lines that come after a blank line or after a question's
children are not part of its answer. They're kept as raw lines in place.

## Data model

- `Question`: `id`, `text`, `answer` (str, verbatim), `status` (open or
  answered), `children` (questions only), `items` (questions and raw lines in
  file order), `parent`. `ancestors()` follows parent pointers, so the trail
  costs O(depth).
- `Document`: the root. Holds top-level items, an ID index for O(1) lookup,
  the newline style, and `ids_assigned` (set when parsing added or replaced
  IDs).
- `RawLine`: one unrecognised line.

## Tree operations (`core.ops`)

| Operation | Behaviour |
| --- | --- |
| `add(text, parent_id=None, as_sibling_of=None)` | New open question. As a child, it goes after the last child question; at the root, after the last top-level question (so not after trailing prose). As a sibling, it goes straight after that sibling's subtree. Text must be a single non-empty line. |
| `answer(id, text)` | Replaces the answer verbatim. An empty answer removes the `>` lines. |
| `mark_answered(id)` / `reopen(id)` | Status only. |
| `set_text(id, text)` | Renames. Not bound to a key in the TUI yet. |
| `move(id, new_parent_id, index=None)` | Moves the subtree. `index` counts among the new parent's child questions. Refuses moves into itself or a descendant (`InvalidMove`). A bad index raises `IndexError` and leaves the document unchanged. |
| `reorder(id, index)` | `move` within the same parent. |
| `indent(id)` / `outdent(id)` | Become the last child of the previous sibling / the next sibling of the parent. |
| `delete(id)` | Removes the whole subtree, including raw lines nested under it. |
| `trail(id)` | Ancestors, root-most first. |
| `next_open(from_id=None)` | See below. |

### `next_open`: finish the branch, then widen

"Depth-first, finish the current branch before moving across" was ambiguous
about what happens when the current question's children run out. The rule
chosen:

1. Open descendants of the current question, in document order.
2. Then widen one ancestor at a time. Within each scope, look at the siblings
   after us, then the siblings before us, then the ancestor itself.
3. At the root this wraps round the whole document.

The current question is never returned. With no `from_id`, it returns the
first open question in document order.

```
P (open)
├─ C1 (open)
├─ C2  ← current, just answered
└─ C3 (open)
Q (open)

next_open(C2) → C3 → C1 → P → Q
```

This returns you to the question you parked children from once they're done,
rather than skipping past it. Plain pre-order was the alternative and was
rejected for that reason.

## Storage (`core.store.DocumentFile`)

- **Atomic writes:** a temp file in the same directory, flushed and fsynced,
  the original's permission bits copied, then `os.replace`. Symlinked paths are
  resolved first, so saving writes through the link instead of replacing it.
- **Conflict detection:** the store remembers the text it last read or wrote.
  `save()` raises `ExternalChange` if the disk now holds anything else, unless
  `force=True`. A missing file doesn't count as a conflict; saving recreates
  it.
- **IDs are saved on open.** If parsing had to add IDs, the file is written
  immediately, so IDs are stable for any other tool reading the file.
- **Watching:** `watch()` uses watchfiles on the parent directory (an atomic
  rename replaces the inode, so watching the file itself stops working). It
  yields only when the content differs from what we last wrote, so our own
  saves don't trigger it.

## The TUI

### Focus view (default)

The trail, the current question (bold, with a coloured bar; answered ones
show ✓ and dim), and the answer editor. Nothing else, apart from a hint in the
editor border. When the file has no questions, the view says to press `r`.

### Two modes

The spec's single-letter keys (`n`, `N`, `r`, `u`, `e`, `q`) would otherwise
be typed into the answer. So:

- Opening a question (on start, `ctrl+n`, `ctrl+d`, `u`, `enter` in the
  outline) puts the cursor in the editor.
- `esc` leaves the editor and saves. Letter keys then act as commands.
  `enter` or `i` goes back in.
- `ctrl+n`, `ctrl+d`, `ctrl+s` and `tab` are priority bindings that work in
  both modes, and are disabled while a dialog is open.

### Keys

| Key | Does |
| --- | --- |
| `n` / `N` / `r` | Park a question as a child / sibling / at the root. A one-line input pops up; `enter` saves, `esc` cancels, and you stay on the current question. In an empty file, all three park at the root. |
| `ctrl+n` | Next open question. |
| `ctrl+d` | Mark answered and go to the next open question. |
| `u` | Go up to the parent. |
| `e` | Edit the answer in `$VISUAL`, else `$EDITOR`, else `vi`. On return, one trailing newline is stripped (editors add one) and nothing else. |
| `ctrl+s` | Save. |
| `tab` | Toggle focus and outline views. |
| `q` | Save and quit. |

### Outline view

The full tree. Answered branches start collapsed unless something under them
is still open, and expand/collapse choices survive rebuilds. The current
question is underlined.

| Key | Does |
| --- | --- |
| `j` / `k`, arrows | Move. |
| `enter` | Open the question in the focus view. |
| `space` | Fold or unfold. |
| `d` | Delete; asks first if the question has children. |
| `J` / `K` | Move down / up among siblings. |
| `>` / `<` | Indent / outdent. |

`n`, `N`, `r` and `ctrl+d` apply to the highlighted question here, not the
current one.

### Saving and reloading

- **Autosave** happens after every structural change, whenever the answer
  editor loses focus, before moving to another question, and on quit.
- **External change while clean:** reload silently, keep the current question
  by ID, and show a short notice.
- **External change with unsaved edits** (an uncommitted answer or an unsaved
  document): a dialog offers `r` to reload and discard yours, or `k` to keep
  yours and overwrite the file. Nothing is written until you choose.

## Testing

`just check` runs format-check, pre-commit (ruff), mypy strict and pytest:
83 tests, passing on Python 3.12 and 3.13.

- **Round-trip:** byte-for-byte on every fixture, and for missing IDs, that
  the only change is the added comments.
- **Ops:** every operation, including insertion position around prose,
  sibling indent matching, subtree re-indenting, cycle and index errors.
- **`next_open`:** the worked example above, and a table over a deeper tree
  with answered ancestors.
- **Store:** atomic write (no temp files left, mode kept), CRLF, symlinks,
  conflict refusal, a deleted file being recreated, and a live watcher test
  that ignores our own writes but sees an external one.
- **TUI pilot:** start-up focus; letters typed into the editor not firing
  commands; park child, sibling and root; cancel parking; next open; mark
  answered; up; outline open and reorder; collapsed answered branches; delete
  confirmation; an empty file; reload when clean; and the conflict dialog.

The real `qq` command was also smoke-tested in a pseudo-terminal: an
external edit while open was reloaded, a parked question was saved under the
right parent, and `q` exited cleanly.

## Not in v1

From the spec: MCP server, LLM integration, VS Code extension, sync, multiple
files, search. Also not done:

- Renaming a question from the TUI (`ops.set_text` exists).
- Configurable keybindings.
- Remembering the current question between sessions; `qq` starts on the first
  open question.
- Undo beyond the answer editor's own.

## Notes for the MCP server

- Wrap `DocumentFile` and `core.ops` directly. Each tool call should load the
  file (or check `changed_on_disk()`), apply one operation, and `save()`.
  `ExternalChange` means the TUI or a person wrote in between; reload and
  retry rather than forcing.
- The TUI is already watching, so writes from the MCP server will appear in
  an open `qq` without further work.
- `next_open` and `trail` are the natural "what should I think about next"
  and "where am I" tools.
