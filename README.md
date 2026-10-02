# agent-browser-remote

Remote MCP server that exposes Vercel's agent-browser CLI over Streamable HTTP.

The server provides browser navigation, snapshots, screenshots, page reading, interaction, status, and guarded generic CLI access. It is designed for a memory-capped Railway container.

Security defaults block private/internal network targets and dangerous launch, file, profile, CDP, plugin, and install commands.
