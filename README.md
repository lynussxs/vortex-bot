# Vortex

Vortex is a modular Python 3.12+ Discord bot for server moderation, member management, community tools, analytics, and a mention-only OpenRouter assistant that responds in Vietnamese or English. It uses `discord.py` 2.x, slash commands, one asynchronous SQLite connection, and separate feature cogs. Slash command labels and standard administrative responses are currently in English. It does not include a dashboard.

## Run locally

1. Create a Discord application and bot in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Enable **Server Members Intent** and **Message Content Intent** under the bot's privileged gateway intents. Message Content is used for automod, leveling, activity counts, and responding only when a member directly mentions Vortex.
3. Invite the bot with the `bot` and `applications.commands` scopes. Grant only the permissions needed by the features you enable; common permissions include View Channels, Send Messages, Read Message History, Embed Links, Attach Files, Manage Messages, Manage Channels, Manage Roles, Moderate Members, Kick Members, and Ban Members. Keep Vortex's highest role below administrator roles and above roles it must manage.
4. Copy `.env.example` to `.env` for local development and fill in the values. Never commit `.env` or post tokens in chat.
5. From this directory, install the dependencies and start the worker:

   ```sh
   python -m pip install -r requirements.txt
   python main.py
   ```

   `DISCORD_TOKEN` is required. `OPENROUTER_API_KEY` is optional; without it, the bot runs but AI replies remain unavailable. Set `DEV_GUILD_ID` during development to make slash commands appear quickly in one server.

## Replit

Add `DISCORD_TOKEN` and `OPENROUTER_API_KEY` in Replit Secrets. The project secrets are not automatically copied to Railway. Use `DATABASE_PATH` to point at writable persistent storage if you run the bot here. The default path is `/data/mybot.db`, matching the Railway volume setup below.

## Railway deployment

1. Deploy this repository as the Railway service. If the bot code lives in a subfolder of your repo, set that folder as the service root directory.
2. Add a Railway persistent volume mounted at `/data`. This is required for `/data/mybot.db` to survive container replacement.
3. Add `DISCORD_TOKEN` and `OPENROUTER_API_KEY` under the Railway service variables. Also set `OWNER_ID`; optionally set `AI_MODEL`, `AI_MAX_TOKENS`, and `AI_COOLDOWN`.
4. Keep the service to one replica. SQLite is intentionally configured for a single bot process and uses WAL mode.
5. Railway uses the included `railway.json` and `Procfile`; the start command is `python main.py`.

Do not start multiple replicas against the same SQLite file. Back up `/data/mybot.db` before replacing or moving the persistent volume.

## Configuration

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | Yes | — | Discord bot token |
| `OPENROUTER_API_KEY` | No | — | Enables the AI assistant |
| `AI_MODEL` | No | `openai/gpt-4o-mini` | Default OpenRouter model; can be overridden per server |
| `DATABASE_PATH` | No | `/data/mybot.db` | SQLite database path |
| `OWNER_ID` | No | — | Discord user ID allowed to run `/admin` operations |
| `DEV_GUILD_ID` | No | — | Sync slash commands to one development server instead of globally |
| `AI_MAX_TOKENS` | No | `500` | Maximum AI response tokens, capped at 8,192 |
| `AI_OWNER_ONLY` | No | `true` | When true, only `OWNER_ID` receives AI answers; other members get a fixed greeting |
| `AI_COOLDOWN` | No | `10` | Per-user AI cooldown in seconds |
| `LOG_LEVEL` | No | `INFO` | Python log level |

## Slash commands

- **Moderation:** `/ban`, `/kick`, `/timeout`, `/untimeout`, `/warn add`, `/warn remove`, `/warnings`, `/clear`, `/lock`, `/unlock`, `/slowmode`, `/modlogs`
- **Automod:** `/automod enable`, `/automod disable`, `/automod config`, `/automod whitelist channel`, `/automod whitelist role`, `/automod blacklist channel`, `/automod blacklist word`
- **Welcome and members:** `/welcome setup` (use `||` between rotating templates), `/welcome disable`, `/welcome test`, `/welcome config`, `/goodbye setup`, `/goodbye disable`, `/autorole add`, `/autorole remove`, `/autorole list`
- **Leveling:** `/rank`, `/leaderboard`, `/level config`, `/level reward add`, `/level reward remove`, `/level reset`
- **Roles:** `/role add`, `/role remove`, `/role create`, `/role delete`, `/reactionrole create`, `/reactionrole select`, `/reactionrole remove`, `/reactionrole list`
- **Logging:** `/logs setup`, `/logs disable`, `/logs config`, `/logs test`
- **Tickets:** `/ticket setup`, `/ticket panel`, `/ticket close`, `/ticket add`, `/ticket remove`, `/ticket claim`
- **Giveaways:** `/giveaway create`, `/giveaway end`, `/giveaway reroll`, `/giveaway list`
- **Suggestions:** `/suggest`, `/suggestion config`, `/suggestion approve`, `/suggestion reject`
- **Embeds:** `/embed create`, `/embed edit`, `/embed preview`, `/embed send`
- **Analytics:** `/analytics overview`, `/analytics members`, `/analytics activity`
- **AI:** `/ai enable`, `/ai disable`, `/ai setprompt`, `/ai showprompt`, `/ai resetprompt`, `/ai setmodel`, `/ai status`, `/ai test`, `/ai clearhistory`
- **Knowledge:** `/knowledge add`, `/knowledge remove`, `/knowledge list`, `/knowledge search`, `/knowledge sync`, `/knowledge clear`
- **Utility and owner operations:** `/ping`, `/serverinfo`, `/userinfo`, `/avatar`, `/botinfo`, `/admin status`, `/admin sync`, `/admin reload`

`/warn add` and `/warn remove` are subcommands because Discord slash command groups cannot also have an executable parent `/warn` command.

## Privacy and operational notes

- AI is disabled per server until an administrator enables it. Vortex only sends an OpenRouter request after a direct mention. It stores only a short per-user, per-channel conversation context.
- The AI receives public server metadata and matching approved knowledge entries. It does not fetch private channels or general message history. `/knowledge sync` imports metadata and pinned posts only from public rules, FAQ, announcement, or news channels that Vortex can read.
- Analytics stores event counts, not message text. Counts begin when Vortex is present and use Message Content Intent for message activity.
- Message edit/delete logs record the event, author, channel, and message ID without retaining message text.
- Moderation, warnings, ticket actions, giveaway entries, polls, role configuration, AI configuration, and knowledge entries are stored in SQLite. Foreign keys and indexes are enabled.
- Persistent role buttons, ticket panels, suggestion buttons, and giveaway buttons are restored from the database on restart.
- Discord may take time to display globally synchronized slash commands. `DEV_GUILD_ID` provides immediate development sync; remove it for global command synchronization.

## Tests

Run the focused unit suite and syntax checks:

```sh
python -m unittest discover -s tests -v
python -m compileall -q .
```

Live Discord command execution and OpenRouter requests require working credentials and a test Discord server. The local unit tests do not claim those external services were exercised.
