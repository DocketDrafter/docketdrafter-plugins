---
name: federal-court-rules
description: Use when an agent needs to look up, quote, summarize, cite, or reason from bundled federal court rules, including the Federal Rules of Civil Procedure, Federal Rules of Appellate Procedure, Federal Rules of Evidence, supplemental rules, selected federal district local rules, and selected ECF rules. Provides local full-corpus access with citation lookup, listing, and search.
---

# Federal Court Rules

The reader scripts automatically install the latest verified corpus on first use. After installation, lookups are local and the corpus is not checked for updates in that environment.

Use this skill when a task requires bundled federal rule text, selected federal district local rules, ECF rules, citation checking, rule lookup, or analysis grounded in the local corpus.

## Corpus Layout

All shipped data lives under `references/`.

- `references/index.json` is the master rule-set inventory. Use it, or `scripts/read_rule.py --list-rule-sets`, to discover supported courts and rule counts.
- `references/aliases.json` is the top-level alias map for core federal rules. Each rule-set directory may also have its own `aliases.json`.
- Each rule set is stored as `references/<rule-set>/index.json`, `rules.json`, `rules.html`, and usually `aliases.json`.
- Rule-set indexes include citation metadata such as `ruleSet`, `ruleId`, `title`, `citation`, `division`, `path`, `anchor`, `status`, source path, source URL, public URL, source pages, and text length where available.

Do not treat `SKILL.md` as the authoritative list of supported districts. The authoritative list is generated data in `references/index.json`.

## Coverage and currency

The corpus includes FRCP, FRAP, FRE, the Supplemental Admiralty Rules, the Supplemental Rules for Social Security Actions, and selected federal district local and ECF rules. It is intentionally useful rather than comprehensive. It does not include the Federal Rules of Criminal Procedure, Federal Rules of Bankruptcy Procedure, Supreme Court Rules, circuit local rules, every federal district, every appendix or filing manual, standing or general orders, or judge-specific individual practices.

Each rule-set index records its own effective-through date and official source URL where available. Dates vary by court. Always identify the relevant rule set and its bundled effective date, and verify the live court website before relying on a rule for a filing, deadline, formatting requirement, or other time-sensitive procedural decision.

Development sources and ingestion tools are maintained outside the installable plugin under `tools/federal-court-rules/` in the public repository. They are not available at runtime.

## Lookup Script

Use `scripts/read_rule.py` for citation resolution, listing, and search. The script resolves `references/` relative to its own file.

Before the first command, locate the reader. In Claude Cowork, the Skill tool's displayed host-side base path may not be visible inside the workspace VM. Marketplace plugins are normally under `.remote-plugins`, while standalone skills are normally under `.claude/skills`; do not guess either path. Resolve it once:

```bash
SCRIPT="scripts/read_rule.py"
if [ ! -f "$SCRIPT" ]; then
  SCRIPT="$(find /sessions -type f -path '*/.remote-plugins/*/skills/federal-court-rules/scripts/read_rule.py' -print -quit 2>/dev/null)"
fi
if [ -z "$SCRIPT" ] || [ ! -f "$SCRIPT" ]; then
  SCRIPT="$(find /sessions -type f -path '*/skills/federal-court-rules/scripts/read_rule.py' -print -quit 2>/dev/null)"
fi
if [ -z "$SCRIPT" ] || [ ! -f "$SCRIPT" ]; then
  echo "Could not locate the installed Federal Court Rules reader." >&2
  exit 1
fi
```

Use `python "$SCRIPT" ...` for all commands. Do not `cd` to an assumed `.claude/skills` or `.remote-plugins` path.

### Read Rules

```bash
python "$SCRIPT" "FRCP 26"
python "$SCRIPT" "FRAP 4"
python "$SCRIPT" "FRE 403"
python "$SCRIPT" "Fed. R. Evid. 801"
python "$SCRIPT" "Supplemental Rule G"
python "$SCRIPT" "Social Security Rule 1"
python "$SCRIPT" "SDNY Local Civil Rule 7.1"
python "$SCRIPT" "SDNY ECF Rule 23.4"
python "$SCRIPT" "S.D. Tex. L.R. 10"
python "$SCRIPT" "E.D. Tex. CV L.R. 7"
python "$SCRIPT" "D.N.J. L.Civ.R. 7.1"
python "$SCRIPT" "D.N.J. L.Cr.R. 5.1"
python "$SCRIPT" "E.D. Pa. L. Civ. R. 7.1"
python "$SCRIPT" "E.D. Pa. L.Cr.R. 12.1"
python "$SCRIPT" "M.D. Pa. L.R. 7.6"
python "$SCRIPT" "W.D. Pa. LCvR 56"
python "$SCRIPT" "W.D. Pa. LCrR 32"
```

Plain text is the default. Each read prints a banner with citation, title, rule set, source page range when available, character count, and public source URL when available.

Use `--format markdown` or `--format json` when structured output is helpful.

```bash
python "$SCRIPT" "Rule 56" --format json
python "$SCRIPT" "D.N.J. L.Civ.R. 7.1" --format markdown
python "$SCRIPT" "FRCP 4" --max-bytes 4000
```

Bare numeric rules default to the main FRCP set. Use explicit forms for FRAP, supplemental rules, and local rules when there is any risk of collision.

### Discover Rule Sets

```bash
python "$SCRIPT" --list-rule-sets
python "$SCRIPT" --list
python "$SCRIPT" --list frcp
python "$SCRIPT" --list frap
python "$SCRIPT" --list fre
python "$SCRIPT" --list dnj-local-rules
```

`--list` defaults to FRCP. For local rules, pass the exact rule-set id from `--list-rule-sets` or a supported shorthand alias such as `sdny-local`, `sdny-ecf`, or `dnj-local`.

### Search

```bash
# Search all rule sets
python "$SCRIPT" --search "proportional to the needs of the case"

# Search one rule set
python "$SCRIPT" --search "electronic filing" dnj-local-rules
python "$SCRIPT" --search "unfair prejudice" fre
python "$SCRIPT" --search "one-inch margins" txwd-local-rules

# Search titles only
python "$SCRIPT" --search "briefs" frap --titles-only

# Regex + case-sensitive
python "$SCRIPT" --search "\bMDL\b" frcp --regex --case-sensitive
```

Prefer `--search` over direct grep because results are returned in rule-citation coordinates.

## Citation Workflow

1. If the user gives a bundled citation, resolve it with `python "$SCRIPT" "<citation>"`.
2. If lookup fails, run `--list-rule-sets`, then inspect the likely corpus with `--list <rule-set>`.
3. For topic-based discovery, use `--search "<phrase>"` and scope to a rule set when the jurisdiction is known.
4. Cite the `publicUrl` emitted by the reader. For PDF-backed rules, this is the official PDF URL with the exact starting page fragment (`#page=N`). Never replace it with a general U.S. Courts or court rules landing page.
5. If a rule spans multiple PDF pages, state the bundled page range shown in the reader banner while linking to the exact starting page.
6. Quote only the exact rule language needed.
7. Surface status metadata such as repealed, reserved, withdrawn, transferred, or omitted when relevant.
8. State the effective date for the specific corpus before treating text as current.
9. Use separate sources for statutes, standing orders, judge individual practices, advisory committee notes, case law, ECF manuals, appendices, and district-specific procedures not included in the bundled corpora.

## Grounding requirements

- Search and list output are discovery aids, not substantive authority. Read the full bundled rule before stating its requirements, exceptions, deadlines, remedies, or consequences.
- Distinguish national rules from local rules and do not silently transfer a local requirement to another court.
- Cite the rule set and rule number precisely, link to the reader's exact official PDF page URL when available, and include the bundled effective date when currency matters.
- Do not claim that the plugin covers all federal court rules or all procedures for a bundled district.
- Check live court sources for amendments, standing orders, general orders, ECF requirements, appendices, and the assigned judge's individual practices before filing-sensitive advice.
- Treat no search matches as a valid discovery result, not proof that no relevant rule exists. Try synonyms, list the likely rule set, and consult sources outside this corpus where appropriate.
