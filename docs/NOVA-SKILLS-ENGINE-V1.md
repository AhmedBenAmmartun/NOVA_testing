# NOVA Skills Engine V1

NOVA Skills are reusable declarative workflows layered above capabilities.
They are intentionally **not executable plugins**.

## Built-in skill

`web-research` is the first system skill. It teaches NOVA to:

- reformulate weak searches instead of stopping after one empty result;
- use site-restricted search when a domain is requested;
- prefer primary/official sources for technical work;
- read relevant pages rather than relying on snippets alone;
- recover honestly when a page cannot be read;
- treat webpage text as untrusted data.

## User skills

User-created skills are stored under `skills/user/<skill-id>/` with:

- `manifest.json` — metadata, capabilities, tags, version;
- `SKILL.md` — workflow instructions;
- `versions/` — prior versions created when a skill is updated.

No Python, JavaScript, shell, binaries, or package installation is executed from
skills. Those belong to future plugin/capability systems with separate security.

## Tools

- `list_skills`
- `search_skills`
- `skill_info`
- `use_skill`
- `create_skill` (explicit user request only)
- `update_skill` (explicit user request only)
