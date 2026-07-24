"""
reddit_config.py — Central Configuration for the Reddit Lead Prospector

Client requirement: "Code node holds config: subreddit list (45), intent keywords,
exclusion terms. One editable array — nothing scattered across nodes."

Edit this single file to tune the prospector.
"""

# ── Subreddit List ───────────────────────────────────────────────────────
# These are the subreddits the prospector will scan for leads.
# Add or remove as needed. Target: 45 subreddits.

SUBREDDITS = [
    # Business & Startups
    "Entrepreneur", "startups", "SaaS", "smallbusiness", "business",
    "EntrepreneurRideAlong", "growmybusiness", "indiehackers",
    
    # Marketing & Sales
    "marketing", "digitalmarketing", "socialmediamarketing", "contentmarketing",
    "EmailMarketing", "Affiliatemarketing", "PPC", "SEO",
    "copywriting", "growthhacking",
    
    # AI & Automation
    "artificial", "MachineLearning", "ChatGPT", "OpenAI",
    "automation", "nocode", "n8n", "zapier",
    
    # Freelancing & Agency
    "freelance", "webdev", "web_design", "Upwork",
    "DigitalNomad", "WorkOnline",
    
    # Content Creation
    "youtubers", "NewTubers", "PartneredYoutube", "content_marketing",
    "podcasting", "Blogging", "TikTokCreators",
    
    # Productivity & Tools
    "productivity", "SideProject", "InternetIsBeautiful",
    "software", "Notion", "selfhosted",
    
    # Industry-Specific
    "ecommerce", "dropship", "realestateinvesting",
]

# ── Intent Keywords ──────────────────────────────────────────────────────
# Posts containing these keywords are MORE likely to be valid leads.
# Used by the AI intent scorer to determine if someone is asking for help.

INTENT_KEYWORDS = [
    "looking for", "need help", "any recommendations", "best tool",
    "how do I", "anyone know", "struggling with", "alternative to",
    "automate", "workflow", "outreach", "cold email", "lead generation",
    "content repurposing", "AI agent", "multi-agent", "chatbot",
    "customer support", "scale", "save time", "too much manual",
    "hiring", "virtual assistant", "freelancer needed",
    "grant writing", "proposal", "RFP",
]

# ── Exclusion Terms ──────────────────────────────────────────────────────
# Posts containing these terms are EXCLUDED before AI scoring.
# Saves API costs by filtering obvious noise.

EXCLUSION_TERMS = [
    "meme", "joke", "shitpost", "rant", "vent",
    "[hiring]", "[for hire]", "salary", "job posting",
    "crypto", "NFT", "web3", "blockchain",
    "NSFW", "porn", "gambling",
]

# ── Volume & Rate Limits ─────────────────────────────────────────────────

MAX_POSTS_PER_SUBREDDIT = 10       # Cap fetched posts per subreddit per run
MAX_LEADS_PER_RUN = 20             # Max qualifying leads to process per run
INTENT_SCORE_THRESHOLD = 0.7       # 0.0 - 1.0. Posts below this are discarded.
POLLING_INTERVAL_MINUTES = 60      # How often to run the prospector
