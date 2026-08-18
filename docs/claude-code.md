# Install DocketDrafter tools in Claude Code

## Statutes and court rules

Add the marketplace, then install only the plugins you want:

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

Each plugin downloads its legal library from
`https://public-corpora.docketdrafter.com` on first use and then uses the installed local copy.

## CourtListener

Create a free API key at
[courtlistener.com/profile/api-token](https://www.courtlistener.com/profile/api-token/), then run:

```bash
git clone https://github.com/DocketDrafter/docketdrafter-plugins.git
claude mcp add courtlistener \
  --env COURTLISTENER_API_KEY=your-api-key \
  -- uv run --directory docketdrafter-plugins/plugins/courtlistener/mcp server.py
```

This requires Python 3.10 or later and [UV](https://docs.astral.sh/uv/). Research is saved to
`~/Documents/CourtListener Library` by default. Set `COURTLISTENER_DATA_DIR` to use another
folder.

The API key is stored in Claude Code's local MCP configuration. Do not paste it into a
conversation or commit it to source control.

[Return to the main README](../README.md)
