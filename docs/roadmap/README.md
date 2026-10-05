# ModelCompass Roadmap

Planning and progress tracking for ModelCompass, organized as a three-tier
hierarchy: **Milestone → Story → Task**.

## Hierarchy & vocabulary

| Tier          | Meaning                                                                                                       | Lives in                                                |
|---------------|---------------------------------------------------------------------------------------------------------------|---------------------------------------------------------|
| **Milestone** | A large, strategic initiative / development direction (e.g. the generic implementation effort).               | A folder `docs/roadmap/{NNNN}-{milestone-slug}/`.       |
| **Story**     | One deliverable unit of a milestone (e.g. "AWS Bedrock Backend"). Listed in the milestone's `## Stories` table. | A subfolder `…/{TT.t}-{story-slug}/` with a `README.md`. |
| **Task**      | An atomic, implementable spec (one file, one set of classes/tests). Listed in the story's `## Tasks` table. | A file `…/{TT.t}-{story-slug}/{NN}-{task-slug}.md`.   |

A *task* is part of a *story*; a *story* is part of a *milestone*.

## File & folder convention

```
docs/roadmap/
  README.md                              ← this index + convention
  {NNNN}-{milestone-slug}/               ← MILESTONE
    plan.md                              ← milestone spec; opens with a `## Stories` table
    status.md                            ← progress tracker (optional); `## Current status` table
    {TT.t}-{story-slug}/                 ← STORY
      README.md                          ← story spec; opens with a `## Tasks` table
      {NN}-{task-slug}.md                ← TASK spec
```

- `{NNNN}` - zero-padded milestone number (`0001`, `0002`, …).
- `{TT.t}` - story number, carried from the milestone's `## Stories` table (e.g. `03.2`, `06.1`, `08.0`).
- `{NN}` - zero-padded task order (`01`, `02`, …).
- Slugs are kebab-case.

### Heading vocabulary

- A milestone's `plan.md` lists its stories under a `## Stories` heading (table column: `Story`).
- A story's `README.md` lists its tasks under a `## Tasks` heading.

### Linking convention

When a document references another **specific** document, use an
absolute-from-repo-root Markdown link:

```
[docs/roadmap/0001-generic-implementation/plan.md](/docs/roadmap/0001-generic-implementation/plan.md)
```

- Always a leading `/` (repo root), never relative `../../` chains.
- **Template** paths (containing `{` / `}`, e.g. `` `{NN}-{task-slug}.md` ``) stay as
  backtick code spans, not links.
- Run `python scripts/check_doc_links.py docs/` (or the `/link-check` skill) to verify every
  link target and `#heading-anchor` resolves. The `doc_link_check` hook runs it on edits.

## Milestones

| #    | Milestone                                                             | Spec                                             | Status                                               |
|------|-----------------------------------------------------------------------|--------------------------------------------------|------------------------------------------------------|
| 0001 | Generic working implementation (CLI, project structure, backend, ...) | [plan.md](./0001-working-implementation/plan.md) | [status.md](./0001-working-implementation/status.md) |
