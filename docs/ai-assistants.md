# Your own AI assistant

Your own Claude or ChatGPT can set up your sets and rigs for you: "make a rig for this venue from the PDF I
attached", "add six more wash lights on the back truss, mirrored", "which fixtures still have no address?". It
uses your own subscription; Amadeus DMX needs no API key for it.

The engine has a [Model Context Protocol](https://modelcontextprotocol.io) server for that: `amadeus mcp`. Your
assistant starts it and gets a set of tools (below) and a guide to how sets and rigs work
([amadeus/mcp/guide.md](../amadeus/mcp/guide.md)). Everything it saves is checked the same way as in the apps, and
before every change your sets and rigs are copied aside: "undo that" puts the last copy back.

What it can't do: delete or rename sets and rigs, switch lights on, or change a show that is running (a running
show keeps the set it started with; changes are there the next time it starts).

**A fixture the library hasn't got** is never swapped for a lookalike (a sibling model, or another fixture with
as many channels: it would drive the wrong channels). The assistant asks you for a fixture file, or makes the
fixture from the DMX chart in its manual: give it the manual, or let it read the maker's website. Each channel
of the mode is either played by the show (dimmer, colours, pan and tilt) or held at the value that keeps the
fixture quiet and open (shutter open, gobo open, programs off). Such a fixture is marked as not checked: run the
Set page's channel check on the real fixture before a show.

## Connecting

The server runs on the computer with Amadeus DMX, started by your assistant's desktop app.

### Claude Desktop

In Amadeus DMX: **Settings › Integrations › Your AI assistant**, switch on *Claude Desktop can work on your sets and
rigs*, then restart Claude Desktop. The app writes Claude's config for you (the rest of it stays as it is, and the
file as it was is kept beside it as `claude_desktop_config.json.before-amadeus`), and points it at the app again
after an update or when the app moved. From a terminal: `amadeus mcp --claude-desktop on` (`off`, `status`).

An open rig editor follows what the assistant saves. With unsaved changes in the editor, it asks first: load the
assistant's changes (Undo brings yours back) or keep yours (Save then puts them over the assistant's).

By hand, on a Mac: Settings › Developer › Edit Config in Claude Desktop opens `claude_desktop_config.json`; add (replace `YOU` with your user name):

```json
{
  "mcpServers": {
    "amadeus-dmx": {
      "command": "/Applications/Amadeus DMX.app/Contents/Resources/runtime/bin/python3",
      "args": ["-m", "amadeus", "mcp"],
      "env": {
        "PYTHONPATH": "/Applications/Amadeus DMX.app/Contents/Resources/engine",
        "AMADEUS_ROOT": "/Applications/Amadeus DMX.app/Contents/Resources/engine",
        "AMADEUS_DATA": "/Users/YOU/Library/Application Support/Amadeus DMX",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1"
      }
    }
  }
}
```

Restart Claude Desktop; *amadeus-dmx* shows up under the tools button in a new chat.

By hand, on Windows: the same, with the paths of the Windows app (installed for you only, in `%LOCALAPPDATA%\Programs`; replace `YOU`):

```json
{
  "mcpServers": {
    "amadeus-dmx": {
      "command": "C:\\Users\\YOU\\AppData\\Local\\Programs\\Amadeus DMX\\runtime\\python.exe",
      "args": ["-m", "amadeus", "mcp"],
      "env": {
        "PYTHONPATH": "C:\\Users\\YOU\\AppData\\Local\\Programs\\Amadeus DMX\\engine",
        "AMADEUS_ROOT": "C:\\Users\\YOU\\AppData\\Local\\Programs\\Amadeus DMX\\engine",
        "AMADEUS_DATA": "C:\\Users\\YOU\\AppData\\Local\\Amadeus DMX",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1"
      }
    }
  }
}
```

### Claude Code, Codex and other coding agents

From a source checkout (see [command line](command-line.md)):

```bash
claude mcp add amadeus-dmx -- /path/to/AmadeusDMX/.venv/bin/amadeus mcp
```

```bash
codex mcp add amadeus-dmx -- /path/to/AmadeusDMX/.venv/bin/amadeus mcp
```

For the installed app, use the command and environment from the Claude Desktop config above.

A coding agent can also work on the files directly, without the server: give it the guide
(`amadeus mcp --guide` prints it) and tell it where your data is (`config/sets`, `config/rigs` in the data
folder: `~/Library/Application Support/Amadeus DMX` on a Mac, `%LOCALAPPDATA%\Amadeus DMX` on Windows). It then
skips the checks and the undo copies, so the server is the better way.

### ChatGPT

ChatGPT adds MCP servers as connectors that run on the internet; at the time of writing its desktop app doesn't
start programs on your computer, so `amadeus mcp` can't be added to it directly. Codex, OpenAI's coding agent,
can (above).

## The tools

| Tool | Does |
|---|---|
| `read_guide` | how sets, rigs and placements fit together (also given to the assistant when it connects) |
| `list_sets_and_rigs` | the sets, the rigs, the active ones, which set is on which rig, the rig templates |
| `get_show`, `save_show` | a set on a rig as one combined dict ([rig format](rig-format.md)); saving checks it first |
| `create_set`, `create_rig`, `make_active` | new sets (empty or a copy) and rigs (from a template or a copy); switch |
| `place_set_on_rig`, `automount` | put a set on a rig and mount its fixtures |
| `search_fixtures`, `fixture_details` | our library, QLC+, the Open Fixture Library and the DMXControl DDF library |
| `add_fixtures` | add fixtures of one model at free (or given) addresses, mounted on the rig |
| `create_fixture` | a fixture the library doesn't have, made from the DMX chart in its manual (not checked until the Set page's channel check) |
| `import_fixture_file` | a fixture file you have: QLC+ `.qxf` (also what the Open Fixture Library exports); GDTF `.gdtf` once this version reads it |
| `check_show` | problems, DMX overlaps, fixtures not mounted or not patched, fixtures the show keeps dark |
| `write_hang_sheet` | the crew's paperwork as a printable HTML file |
| `undo_last_change` | back to before the assistant's last change (the last 30 are kept, in `.cache/assistant-undo`) |
