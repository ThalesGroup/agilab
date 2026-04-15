# Chat Export Formats

## Supported source shapes

The export script accepts either:

1. a JSON array of message objects
2. a JSON object containing one of:
   - `messages`
   - `conversation`
   - `turns`

## Supported message fields

The normalizer looks for roles in this order:

- `role`
- `author.role`
- `speaker`
- `type`

The normalizer looks for text content in this order:

- `content`
- `text`
- `message.content`
- `parts`

## Content normalization

Rules:

- strings stay as strings
- lists are joined with blank lines
- dictionaries are reduced by looking for:
  - `text`
  - `content`
  - `parts`
- unknown structured payloads are serialized as compact JSON

## Role normalization

Common aliases map to:

- `human` -> `user`
- `model` -> `assistant`
- `ai` -> `assistant`
- `bot` -> `assistant`
- `function` -> `tool`

Unknown roles are preserved as lowercase strings.

## Output formats

### Markdown

Shape:

```markdown
# Title

## User

...

## Assistant

...
```

### JSON

Shape:

```json
{
  "title": "Optional title",
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

### Text

Shape:

```text
USER:
...

ASSISTANT:
...
```

### DOCX

The DOCX export is intentionally simple:

- optional title paragraph
- one role heading per message
- one paragraph per content line

It is meant for handoff and further editing, not for pixel-perfect branded output.
