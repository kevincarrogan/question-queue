# Question Queue (`qq`)

Think through a problem by asking yourself questions and answering them in
your own voice. Questions nest under the questions that raised them; you work
on one at a time and park new ones as they occur to you.

A plain markdown file is the only storage:

```markdown
- ? How should the essay open? <!-- q:a1b2 -->
  > Start with the story, it's concrete.
  - ? Which anecdote exactly? <!-- q:c3d4 -->
  - ?x Does it need background first? <!-- q:e5f6 -->
    > No, link out instead.
- ? Who's the audience? <!-- q:g7h8 -->
```

- `? ` marks an open question, `?x ` an answered one. Any list marker works.
- Answers are the `>` lines directly under a question, stored verbatim.
- Every question gets a short ID comment, added on load if it's missing.
- Every other line in the file is left exactly as it was.

## Use

```sh
just setup
uv run qq notes.md     # created if it doesn't exist
```

**Focus view** (the default): the trail of parent questions, the current
question, and its answer. Opening a question puts you in the answer editor;
`esc` leaves it, and `enter` or `i` goes back in.

| Key | Where | Does |
| --- | --- | --- |
| `n` / `N` / `r` | outside the editor | park a question as a child / sibling / at the root |
| `u` | outside the editor | go up to the parent |
| `e` | outside the editor | edit the answer in `$VISUAL` / `$EDITOR` |
| `q` | outside the editor | quit |
| `ctrl+n` | anywhere | next open question |
| `ctrl+d` | anywhere | mark answered, go to the next open question |
| `ctrl+s` | anywhere | save |
| `tab` | anywhere | switch between focus and outline |

**Outline view**: the whole tree, with answered branches collapsed. `j`/`k`
or the arrow keys move; `enter` opens a question; `space` folds;
`d` deletes (asking first if it has children); `J`/`K` reorder;
`>`/`<` indent and outdent.

"Next open" finishes the branch you're in before moving across: it looks at
the current question's children first, then its siblings, then goes back to
the parent you parked them from, widening one level at a time.

The file is saved on every structural change and when you leave the editor,
always by writing a temp file and renaming it. If something else edits the
file while `qq` is open, it reloads; if you have unsaved edits, it asks first.

## Layout

- `src/questionqueue/core/`: the model, parser, serialiser, tree operations
  and file store. No UI imports, so other front ends can build on it.
- `src/questionqueue/tui/`: the Textual app.

Run `just` for the development recipes; `just check` is the full gate.
