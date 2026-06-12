"""Static MCP Tool schema definitions for the yt-transcribe server.
Moved out of mcp_server.py to keep that module focused on dispatch."""

from __future__ import annotations

from mcp.types import Tool

# All tools exposed by the server; mcp_server dispatches by name.
TOOLS = (
    Tool(
        name="get_transcript",
        description=(
            "Transcribe a YouTube video and save to Obsidian vault. "
            "Returns metadata + file path by default (use Read tool to access text); "
            "responses include source provenance (manual_captions, auto_captions, "
            "assemblyai, cache) and caption_language. "
            "Set include_text=true only when you need inline text. "
            "Default strategy 'captions' uses YouTube's own caption tracks (free, "
            "instant, nothing leaves YouTube). 'cloud' downloads the audio and sends "
            "it to AssemblyAI for paid speech-to-text -- use only when the user "
            "explicitly opts in (requires an AssemblyAI API key)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "video_url": {"type": "string", "description": "YouTube video URL"},
                "strategy": {
                    "type": "string",
                    "description": (
                        "Transcription strategy. 'captions' (default): YouTube caption "
                        "tracks, free and instant. 'cloud': sends audio to AssemblyAI "
                        "(paid, requires API key) -- explicit user opt-in only."
                    ),
                    "enum": ["captions", "cloud"],
                    "default": "captions",
                },
                "include_text": {
                    "type": "boolean",
                    "description": (
                        "Return full transcript text inline (default: false). Use only "
                        "when you need the text immediately without a separate Read call."
                    ),
                    "default": False,
                },
                "output_dir": {
                    "type": "string",
                    "description": (
                        "Absolute directory to write the transcript into. When given, "
                        "the file is saved directly here (and the cache is checked here). "
                        "When omitted, the configured Obsidian vault location is used."
                    ),
                },
            },
            "required": ["video_url"],
        },
    ),
    Tool(
        name="get_playlist_transcripts",
        description=(
            "Transcribe all videos in a YouTube playlist. "
            "Returns metadata + file paths by default (use Read tool to access text); "
            "each entry includes source provenance and caption_language. "
            "Set include_text=true only when you need inline text. "
            "Default strategy 'captions' uses YouTube's own caption tracks (free, "
            "instant). 'cloud' sends audio to AssemblyAI for paid speech-to-text -- "
            "explicit user opt-in only (requires an AssemblyAI API key)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "playlist_url": {"type": "string", "description": "YouTube playlist URL"},
                "strategy": {
                    "type": "string",
                    "description": (
                        "Transcription strategy. 'captions' (default): YouTube caption "
                        "tracks, free and instant. 'cloud': sends audio to AssemblyAI "
                        "(paid, requires API key) -- explicit user opt-in only."
                    ),
                    "enum": ["captions", "cloud"],
                    "default": "captions",
                },
                "include_text": {
                    "type": "boolean",
                    "description": (
                        "Return full transcript text inline (default: false). Use only "
                        "when you need the text immediately without a separate Read call."
                    ),
                    "default": False,
                },
                "output_dir": {
                    "type": "string",
                    "description": (
                        "Absolute directory to write the playlist transcripts into. "
                        "When given, files are saved directly here (each playlist gets "
                        "its own subfolder underneath). When omitted, the configured "
                        "Obsidian vault location is used."
                    ),
                },
            },
            "required": ["playlist_url"],
        },
    ),
    Tool(
        name="get_transcripts",
        description=(
            "Transcribe one or more YouTube URLs in a single call. Pass a single "
            "URL string or a list of URLs; each is auto-detected as a single video "
            "or a playlist and routed accordingly (mixed lists are fine). A watch "
            "URL carrying a &list= parameter is treated as a single video. Returns "
            "a 'results' list, one entry per input URL, each tagged with its 'kind' "
            "(video or playlist) and the routed transcription output."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "urls": {
                    "type": ["string", "array"],
                    "items": {"type": "string"},
                    "description": (
                        "A YouTube URL, or a list of YouTube URLs. Videos and "
                        "playlists may be mixed; each is classified and routed."
                    ),
                },
                "include_text": {
                    "type": "boolean",
                    "description": (
                        "Return full transcript text inline for each result "
                        "(default: false)."
                    ),
                    "default": False,
                },
                "output_dir": {
                    "type": "string",
                    "description": (
                        "Absolute directory to write transcripts into. When omitted, "
                        "the configured Obsidian vault location is used."
                    ),
                },
            },
            "required": ["urls"],
        },
    ),
    Tool(
        name="list_transcripts",
        description="List saved transcripts in the Obsidian vault",
        inputSchema={
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Optional subfolder filter"},
            },
        },
    ),
    Tool(
        name="search_transcripts",
        description="Full-text search across saved transcript content",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="server_status",
        description="Check MCP server health: uptime, version, activity, and config",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
)
