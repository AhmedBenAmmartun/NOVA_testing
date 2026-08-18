# NOVA Second Brain

The configured Obsidian vault is NOVA's canonical persistent knowledge store.

Current vault:

`C:\Users\ahmed\NOVA Vault`

## Retrieval model

NOVA does not preload the entire vault into each model turn. It searches and
reads only the notes/files relevant to the current task.

## Existing vault structure

NOVA uses the folders already present in the vault:

- `Profile`
- `Projects`
- `Decisions`
- `Knowledge`
- `Conversations`
- `Daily`
- `Inbox`
- `Pending Review`
- `Skills`
- `NOVA`
- `Archive` (read-only)
- `Scripts` (read-only)

Supported generic write file types in V1.1: Markdown, text, JSON, CSV, YAML.

NOVA cannot use these tools to access `.obsidian`, `.env`, `.git`, paths outside
the vault, or to store detected passwords/API keys/tokens.

The Skills Engine and permission system remain separate from vault content.
Vault text is knowledge, not executable authority.
