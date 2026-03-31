---
name: chat-export
description: Export chat transcripts or conversation JSON into clean Markdown, JSON, or plain-text artifacts. Use this skill when a user wants a reusable export of a chat thread, needs a deterministic transcript cleanup, or wants a conversation converted into a file-oriented format for reports, prompts, docs, or downstream tooling.
---

# Chat Export

## Overview

Use this skill to turn a chat transcript into a reusable artifact with stable structure.
Prefer the bundled script for file-based exports and repeated transformations.

## When to use

- Export a conversation to `markdown`, `json`, `text`, or `docx`
- Normalize a messy chat JSON into a clean message list
- Remove empty turns or system turns for downstream use
- Prepare a conversation for docs, prompts, reports, or archival

## Workflow

1. Identify the source shape.
   - If the user gives a JSON file, use the script.
   - If the user only provides pasted transcript text, transform it directly in the response unless they explicitly want files created.
2. Pick the target format.
   - `markdown` for readable artifacts
   - `json` for downstream tooling
   - `text` for simple archival or prompt packs
   - `docx` for handoff into report workflows
3. Normalize the messages.
   - Keep only meaningful turns
   - Standardize roles to `system`, `user`, `assistant`, or `tool`
   - Collapse structured content into plain text when needed
4. Export deterministically.
   - Use `scripts/export_chat.py` for file-based exports
   - Read `references/formats.md` if the input schema is unclear

## Quick start

For a JSON conversation file:

```bash
python scripts/export_chat.py input.json --format markdown --output chat.md
python scripts/export_chat.py input.json --format json --output chat.normalized.json
python scripts/export_chat.py input.json --format text --output chat.txt
python scripts/export_chat.py input.json --format docx --output chat.docx --title "Chat Export"
```

Useful flags:

- `--title "My Export"` adds a document title
- `--include-system` keeps system turns
- `--include-empty` keeps empty messages

## Input expectations

The script accepts:

- a top-level list of message objects
- or a top-level object with one of:
  - `messages`
  - `conversation`
  - `turns`

Each message can provide content via common fields such as:

- `content`
- `text`
- `message.content`
- `parts`

See `references/formats.md` for the accepted shapes and normalization rules.

## Output rules

- Markdown uses a readable heading plus one section per turn
- JSON emits a normalized list of `{role, content}`
- Text emits a linear transcript with `ROLE:` prefixes
- DOCX emits a simple report-style transcript with a title and one heading per turn

## Resources

### `scripts/export_chat.py`

Deterministic CLI export tool for JSON-based chat data.

### `references/formats.md`

Accepted source shapes, role normalization, and output conventions.
