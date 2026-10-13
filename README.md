# Question Queue (`qq`)

An outliner for thinking things through: get questions, ideas and to-dos out
of your head as they come up, nest them under whatever raised them, and keep
working on the thing in front of you.

The storage is a plain markdown file, a nested list:

```markdown
- Where is the function to do X? <!-- q:a1b2 -->
  foo/bar/core.py:30, next to the parser.

  It's called from two places.
  - [ ] Add a test for it <!-- q:c3d4 -->
  - [x] Check the caller <!-- q:e5f6 -->
- Who's coming? <!-- q:g7h8 -->
```

- Every list item is an item. Its first line is the subject, which is what the
  outline shows; the indented lines under it are the rest of it, like a
  commit message's body. Blank lines and code fences can sit inside.
- `[ ] ` gives an item a box, `[x] ` ticks it. An item with boxes under it is
  ticked when all of them are; when only some are, the outline shows `[-]`
  (the file keeps `[ ]`, since it isn't done).
- Every item gets a short ID comment, added on load if it's missing.
- Every other line in the file is left exactly as it was, and so is every
  item you haven't changed. Files from the first version (`- ? question`
  with `> answer` lines) open as items whose text starts with `?`.

## Use

```sh
just setup
uv tool install --editable .   # puts qq on your PATH

qq             # the queue for this folder (see below)
qq notes.md    # a specific file, created if it doesn't exist
qq --here      # start or open the queue in this folder
qq -g          # your global queue, ~/.qq/questions.md
```

Plain `qq` looks for a `.qq` folder in the current folder and its parents, the
way git finds `.git`, and opens `.qq/questions.md` inside it. If there isn't
one, the first screen asks: `h` starts a queue in this folder, `g` uses your
global one. In a new project, that's `qq`, then `h`, and you're asking
questions. From your home folder, `qq` goes straight to the global queue.

Two panes: the **outline** on the left is for moving around and arranging
(keys there are commands and never type), and the **editor** on the right is
the selected item's whole text, where you type. The pane with the bright
border has the focus, and the key bar starts with the mode: OUTLINE, EDIT,
NEW or MOVE. Below 90 columns the panes stack.

`w` `a` `s` `d` work as the arrow keys in the outline, and with shift as
shift+arrows.

| In the outline | Does |
| --- | --- |
| `↑` `↓` / `j` `k` | Move between items. The editor shows the selected one. |
| `←` | Go to the parent. |
| `→` | Edit the item: the editor is the pane to the right. The cursor starts at the end of its first line. |
| `tab` | Fold or unfold the item, as in org-mode. A folded item shows `▸ N` for the N items under it. |
| `shift+tab` | Fold or unfold everything, in turn: top level only, one level open, all open. |
| `enter` | New item here, after this one (and everything under it), with a box. It appears in the outline straight away and fills in as you type on the right; `esc` when you're done. |
| `alt+enter` | New item above. (`shift+enter` too, where the terminal sends it as its own key or as ESC + enter.) |
| `n` | New top-level item at the bottom. When you're done you're back on the item you were on. |
| `m` | Pick the item up (with everything under it): `↑` `↓` carry it through the outline as it's shown, into and out of branches, and `←` `→` change its level. `m` or `enter` drops it; `esc` or `u` puts it back. |
| `shift+↑` / `shift+↓` | Move the item one row without picking it up. |
| `shift+←` / `shift+→` | Out / in a level. |
| `ctrl+n` | Edit the selected item, like `→`. |
| `space` | Tick or untick. A plain item gets a box when you tick it. Ticks cascade: down to the boxes under it, and up, so a parent is ticked once all its boxes are and shows `[-]` while only some are. A plain item in between stops the cascade. |
| `t` | Give the item a box, or take it away. |
| `x` | Delete; asks first if there's more to it or items under it. |
| `u` | Undo the last change: adding, deleting, moving, ticking or editing. A run of moves of one item is one change, so `u` puts it back where it started. |
| `ctrl+p` / `/` / `:` | The palette (see below), with `/` or `:` already typed for those two keys. |
| `o` | Open the first file reference in the item, like `src/app.py:30`, at that line in your editor. Clicking an underlined reference in the outline does the same. The editor is `$QQ_EDITOR`, else `$VISUAL`, else `$EDITOR`, else VS Code (`code -g`) if it's installed, else vi. VS Code, Cursor, Zed and Sublime open alongside; a terminal editor takes over until you quit it. |
| `?` | Show every key. |

| In the editor | Does |
| --- | --- |
| typing | The first line, in bold, is what the outline shows; `enter` starts the next line, `tab` indents (for code). Lines are numbered, and markdown is coloured as you type, including the code in a fenced block by its language. It saves as you type. A blank first line isn't saved. |
| `esc` / `ctrl+n` | Back to the outline. For a new item, that's when it's added; leave it empty to add nothing. |
| `ctrl+o` | Open the file reference on the cursor's line. |
| `ctrl+p` | The palette, working on this item (see below). |

**The palette** (`ctrl+p`, like VS Code's quick open with vim's command
line in it) works on whatever pane you opened it from:

| Type | In the outline | In the editor |
| --- | --- | --- |
| `/words` | find items with all the words, anywhere in their text | find lines in this item |
| `//words` | the same | find items |
| `:34` | go to item 34 | go to line 34 |
| `:34:12` | edit item 34 at line 12 | the same |
| `/old/new/` | replace in every item | replace in this item |
| `//old/new/` | the same | replace in every item |

A replace needs the closing slash, so a search like `/src/app.py` finds the
path as it is. Without flags it replaces the first match on each line; add
`g` for every match and `i` to ignore case (`/old/new/gi`). The text is
literal, not a pattern. The palette lists what will change before `enter`,
and `u` undoes it. Plain words with no `/` find items, wherever you are.

`ctrl+d` twice quits from anywhere, as in Claude Code: the first press warns, and a second within two seconds quits. (`ctrl+q` quits straight away.)

Text saves a second after you stop typing, and everything else saves
straight away, always by writing a temp file and renaming it. If something
else edits the file while `qq` is open, it reloads; if you have unsaved edits,
it asks first.

## Layout

- `src/questionqueue/core/`: the model, parser, serialiser, tree operations
  and file store. No UI imports, so other front ends can build on it.
- `src/questionqueue/tui/`: the Textual app.

Run `just` for the development recipes; `just check` is the full gate.
