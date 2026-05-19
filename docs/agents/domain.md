# Domain Docs

How engineering skills should consume this repo's domain documentation when exploring the codebase.

## Layout

This repo uses a single-context domain-doc layout.

Expected files:

- `CONTEXT.md` at the repo root for domain language, glossary, and project context
- `docs/adr/` for architectural decision records

## Before exploring

Read `CONTEXT.md` if it exists. Read relevant ADRs in `docs/adr/` when the task touches an architectural decision.

If these files do not exist, proceed silently. Do not flag their absence or create them upfront unless the user asks or a documentation-producing skill is being used.

## Vocabulary

When output names a domain concept, use the term as defined in `CONTEXT.md`. If the concept is missing, note the gap rather than inventing parallel vocabulary.

## ADR Conflicts

If a proposal or implementation contradicts an existing ADR, surface the conflict explicitly instead of silently overriding it.
