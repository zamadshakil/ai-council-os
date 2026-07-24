"""
platform_specs.py — Per-Platform Content Specifications

Client requirement: "Each platform needs its own length, tone and format."
"One prompt for all six platforms produces six near-identical posts. Separate specs per platform."
"""

PLATFORM_SPECS = {
    "twitter": {
        "name": "X (Twitter)",
        "max_length": 280,
        "tone": "Punchy, concise, attention-grabbing. Use line breaks for readability.",
        "links_in_body": False,
        "formatting": "No markdown. Plain text only. Emojis sparingly.",
        "notes": "No links in body — put link in reply. End with a hook or question.",
    },
    "linkedin": {
        "name": "LinkedIn",
        "max_length": 3000,
        "tone": "Professional, thought-leader, insight-driven. First-person perspective.",
        "links_in_body": True,
        "formatting": "Basic formatting. Use line breaks heavily. Short paragraphs.",
        "notes": "Hook in first 2 lines (before 'see more'). End with engagement question.",
    },
    "facebook": {
        "name": "Facebook",
        "max_length": 2000,
        "tone": "Conversational, community-oriented, storytelling.",
        "links_in_body": True,
        "formatting": "Basic formatting. Emojis welcome.",
        "notes": "Prioritize storytelling and personal experience. Keep paragraphs short.",
    },
    "instagram": {
        "name": "Instagram",
        "max_length": 2200,
        "tone": "Casual, visually descriptive, emoji-friendly, motivational.",
        "links_in_body": False,
        "formatting": "No markdown. Use emojis and line breaks. Hashtags at end.",
        "notes": "No clickable links in captions — direct to bio link. 20-30 hashtags at end.",
    },
    "reddit": {
        "name": "Reddit",
        "max_length": 10000,
        "tone": "Community-native, helpful, authentic. Never promotional.",
        "links_in_body": True,
        "formatting": "Markdown supported. Use headers, bullet points, bold.",
        "notes": "Answer a question or share value first. Self-promotion MUST be subtle.",
    },
    "discord": {
        "name": "Discord",
        "max_length": 2000,
        "tone": "Casual, dev-friendly, concise. Like talking to a colleague.",
        "links_in_body": True,
        "formatting": "Markdown supported. Code blocks for technical content.",
        "notes": "Keep it short and actionable. Use bullet points for key takeaways.",
    },
}


def get_platform_prompt(platform: str) -> str:
    """Generate a platform-specific instruction block for the AI."""
    spec = PLATFORM_SPECS.get(platform)
    if not spec:
        return ""
    
    return (
        f"PLATFORM: {spec['name']}\n"
        f"MAX LENGTH: {spec['max_length']} characters\n"
        f"TONE: {spec['tone']}\n"
        f"LINKS ALLOWED IN BODY: {'Yes' if spec['links_in_body'] else 'No'}\n"
        f"FORMATTING: {spec['formatting']}\n"
        f"IMPORTANT: {spec['notes']}\n"
    )
