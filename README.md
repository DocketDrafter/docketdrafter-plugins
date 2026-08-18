<p align="center">
  <a href="https://docketdrafter.com">
    <img src="assets/docketdrafter-logo.svg" alt="DocketDrafter" width="96">
  </a>
</p>

<h1 align="center">DocketDrafter Legal Skills for Claude</h1>

<p align="center">
  Open-source legal research tools for Claude Cowork and Claude Code
</p>

This repository contains free legal-research plugins and the standalone CourtListener MCP extension from [DocketDrafter](https://docketdrafter.com).

## Install in Claude Cowork

### CourtListener by DocketDrafter

**Video tutorial: installation, setup, and use**

[![How to Install the DocketDrafter CourtListener Plugin for Claude Cowork and Claude Code](assets/courtlistener-cowork-tutorial.png)](https://youtu.be/yw3V6mhgk1U)

[Watch on YouTube →](https://youtu.be/yw3V6mhgk1U)

1. Get a free API key at [courtlistener.com/profile/api-token](https://www.courtlistener.com/profile/api-token/).
2. [Download `courtlistener.mcpb`](https://github.com/DocketDrafter/docketdrafter-plugins/releases/latest/download/courtlistener.mcpb).
3. Double-click the downloaded file. If macOS asks which app to use, choose **Claude**.
4. Click **Install**, paste your API key, and leave the library folder as `~/Documents/CourtListener Library` unless you want your research saved elsewhere.
5. Save and enable the extension, then start a new conversation.

After updating CourtListener, quit and reopen Claude and start a new conversation. Existing conversations retain the tool definitions with which they started.

### Statutes and court rules

> [!IMPORTANT]
> **Allow corpus downloads before using these plugins.** In Claude, open
> **Settings → Capabilities → Domain allowlist**, then either:
>
> - Add `public-corpora.docketdrafter.com` under **Additional allowed domains**
>   (recommended); or
> - Change the domain allowlist dropdown to **All domains**.
>
> Without one of these settings, Claude Cowork cannot download the legal corpus and the plugin
> will not work. If **All domains** is already selected, you do not need to add the hostname.

![Claude Settings showing public-corpora.docketdrafter.com under Additional allowed domains](assets/claude-corpus-domain-allowlist.png)

1. Open **Customize** in Claude Cowork and select **Plugins**.
2. Add a marketplace from a repository.
3. Enter `DocketDrafter/docketdrafter-plugins`.
4. Install and enable the plugins you want.

The U.S. Code, New York Laws, Florida Laws, Indiana Laws, Illinois Laws, Ohio Laws, and Federal Court Rules plugins require no API keys. On first use, each downloads and verifies its corpus from `public-corpora.docketdrafter.com`; afterward, it uses the installed local copy.

> **First-time setup note — if you see "Failed to add marketplace," nothing is actually
> broken.** Our plugin catalog is large, and Claude sometimes stops waiting before it finishes
> loading, but loading continues in the background. Wait about one minute, reopen
> **Customize → Plugins**, and check whether **DocketDrafter** appears in your marketplace
> list. If it does not, repeat the add steps. This issue only affects the initial marketplace
> addition; installation, updates, and everyday use are unaffected.

## Install in Claude Code

```text
/plugin marketplace add DocketDrafter/docketdrafter-plugins
/plugin install us-code@docketdrafter
/plugin install ny-laws@docketdrafter
/plugin install fl-laws@docketdrafter
/plugin install in-laws@docketdrafter
/plugin install il-laws@docketdrafter
/plugin install oh-laws@docketdrafter
/plugin install federal-court-rules@docketdrafter
```

Install any plugins you want to use.

**CourtListener by DocketDrafter in Claude Code.** Get a free API key at
[courtlistener.com/profile/api-token](https://www.courtlistener.com/profile/api-token/), then:

```bash
git clone https://github.com/DocketDrafter/docketdrafter-plugins.git
claude mcp add courtlistener \
  --env COURTLISTENER_API_KEY=your-api-key \
  -- uv run --directory docketdrafter-plugins/plugins/courtlistener/mcp server.py
```

Requires Python 3.10+ and [UV](https://docs.astral.sh/uv/). Research is saved to
`~/Documents/CourtListener Library` (set `COURTLISTENER_DATA_DIR` to change it). The key is
stored in Claude Code's local MCP configuration; the desktop extension instead keeps it in
your operating system's keychain.

**Corpus sources and updates.** This marketplace contains only the lightweight reader skills.
The canonical, version-controlled corpus data and the scripts used to build it are public in
[docketdrafter-plugin-content](https://github.com/DocketDrafter/docketdrafter-plugin-content).
On first use, each reader resolves the latest reviewed corpus release and downloads a
checksum-verified, immutable artifact from DocketDrafter's public corpus bucket. Once installed
in an environment, that corpus remains local and is not automatically refreshed. A fresh Cowork
session receives the latest published corpus without requiring a skill or marketplace update.

## Available plugins

### Federal Court Rules

Look up, search, quote, and compare 2,570 rules across 28 bundled rule sets without network access or an API key. Coverage includes the Federal Rules of Civil Procedure, Federal Rules of Appellate Procedure, Federal Rules of Evidence, supplemental Admiralty and Social Security rules, and selected district local and ECF rules from Arizona, California, Florida, Illinois, New Jersey, New York, Pennsylvania, and Texas.

The corpus is intentionally selected rather than comprehensive, and each rule set has its own effective-through date. It does not include the Federal Rules of Criminal Procedure, Federal Rules of Bankruptcy Procedure, every district, standing orders, or judge-specific practices. Verify the live court website before relying on a rule for a filing, deadline, or other time-sensitive procedural requirement.

### New York Laws

Look up and search New York statutes, the New York State Constitution, the New York City Administrative Code, and selected New York court rules using a downloaded local corpus. Core research works without network access or an API key. The statutory corpus was refreshed August 6, 2026; the bundled NYC Administrative Code is current through amendments effective May 17, 2026, and the court-rule snapshots were generated June 27, 2026. The corpus omits annotations, historical credits, and other editorial material; Title 22 NYCRR coverage is limited to the court-rule sources described by the skill.

### Florida Laws

Look up and search Florida Statutes, the Florida Constitution, and statewide Florida court rules using a downloaded local corpus. The statutes and Constitution were refreshed August 2026 from official Florida Legislature and Florida Senate sources. The corpus omits statutory and constitutional annotations; verify live sources before relying on time-sensitive law or procedural rules.

### Indiana Laws

Look up and search the Indiana Code and Indiana Constitution using a downloaded local corpus. Core research works without network access or an API key. The statutory corpus was retrieved August 10, 2026, from the Indiana General Assembly's 2026 Code publication and contains 83,148 sections across Titles 1–37, including Title 7.1. The bundled Constitution is the General Assembly's publication as amended through 2024. The corpus omits annotations and other editorial material; verify live official sources before relying on time-sensitive law.

### Illinois Laws

Look up and search 72,163 sections across 2,813 Illinois Compiled Statutes Acts and 390 Illinois Supreme Court Rules using a downloaded local corpus. Core research works without network access or an API key. The ILCS corpus is the newest official static ILGA snapshot available as of August 12, 2026: it was updated November 21, 2025, with Public Acts through 104-433. The Supreme Court Rules are from the official compiled PDF current May 29, 2026. Recent enactments may not yet appear in the ILCS snapshot, and rules may change; verify live official sources for time-sensitive matters.

### Ohio Laws

Look up and search 33,220 sections of the Ohio Revised Code and 227 provisions of the Ohio Constitution using a downloaded local corpus. Core research works without network access or an API key. The corpus was retrieved August 13, 2026, from the official Ohio Laws website maintained by the Ohio Legislative Service Commission and preserves effective dates, latest-legislation metadata, official section links, and authenticated PDF links where available. The Revised Code is updated continuously; verify the live official source before relying on time-sensitive law.

### U.S. Code

Look up, search, quote, list, and compare U.S. Code sections using a downloaded local corpus derived from the Office of the Law Revision Counsel preliminary release. Core research works without network access or an API key.

The corpus was checked August 6, 2026. The latest bulk release available on that date was current through Public Law 119-102, July 12, 2026. It includes statutory section text but omits source credits, amendment notes, effective-date notes, and other editorial material.

### CourtListener

Search CourtListener opinions and RECAP dockets, download public court materials, and reuse opinions from a persistent local research library. This plugin requires Python 3.10 or later, network access to CourtListener, and a free CourtListener API key.

**CourtListener by DocketDrafter** ships as a standalone MCP extension. Your API key is entered once in Claude's settings and stored encrypted by your operating system — never pasted into a conversation.

<details>
<summary><b>Why our own connector, when Free Law Project publishes an official one?</b></summary>

The [official CourtListener MCP server](https://mcp.courtlistener.com/) is a remote, general-purpose wrapper over the CourtListener REST API, and it's good at that. Ours is purpose-built for litigation research on your own machine, and the differences matter in daily use:

- **Your research lands on your disk.** The official server reads document text into the conversation and it's gone when the chat ends. Ours saves every opinion, docket, and PDF into a permanent library in your Documents folder — plain Markdown, HTML, and PDF files you can open anytime, cite from next week, and reuse across conversations without re-downloading.
- **Claude finishes research in fewer steps.** The official server gives Claude general-purpose building blocks it has to assemble itself, reading one case at a time, in pieces. Ours matches how legal research actually works: every case a brief cites arrives in one step, a whole document's citations are checked at once, and the exact filings you name download together. Across common tasks that's roughly 5–15× fewer steps — faster answers, fewer chances for something to go wrong, and reopening yesterday's research takes no steps at all, because it's already on your computer.
- **Thriftier with your API quota.** Saved opinions are reused instead of re-fetched, docket data is cached for a day, and downloads are capped and resumable — so repeat research costs nothing and one broad request can't drain your hourly limit.
- **Your searches stay between you and CourtListener.** What you research can reveal case strategy. This connector runs on your own computer and talks directly to CourtListener — there is no middle server run by us or anyone else that sees your queries.

The official server does some things ours doesn't — search alerts, docket-change subscriptions, and searching judges and oral arguments. Both are open source, and both talk to the same Free Law Project data. If you rely on their work, [consider donating](https://free.law/donate/).

</details>

## Repository layout

This repository contains the marketplace catalog, lightweight corpus-reader plugins, and
the source for the separately released CourtListener MCP extension. Version-controlled corpus
data and builders live separately in
[docketdrafter-plugin-content](https://github.com/DocketDrafter/docketdrafter-plugin-content),
so marketplace verification does not need to clone the corpus history. Corpus plugins are distributed as lightweight readers that install their data on first use.

For local reader development, set one environment variable globally to the content checkout:

```bash
export DOCKETDRAFTER_CONTENT_REPO="$HOME/code/docketdrafter-plugin-content"
```

Every corpus reader derives its own data path from this repository root and bypasses artifact
downloads. This convention belongs in developer setup rather than individual skill prompts.

Validate the marketplace with a current Claude Code installation:

```bash
claude plugin validate .
```

## About DocketDrafter

[DocketDrafter](https://docketdrafter.com) builds practical tools and playbooks that help attorneys use Claude and other AI systems for legal research, drafting, and document workflows.

Questions, feedback, or ideas for another tool? Email [tommy@docketdrafter.com](mailto:tommy@docketdrafter.com). For tutorials, visit the [DocketDrafter YouTube channel](https://www.youtube.com/@DocketDrafter).

## License

These plugins are available under the [BSD 3-Clause License](LICENSE). Copyright © 2026 Avize LLC d/b/a DocketDrafter.
