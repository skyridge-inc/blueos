# skynet — Agent Guidelines

## Codebase Analysis Prep (READ FIRST)

**Before doing any non-trivial analysis of the existing code (audits,
architecture review, cross-file refactors, "where is X used?" surveys,
etc.), regenerate the codebase index:**

```bash
bunx repomix@latest
```

This writes a single consolidated XML snapshot of the entire repository
to `./repomix-output.xml`. Read that file as your primary index of the
codebase — it gives you the complete file tree, file contents, and
dependency relationships in one self-contained document, which is far
more efficient than recursive Glob/Grep traversal for broad questions.

**Workflow:**

1. Run `bunx repomix@latest` (takes a few seconds, idempotent).
2. Read `./repomix-output.xml` for the global picture.
3. Use targeted Read/Grep/Glob only for files the index points you to.

**When to skip the index** — for narrow, targeted edits where you
already know the file and line you're modifying, the regenerate-and-read
overhead isn't worth it.

**Keep the index fresh** — if you've made non-trivial edits and need to
re-analyze, re-run `bunx repomix@latest` so the snapshot reflects your
changes. The output file is gitignored / regenerated on demand.

<!-- BACKLOG.MD MCP GUIDELINES START -->

<CRITICAL_INSTRUCTION>

## BACKLOG WORKFLOW INSTRUCTIONS

This project uses Backlog.md MCP for all task and project management activities.

**CRITICAL GUIDANCE**

- If your client supports MCP resources, read `backlog://workflow/overview` to understand when and how to use Backlog for this project.
- If your client only supports tools or the above request fails, call `backlog.get_backlog_instructions()` to load the tool-oriented overview. Use the `instruction` selector when you need `task-creation`, `task-execution`, or `task-finalization`.

- **First time working here?** Read the overview resource IMMEDIATELY to learn the workflow
- **Already familiar?** You should have the overview cached ("## Backlog.md Overview (MCP)")
- **When to read it**: BEFORE creating tasks, or when you're unsure whether to track work

These guides cover:
- Decision framework for when to create tasks
- Search-first workflow to avoid duplicates
- Links to detailed guides for task creation, execution, and finalization
- MCP tools reference

You MUST read the overview resource to understand the complete workflow. The information is NOT summarized here.

</CRITICAL_INSTRUCTION>

<!-- BACKLOG.MD MCP GUIDELINES END -->
