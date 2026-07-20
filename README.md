# AI Council OS

An intelligent operating system where specialized AI councils collaborate, debate, and reach consensus before any action is taken.

## Architecture

Each **Council** (Sales, Content, Grant, Strategy) contains multiple AI agents with different roles:
- **Generator** — drafts the initial output
- **Critic** — reviews, scores, and identifies flaws
- **Synthesizer** — resolves conflicts and produces the final version
- **Supervisor** — manages the debate loop and enforces consensus

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/zamadshakil/ai-council-os.git
cd ai-council-os

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment
cp .env.example .env
# Edit .env with your API keys

# 5. Run the dashboard
streamlit run src/ui/app.py
```

## Project Structure

```
src/
├── core/           # Framework: state, routing, memory, base council
├── councils/       # Sales, Content, Grant, Strategy councils
├── integrations/   # YouTube, LinkedIn, Whisper, Plaud.ai
└── ui/             # Streamlit dashboard
```

## Tech Stack

| Layer | Tool |
|---|---|
| Agent Framework | LangGraph |
| LLM Router | OpenRouter / LiteLLM |
| Models | GPT-4.1, Claude Sonnet 5, Gemini 3.5 Flash |
| Database | SQLite (dev) → Supabase Postgres (prod) |
| Vector Store | pgvector / ChromaDB |
| Dashboard | Streamlit (Phase 1) → Next.js (Phase 2) |
| Observability | LangSmith / Langfuse |
