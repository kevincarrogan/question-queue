# Question Queue: design

This is the record of how Question Queue works and why, written for whoever
builds the next front end (the MCP server, the VS Code extension, remote
access). The README covers how to use it; this covers how it fits together.

## What it is

An outliner for thinking things through. Questions, ideas and to-dos go into
a nested list as they come up, under whatever raised them, so you can get them
out of your head without losing your place in what you're working on.

Everything is an item: a line of text, with more text under it if it needs
it, and items nested under items. A question is just an item that ends in a
question mark, and its answer is an item underneath it (or the rest of its
text). Nothing in the tool treats questions specially.

It's a Textual TUI over a single markdown file. There is no database: the
file is the only source of truth, and it has to stay pleasant to read and edit
by hand.

## Naming

| Thing | Name |
| --- | --- |
| Product | Question Queue |
| PyPI distribution | `question-queue` |
| Import package | `questionqueue` |
| Command | `qq` |
| Queue file | `.qq/questions.md` |

The initials spell the command. `quarry` (the first working name) and `qq`
are taken on PyPI by unrelated projects; `interrobang` was considered and
dropped because it doesn't match `qq`. The names come from the first version,
which was built around questions and answers; they've stayed.

## Layout

```
src/questionqueue/
  cli.py            qq entry point and its options
  core/             no UI imports; what every front end builds on
    model.py        Item, RawLine, Document
    parser.py       markdown → Document
    serialise.py    Document → markdown
    ops.py          tree operations
    store.py        load, atomic save, conflict detection, watching, .qq lookup
    refs.py         file references like foo/bar/core.py:30
    ids.py          short ID generation
    errors.py       ItemNotFound, InvalidMove, ExternalChange
  tui/
    app.py          QQApp: modes, keys, undo, folding, autosave, reloads
    outline.py      the outline pane (subjects only)
    editor.py       the editor pane (the whole text)
    render.py       how an item is drawn in the outline
    command.py      the command line: what / and : understand
    modals.py       single-key choices, the key list
    keys.py         alt+enter support
    highlight.py    inline markdown and fenced code colouring
    app.tcss
tests/
  core/             format, ops, step, replace, ticks, next_open, store,
                    .qq lookup, references
  tui/              pilot tests against the real app, key parsing
  fixtures/         messy real-world markdown, and files in the old format
```

`core` is the boundary that matters. The TUI only ever calls `core.ops`,
`core.refs` and `DocumentFile`, and every operation takes item IDs and
returns items, never positions in the file, so a tool-calling LLM can drive
it as-is.

Runtime dependencies are Textual (with its `syntax` extra, for tree-sitter) and watchfiles. Dev dependencies are pytest,
ruff, mypy (strict) and pre-commit. Pilot tests run Textual's `run_test()`
inside `asyncio.run()`, which avoids needing pytest-asyncio.

## The markdown format

```markdown
- Where is the function to do X? <!-- q:a1b2 -->
  foo/bar/core.py:30, next to the parser.

  It's called from two places.
  - [ ] Add a test for it <!-- q:c3d4 -->
  - [x] Check the caller <!-- q:e5f6 -->
- Who's coming? <!-- q:g7h8 -->
```

### What the parser recognises

- **Item:** a list item (`-`, `*` or `+`, then a space) with some text. Its
  first line is the **subject**, which is what the outline shows. Horizontal
  rules (`- - -`, `* * *`) and a bare `- [ ]` with no text are not items;
  numbered lists aren't either.
- **Box:** `[ ] ` straight after the marker gives the item a box (open),
  `[x] ` or `[X] ` ticks it. An item without one is plain.
- **Body:** the lines straight after the subject that are indented further
  than it and aren't list items themselves, like a commit message's body.
  Blank lines inside belong to the body when more body follows, as in a
  markdown list item with several paragraphs; a blank line followed by
  shallower text ends it. A fenced code block in the body is kept whole, list
  markers and all. The body's indent is the item's content column (where the
  text starts after `- `), so code indented further keeps its indentation.
- **ID:** an HTML comment at the very end of the subject line,
  `<!-- q:… -->`. Any `[A-Za-z0-9_-]+` is accepted when reading; new IDs are
  4 random hex characters, longer only if the short ones run out. A comment
  in the middle of the text is just text.
- **Nesting:** worked out from relative indentation (tabs count as 4 columns),
  so 2-space, 4-space and tab-indented notes all parse. New lines are written
  with 2 spaces, or to match existing siblings.

Everything else is a **raw line**, kept verbatim.

**Files in the first format** (`- ? question` and `- ?x question`, with `>`
answer lines) still open. The `?` or `?x` becomes the start of the item's
text, and the `>` lines are its body. Nothing is rewritten unless you edit it.

### Round-trip fidelity

This was the hardest requirement: existing notes must survive load → save
unchanged apart from added IDs.

- **Source lines are remembered.** Each item stores the exact subject line
  (`source_subject`) and body lines (`source_body`) it was parsed from, and
  the serialiser writes them back byte for byte until something changes.
  Changing the text drops both; ticking, unticking or adding or removing the
  box drops only the subject line, so the body is left alone.
- **Raw lines stay in position.** A non-blank raw line belongs to the innermost
  item indented less than it, so prose under an item travels with it when the
  item moves. Blank lines belong to whatever the next non-blank line belongs
  to. A fenced code block outside a body stays whole in the container where it
  opens, and nothing inside it is parsed.
- **File details are kept.** Line endings (`\n` or `\r\n`), the presence or
  absence of a final newline, and the original list marker all survive.
- **Missing IDs are appended** as ` <!-- q:xxxx -->` after the line's trailing
  whitespace is trimmed. If the same ID appears twice (usually from
  copy-paste), the second copy gets a fresh ID in place.
- **Moves re-indent the subtree.** Moving an item to a new depth shifts every
  line in its subtree, body and raw lines included, by the difference. The
  text itself is never touched.

The fixtures in `tests/fixtures/` are the contract. `messy.md` covers front
matter, headings, trailing spaces, plain bullets, a multi-line body with a
blank line and odd internal spacing, code fences containing fake items,
star and plus markers, 4-space nesting and no final newline, all in the old
`?` format. `crlf_tabs.md` covers Windows line endings and tab indentation.
`missing_ids.md` covers absent and duplicate IDs.

## Data model (`core.model`)

- `Document` holds the top-level entries and an index of items by ID. It
  also records the newline style, whether the file ended with a newline, and
  whether parsing had to add IDs.
- `Item` has `id`, `text` (the subject line, then the body's lines), `kind`
  (`PLAIN` or `TODO`), `status` (`OPEN` or `DONE`), `parent`, `indent`,
  `marker`, and `items` (its children and raw lines, in file order).
  `subject` and `body` split the text; `box` is `[ ]`, `[x]` or nothing.
  `ticks` are its children with boxes, and `mixed` is true when they're
  partly done (the outline draws that as `[-]`). `ancestors()` follows parent
  pointers; `walk()` and `descendants()` go down.
- `RawLine` is any line the parser didn't recognise, kept verbatim.

A plain item is never done: ticking one gives it a box first.

**Ticks cascade.** An item with boxes under it is ticked exactly when all of
them are. Ticking or unticking an item does the same to every box under it,
and then each boxed item above it is settled to agree. Only boxes count: a
plain item has no say and stops the cascade, both ways. Partly done isn't
stored; the file keeps `[ ]`, since it isn't done, and `mixed` is worked out
when drawing. Every operation that can change what's under an item (adding,
moving, deleting, changing a box) settles the branches it touched, and only
those, so a hand-edited file that disagrees elsewhere isn't rewritten behind
your back.

## Tree operations (`core.ops`)

| Operation | Does |
| --- | --- |
| `add(text, parent_id=None, as_sibling_of=None, kind=PLAIN)` | New open item. As a child, it goes after the last child item; at the root, after the last top-level item (so not after trailing prose). As a sibling, it goes straight after that sibling's subtree. |
| `set_text(id, text)` | Replace the whole text. It can run over several lines; trailing blank lines are dropped, and a blank first line is rejected (it's the subject). |
| `set_kind(id, kind)` | Add or remove the box. Removing it reopens the item. |
| `mark_done(id)` / `reopen(id)` | Tick and untick, with the boxes under it, then settle the boxes above (see ticks, above). `mark_done` gives a plain item a box. |
| `move(id, new_parent_id, index=None)` | Move an item and its subtree. Refuses cycles; a bad index raises without changing anything. |
| `reorder(id, index)` | Move among its own siblings. |
| `indent(id)` / `outdent(id)` | Under the previous sibling / after the parent. |
| `visible(folded=())` | Items as the outline shows them, leaving out what's under folded items. |
| `step(id, down, folded=())` | Move one row up or down the outline as shown, so an item can travel into and out of branches. Down past a row with children showing makes it that row's first child. Raises `InvalidMove` at either end. This is what `shift+↑↓` uses. |
| `replace(old, new, ids, every=False, ignore_case=False)` | Literal replace in each item's text, like vim's `s/old/new/`: the first match on each line, or every one with `every` (vim's g), ignoring case with `ignore_case` (i). An item whose first line would end up blank is left alone. `replaced(text, …)` is the same on a string, for previews. |
| `delete(id)` | Remove the item, its body, everything under it and any lines nested under it. |
| `trail(id)` | Ancestors, root-most first. |
| `next_open(from_id=None)` | See below. |

### `next_open`: finish the branch, then widen

The TUI no longer works through a queue, but `next_open` stays in `core` for
the MCP server, where "what next" is a natural tool. The rule:

1. Open descendants of the current item, in document order.
2. Then widen one ancestor at a time. Within each scope, look at the siblings
   after us, then the siblings before us, then the ancestor itself.
3. At the root this wraps round the whole document.

The current item is never returned. With no `from_id`, it returns the first
open item in document order. Plain items are always open, so in practice it
finds the next item that isn't ticked.

```
P (open)
├─ C1 (open)
├─ C2  ← current, just ticked
└─ C3 (open)
Q (open)

next_open(C2) → C3 → C1 → P → Q
```

This returns you to the item you added children under once they're done,
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

## Which file plain `qq` opens (`core.store.find_queue`)

A queue lives in `.qq/questions.md`. `find_queue` walks up from the current
folder and returns the nearest `.qq` folder's file, like git finding `.git`, so
`qq` works from anywhere inside a project. The home folder's `.qq` is the global
queue and is skipped by that walk: from inside a new project, finding the
global queue would quietly put that project's items in the wrong place.
When nothing is found, `find_queue` returns a `QueueChoice` (here, or global)
and the TUI asks as its first screen: `h`, `g`, or `q` to quit without creating
anything. From the home folder itself there's nothing to choose, so the global
queue opens directly.

The command line follows the same choices: a file argument, `--here`, `-g` /
`--global`, or nothing for the lookup above. The lookup is in `core` so the MCP
server can find the same file.

## File references (`core.refs`)

Text like `foo/bar/core.py:30` in an item is a reference: a path with an
extension, `:line`, and optionally `:column`. The extension requirement keeps
times like `12:30` out, and URLs don't match. References are underlined in
the outline (not inside the editor).

The path resolves from the project folder (the folder holding `.qq`, else the
queue file's own folder; `~` and absolute paths work too), and the TUI checks
it exists before opening it. `o` in the outline, `ctrl+o` in the editor, or a
click on the underlined reference in the outline all open it. Each underlined
span carries the reference in its style's meta, which is how a click knows
what it landed on.

The editor is `$QQ_EDITOR`, else `$VISUAL`, else `$EDITOR`, else `code` if
it's installed, else `vi` (`choose_editor`). `code`, `cursor`, `codium` and
`windsurf` get `-g path:line`; `subl`, `zed` and `hx` get `path:line`;
everything else gets `+line path`, which vi, vim, nvim, nano, emacs, micro and
kak understand. Editors with their own window (`windowed`) open alongside the
TUI; anything else runs with the app suspended until you quit it.

## The TUI

### How it got here

The TUI has been reshaped by using it:

1. **v1:** a focus view and an outline view, toggled with Tab. Questions were
   `- ?` items with `>` answers. Single-letter keys parked questions, with Esc
   switching between typing an answer and giving commands. Too much to learn
   at once.
2. **Cut down** to three ctrl keys (ask, done-and-next, quit), always typing
   into the answer, with a guide on the empty screen.
3. **Drawn as the file:** the whole markdown file on screen, IDs hidden, the
   current question's answer edited in place.
4. **Outliner keys in one view:** arrows, enter and tab, OmniOutliner style.
   Moving and typing happened in the same place, so it was never clear which
   you were doing.
5. **Two panes:** a list for moving, a panel for typing, with the mode always
   visible. Still split into questions and answers.
6. **Just an outliner:** the realisation that questions and answers were
   getting in the way. Every item is text; a question is an item ending in
   "?", and an answer is an item underneath. An item's first line is its
   subject and the rest is its body, like a commit message. The format, the
   model and the TUI were rebuilt around that.
7. **Settling the keys by use:** `ctrl+j` jotting gave way to `enter` (add
   here), `n` (add at the bottom) and `m` (pick up and carry), with undo
   behind all of them. `→` edits, because that's what a hand reaches for,
   so folding moved to `tab` and `shift+tab`, as in org-mode. WASD doubles
   as the arrows, `ctrl+d` twice quits, `/` and `:` open a vim-like
   palette, ticks cascade, and references can be clicked. The palette then
   became vim's command line on the bottom line, moving you as you type
   instead of listing results over the panes, so `n` went to vim's next
   match and adding at the bottom moved to `b`. The editor lost
   its help text and gained line numbers and markdown colouring.

The earlier versions are in git history and on the project canvas.

### Two panes

- **The outline** (`tui/outline.py`, an `OptionList`) shows every item by its
  subject, indented by depth, after its number in a dim gutter, with a box if
  it has one (`[-]` when partly done), and `▸ N` when N items are folded under it. Numbers follow the
  file, so folding doesn't renumber anything. Prose and other raw lines
  aren't shown. It's for moving and arranging; its keys are commands and
  never type.
- **The editor** (`tui/editor.py`) is the selected item's whole text in one
  text area, with numbered lines and nothing else in the pane: the first
  line is the subject (in bold), the rest is the body. It flips to a blank
  item when adding, and the outline shows a blank row, with its box, where
  it will go, filling in live as you type the first line.
- **Markdown is coloured as you type.** The text area's markdown mode
  (`textual[syntax]`, which brings tree-sitter) colours headings, list
  markers and code blocks, but not inline markup or the code inside a fence.
  `tui/highlight.py` adds those: `**bold**`, `*italic*`, `` `code` ``, links
  and file references by pattern, and fenced code by parsing it with its
  language's grammar and Textual's highlight query, offset to the fence's
  rows. Highlights are byte columns, as TextArea keeps them.
- **The mode is always visible:** the focused pane has the bright border, and
  the key bar leads with OUTLINE, EDIT, NEW or MOVE and lists that mode's
  keys. Below 90 columns the panes stack (`HORIZONTAL_BREAKPOINTS`).

### Keys

`w` `a` `s` `d` are the arrow keys in the outline, and `W` `A` `S` `D` the
shift+arrows, for terminals that don't send shift with the arrows.

| In the outline | Does |
| --- | --- |
| `↑` `↓` / `j` `k` | Move. The editor shows the selected item. |
| `←` | Go to the parent. |
| `→` | Edit the item, cursor at the end of its first line. The editor is the pane to the right, and that's where a hand goes. |
| `ctrl+n` | Edit the selected item, like `→`. |
| `tab` | Fold or unfold the item, as in org-mode. |
| `shift+tab` | The whole outline in turn: top level only, one level open, all open. If what was selected is hidden, the selection moves to the item it's folded under. |
| `enter` | New item here, after this one (and its children). New items get a box. |
| `alt+enter` | New item above. (`shift+enter` too, where the terminal sends it as its own key or as ESC + enter.) |
| `b` | New top-level item at the bottom; when you're done you're back where you were. |
| `m` | Pick the item up and carry it (below). |
| `shift+↑` / `shift+↓` | Move the item one row without picking it up. |
| `shift+←` / `shift+→` | Out / in a level. |
| `space` / click the box | Tick or untick, cascading (see ticks, above). |
| `t` | Give the item a box, or take it away. |
| `x` | Delete; asks first if it has a body or items under it. |
| `u` | Undo. |
| `/` `:` | Open the command line with that already typed. |
| `n` `N` | Next or previous item with the last words found; `esc` takes the marks away. |
| `o` / click | Open the file reference in the item. |
| `?` | Every key. |

| In the editor | Does |
| --- | --- |
| typing | `enter` is a new line, `tab` indents (for code). Saves as you type; a blank first line isn't saved, and says so once. |
| `esc` / `ctrl+n` | Back to the outline. A new item is added at that point, unless it's empty. |
| `ctrl+o` | Open the file reference on the cursor's line, else the first. |

| Anywhere | Does |
| --- | --- |
| `ctrl+p` | The command line (below). Cmd+P never reaches a terminal app. |
| `ctrl+d` `ctrl+d` | Quit, as in Claude Code: the first press warns, a second within two seconds quits. It takes over the editor's delete-forward. `ctrl+q` quits straight away. |

Textual reports ESC + carriage return as plain `enter`, dropping the alt,
so `tui/keys.py` wraps its key parser to report `alt+enter` instead
(`tests/tui/test_keys.py` feeds the raw bytes through, to catch a Textual
upgrade that changes the private method it wraps). Terminal.app sends
Shift+Enter as that same sequence.

The key bar is a plain widget rather than Textual's `Footer`, which orders
keys by where they were first bound, and it changes with the mode. Each mode's
bar fits in 80 columns.

### Adding and moving

Capturing a thought without losing your place is what matters most:

- **`enter` adds where you are**, as the next sibling. A blank row appears in
  the outline straight away and fills in as you type; `esc` adds it (or adds
  nothing, if it's empty).
- **`b` adds at the bottom**, as a new top-level item, for a thought that has
  nothing to do with what you're on. Afterwards the selection goes back to
  where it was.
- **`m` picks an item up** (MOVE, in blue). `↑` `↓` carry it through the
  outline as it's shown, into and out of branches (`ops.step`); `←` `→`
  change its level; `m` or `enter` drops it; `esc` or `u` puts it back where
  it was picked up. So anything can be added roughly and placed later.
- **shift and the arrows** do the same one step at a time, with no mode.
  Terminal.app doesn't send shift with ↑ and ↓ until you map them (Settings
  → Profiles → Keyboard: `\033[1;2A` and `\033[1;2B`), which is why `m`
  came back after being dropped for shift+arrows; `W` `S` work everywhere.

### Undo

`u` undoes structural changes and edits one at a time. Before each change the
app pushes the serialised document onto a stack (200 deep) and undo parses
the last one back, so IDs survive. Editing pushes once per visit to the
editor, only if the text changed. A run of moves of the same item, with
nothing in between, is one change, so `u` puts it back where it started
(`undo_count` tells "straight after" apart). Picking an item up with `m`
starts a fresh run, so putting it back undoes only what happened since. A reload from disk clears the
stack.

### The command line

`ctrl+p` from either pane, or `/` and `:` in the outline, opens vim's command
line (`tui/command.py`) on the bottom line, in place of the key bar. There's
no list of results over the panes: what's typed moves you as you type it, the
way vim's incsearch does, from where you were to the first match after it
(round the end if need be), unfolding what it's inside. The outline marks
every match, as vim's hlsearch does, and an item matched only in its body
shows a short glimpse of that line after its subject. In the editor the match
is selected. `↓` `↑` step through the matches while the line is open; `enter`
stays; `esc`, or backspacing past the start, puts back the selection, the
folds and the cursor. After a find, `n` and `N` in the outline go on to the
next and previous match, and the marks stay until `esc`. `/` and `enter` on
their own find the last words again. A click in either pane closes the line
where it is. What it works on depends on the pane it was opened from.

| Type | In the outline | In the editor |
| --- | --- | --- |
| words | find items | find items |
| `/words` | find items | find lines in this item |
| `//words` | find items | find items |
| `:34` | item 34 (unfolding to reach it) | line 34 |
| `:34:12` | edit item 34 at line 12 | the same |
| `/old/new/` | replace in every item | replace in this item |
| `//old/new/` | replace in every item | replace in every item |

Replace needs the closing slash, so `/src/app.py` stays a search for a path;
`\/` is a literal slash. Flags follow it as in vim: `g` for every match on a
line (the first, without it) and `i` to ignore case. The text is literal, not
a pattern. Before `enter` the items that would change are marked and the line
says how many; with none, `enter` beeps. A replace is one undo.

### Saving and reloading

- **Autosave** happens one second after typing stops, after every structural
  change, before moving to another item, and on quit.
- **External change while clean:** reload silently, keep the selected item
  by ID, and show a short notice.
- **External change with unsaved edits:** a dialog offers `r` to reload and
  discard yours, or `k` to keep yours and overwrite the file. Nothing is
  written until you choose.

## Testing

`just check` runs format-check, pre-commit (ruff), mypy strict and pytest:
186 tests.

- **Format:** byte-for-byte round-trips; for files without IDs, that the
  only change is the added comments; what is and isn't an item; bodies with
  paragraphs and code; old `?` files opening; editing one item leaving the
  rest untouched.
- **Ops:** every operation, including insertion position around prose,
  sibling indent matching, multi-line text kept verbatim, ticking and box
  changes, subtree re-indenting, cycle and index errors; `step` through
  folded and unfolded branches; literal replace with its flags.
- **Ticks:** cascading down and up, partly done, plain items stopping it, and
  adding, moving, deleting and box changes settling both places.
- **`next_open`:** the worked example above, and a table over a deeper tree
  with ticked ancestors.
- **Store and lookup:** atomic write (no temp files left, mode kept), CRLF,
  symlinks, conflict refusal, a deleted file being recreated, a live watcher
  test that ignores our own writes but sees an external one, and every case
  of the `.qq` lookup.
- **References:** the pattern (including times and URLs that mustn't match),
  choosing by cursor line, path resolution, which editor is chosen and each
  editor's arguments.
- **Keys:** ESC + enter parsing as `alt+enter`, and other keys unchanged.
- **TUI pilot:** the outline never typing; moving with the editor following;
  editing and switching back, including with `→`; enter as a new line in the
  editor; saving when typing pauses; a blank first line not saved; adding
  below, above, at the bottom and with a body, the blank row filling in, and
  adding nothing; the guide in an empty file; carrying with shift+arrows and
  undoing a run of moves in one step; indent and outdent; folding; undo; ticking, `[-]`
  and the box, by key and by clicking it; deleting with and without asking; the
  command line in both panes, moving and marking as you type, stepping, `esc`
  going back, `n` and `N`, replace and its flags; the which-queue choice; reloads and the conflict
  dialog; opening references with keys and with a click; and how the outline
  draws items.

## Not done yet

Out of scope so far: MCP server, LLM integration, VS Code extension, sync,
multiple files. Next up is `qq add "…"`, to capture from the shell; a VS Code
task could then run `qq add "${relativeFile}:${lineNumber}"`. Also not done:

- Configurable keybindings.
- Remembering the selected item and folds between sessions; `qq` starts on
  the first item with everything unfolded.
- Clicking references in the editor pane (use `ctrl+o` there).

## Notes for the MCP server

- Wrap `DocumentFile` and `core.ops` directly. Each tool call should load the
  file (or check `changed_on_disk()`), apply one operation, and `save()`.
  `ExternalChange` means the TUI or a person wrote in between; reload and
  retry rather than forcing.
- The TUI is already watching, so writes from the MCP server will appear in
  an open `qq` without further work.
- Items are addressed by ID. `subject` is the one-line summary to show; `text`
  is everything. `next_open` and `trail` are the natural "what next" and
  "where am I" tools.
