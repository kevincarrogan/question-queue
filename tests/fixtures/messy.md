---
title: Trip notes
---

# Trip notes

Some prose before anything.   
It has trailing spaces on the line above, and a [link](https://example.com).

- a plain bullet, not a question
- ? Why does the opening drag? <!-- q:0a0a -->
  > Because it starts with definitions.
  >
  >   Indented second paragraph,  with  odd   spacing.  
  > > a nested quote inside the answer
  continuation prose that belongs to the question
  - plain sub-bullet
    - ? A question under a plain bullet <!-- q:0b0b -->
  - ?x Should I cut the definitions? <!-- q:0c0c -->
    > Yes.

    > This quote is after a blank line, so it is not an answer.

  ```python
  - ? this is code, not a question
  x = 1

  y = 2
  ```
  - ? After the fence <!-- q:0d0d -->

## Second section

* ? Star marker question <!-- q:0e0e -->
    + ? Four-space nested with plus <!-- q:0f0f -->
        > Deep answer
            - ? Twelve spaces deep <!-- q:1a1a -->

- ?not a question (no space)
- ?? also not a question
- ?xylophone is not answered syntax
-  ? two spaces before the mark
- ?   
~~~
- ? tilde fenced
~~~
> a top-level blockquote that is not an answer
- ? Last one, no trailing newline <!-- q:1b1b -->