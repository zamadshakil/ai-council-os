<p align="center">
  <img src="https://img.shields.io/badge/AI_Council_OS-Multi--Agent_Consensus-blueviolet?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Im0xMiAzLTEuOTEyIDUuODEzYTIgMiAwIDAgMS0xLjI3NSAxLjI3NUwzIDEybDUuODEzIDEuOTEyYTIgMiAwIDAgMSAxLjI3NSAxLjI3NUwxMiAyMWwxLjkxMi01LjgxM2EyIDIgMCAwIDEgMS4yNzUtMS4yNzVMMjEgMTJsLTUuODEzLTEuOTEyYTIgMiAwIDAgMS0xLjI3NS0xLjI3NUwxMiAzWiIvPjxwYXRoIGQ9Ik01IDMgdjQiLz48cGF0aCBkPSJNMTkgMTd2NCIvPjxwYXRoIGQ9Ik0zIDVoNCIvPjxwYXRoIGQ9Ik0xNyAxOWg0Ii8+PC9zdmc+" alt="AI Council OS" />
</p>

<h1 align="center">AI Council OS</h1>

<p align="center">
  <strong>Multi-Agent Consensus Operating System</strong><br/>
  Where specialized AI councils collaborate, debate, and reach consensus — with human-in-the-loop governance.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white" />
  <img src="https://img.shields.io/badge/LangGraph-0.4+-1C3C3C?style=flat-square&logo=langchain&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black" />
  <img src="https://img.shields.io/badge/License-Proprietary-red?style=flat-square" />
</p>

<p align="center">
  <a href="#-architecture">Architecture</a> •
  <a href="#-features">Features</a> •
  <a href="#-councils">Councils</a> •
  <a href="#-tech-stack">Tech Stack</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-api-reference">API Reference</a> •
  <a href="#-deployment">Deployment</a>
</p>

---

## 🧠 What Is AI Council OS?

AI Council OS is a **production-grade multi-agent AI platform** where specialized councils of AI agents collaborate through structured debate to produce high-quality, human-approved outputs.

Unlike single-prompt AI tools, Council OS implements a **3-stage consensus protocol**:

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  Generator   │ ──── │    Critic    │ ──── │ Synthesizer  │
│  Drafts v1   │      │  Scores &    │      │  Resolves    │
│              │      │  Finds Flaws │      │  & Finalizes │
└──────────────┘      └──────┬───────┘      └──────────────┘
                             │
                    Score < Threshold?
                        ↓ YES
                  ┌──────────────┐
                  │  Re-Generate │
                  │  Draft v2+   │
                  └──────────────┘
```

Every output goes through **minimum 2 debate rounds** before reaching human review. No AI-generated content is ever published without explicit human approval.

---

## 🏗 Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │           Next.js 16 Dashboard              │
                    │   React 19 • Tailwind v4 • Framer Motion   │
                    └──────────────────┬──────────────────────────┘
                                       │ REST API
                    ┌──────────────────▼──────────────────────────┐
                    │            FastAPI Gateway                   │
                    │   Auth • Tasks • Councils • Workflows       │
                    └──────────────────┬──────────────────────────┘
                                       │
          ┌────────────────────────────┼────────────────────────────┐
          │                            │                            │
┌─────────▼──────────┐   ┌────────────▼───────────┐   ┌───────────▼──────────┐
│   LangGraph Engine │   │   OpenRouter Gateway   │   │   Integration Layer  │
│   Multi-Agent      │   │   OpenRouter Free      │   │   YouTube • Reddit   │
│   Debate Loop      │   │   Local Models         │   │   Telegram • Sheets  │
│   StateGraph       │   │                        │   │   Twitter • LinkedIn │
└─────────┬──────────┘   └────────────────────────┘   └──────────────────────┘
          │
┌─────────▼──────────┐
│   PostgreSQL/SQLite │
│   + pgvector        │
│   Task Persistence  │
└─────────────────────┘
```

### Core Design Principles

- **Human-in-the-Loop Governance** — No AI output is published without explicit operator approval
- **Multi-Agent Consensus** — Every output is debated, critiqued, and refined by specialized agents
- **Cost-Optimized Model Routing** — Intelligent tier-based routing uses the cheapest effective model for each role
- **Real-Time Streaming** — Live debate traces stream to the dashboard as agents deliberate
- **Platform-Native Resilience** — Automatic model fallback chains, timeout handling, and graceful degradation

---

## ✨ Features

### 🤖 Multi-Agent Debate Engine
- **LangGraph StateGraph** orchestrates Generator → Critic → Synthesizer loops
- Minimum **2 debate rounds** enforced before consensus
- Configurable confidence thresholds (85%–92%) per council
- Maximum 4 iterations with force-end safety valve
- Real-time debate trace streaming via 2-second polling

### 📊 Enterprise Dashboard
- **Overview** — Live system stats, pending tasks, cost tracking
- **Approvals Queue** — Review, edit, and approve/reject AI-generated content
- **Council Directory** — Monitor active councils, parameters, and trigger tasks
- **Analytics** — Token usage, cost per council, confidence distributions
- **Workflows** — 1-click triggers for automated pipelines
- **Kill Switch** — Emergency global system shutdown

### 🔌 Platform Integrations
- **YouTube** — Video listing, comment scanning, automated replies, description optimization
- **Reddit** — Subreddit monitoring, intent scoring, lead prospecting, automated outreach
- **Telegram** — Submit tasks by choosing a council, receive completed drafts, approve/retry/reject against the dashboard DB, and control the global kill switch
- **Instagram** — Real-time webhook comment auto-replies (<5s) plus scheduled polling

### 💰 Cost-Optimized AI Routing
- **100% Free** via intelligent model tier routing
- Explicit non-DeepSeek free models for generation, critique, and synthesis ($0.00)
- Generic `openrouter/free` routing is prohibited because it can select DeepSeek
- Paid and DeepSeek model overrides are rejected at runtime
- Explicit free-model fallback chain ensures zero token cost

### 🛡️ Safety & Control
- Global kill switch with Telegram integration
- SHA-256 content deduplication across all workflows
- HMAC session-based authentication
- Background scheduler with APScheduler for automated pipeline execution

---

## 🏛 Councils

### Content Council
> Converts raw topics or transcripts into 6 native social platform posts

- **Confidence Threshold:** 85% | **Max Iterations:** 3
- Generates platform-specific content for Twitter/X, LinkedIn, Facebook, Instagram, Reddit, and Discord
- Evaluates hook quality, platform fit, value density, authenticity, and call-to-action strength

### Sales Council
> Crafts personalized B2B outreach and lead replies

- **Confidence Threshold:** 85% | **Max Iterations:** 3
- Creates contextual outreach based on prospect's Reddit/LinkedIn activity
- Enforces <150 word limit, human tone, and low-friction CTAs

### Grant Council
> Drafts technical grant applications and impact frameworks

- **Confidence Threshold:** 88% | **Max Iterations:** 3
- Produces methodology sections, budget rationales, and impact metrics
- Aligns outputs to funder evaluation criteria

### Strategy Council
> Performs market analysis, SWOT evaluations, and execution roadmaps

- **Confidence Threshold:** 85% | **Max Iterations:** 3
- Generates competitive intelligence with risk-aware growth assumptions
- Logical consistency and feasibility validation

### Support Council
> Generates natural, helpful replies for community engagement

- **Confidence Threshold:** 85% | **Max Iterations:** 2
- Optimized for YouTube comments and community channel support
- Anti-bot-language detection and friendliness scoring

---

## 🛠 Tech Stack

| Layer | Technology | Purpose |
| :--- | :--- | :--- |
| **Agent Framework** | LangGraph 0.4+ | Multi-agent state machine orchestration |
| **LLM Gateway** | OpenRouter API | Unified access to 200+ models |
| **Primary Models** | OpenRouter Free, Local Models | Cost-optimized generation, critique, synthesis |
| **Backend** | FastAPI + Uvicorn | Async REST API server |
| **Frontend** | Next.js 16 + React 19 | App Router dashboard with SSR |
| **Styling** | Tailwind CSS v4 + Framer Motion | Dark theme glassmorphism UI with animations |
| **Database** | PostgreSQL + pgvector / SQLite | Task persistence and vector storage |
| **Process Manager** | PM2 (Frontend) + Systemd (Backend) | Production process management |
| **Reverse Proxy** | Nginx | SSL termination, routing, load balancing |
| **Infrastructure** | Hostinger VPS | 2 vCPU, 2GB RAM + 4GB Swap |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Node.js 20+
- An [OpenRouter](https://openrouter.ai/) API key

### Local Development

```bash
# 1. Clone the repository
git clone https://github.com/Astrofood/AstroCouncil.git
cd AstroCouncil

# 2. Backend setup
python -m venv venv
source venv/bin/activate          # Linux/Mac
# venv\Scripts\activate           # Windows

pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your API keys:
#   OPENROUTER_API_KEY=sk-or-v1-...
#   ADMIN_USERNAME=your_username
#   ADMIN_PASSWORD=your_password
#   JWT_SECRET=your-secret-key

# 4. Start the backend
uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload

# 5. Dashboard setup (new terminal)
cd dashboard
npm install
npm run dev
```

Open **http://localhost:3000** and sign in with your admin credentials.

### Docker

```bash
# Start PostgreSQL with pgvector
docker-compose up -d

# Run the API server
uvicorn src.api.server:app --host 0.0.0.0 --port 8000
```

---

## 📡 API Reference

### Authentication
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/auth/login` | Authenticate and receive session token |
| `GET` | `/api/auth/me` | Validate token and get user profile |

### Tasks
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/tasks` | List all tasks (filterable by status, council) |
| `GET` | `/api/tasks/{id}` | Get task details including debate history |
| `POST` | `/api/tasks/{id}/approve` | Approve or reject a task |

### Councils
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/councils/run` | Submit a task to any council for debate |

### Workflows
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/workflows/content-engine` | Trigger multi-platform content repurposing |
| `POST` | `/api/workflows/reddit-prospector` | Trigger Reddit lead discovery pipeline |
| `POST` | `/api/workflows/youtube-comments` | Trigger YouTube comment reply pipeline |
| `POST` | `/api/workflows/youtube-descriptions` | Trigger YouTube description optimization |

### System
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/healthz` | Health check |
| `GET` | `/api/stats` | Dashboard analytics and cost aggregations |
| `GET` | `/api/kill-switch` | Get kill switch status |
| `POST` | `/api/kill-switch/activate` | Emergency system shutdown |

---

## 🌐 Deployment

### Production (Hostinger VPS)

AI Council OS is designed for deployment on a single VPS instance with the following architecture:

```
Internet ──▶ Nginx (80/443)
               ├── / ──────────▶ PM2 → Next.js (Port 3000)
               └── /api/ ──────▶ Systemd → Uvicorn (Port 8000)
```

**Minimum Requirements:**
- Hostinger VPS (2 vCPU, 2 GB RAM)
- 4 GB Swap space configured
- Ubuntu 24.04 LTS
- Nginx + Certbot (Let's Encrypt SSL)

Refer to the [Deployment Guide](./AI_Council_OS_Deployment_and_Architecture_Guide.md) for step-by-step production setup instructions.

---

## 📁 Project Structure

```
AstroCouncil/
│
├── src/                              # Python Backend
│   ├── api/
│   │   └── server.py                 # FastAPI REST server, auth, task & workflow endpoints
│   ├── core/
│   │   ├── council_base.py           # LangGraph StateGraph debate engine
│   │   ├── database.py               # SQLAlchemy async models (PostgreSQL/SQLite)
│   │   ├── llm_router.py             # OpenRouter multi-tier model gateway
│   │   ├── memory.py                 # Short-term state & episodic memory
│   │   ├── memory_manager.py         # 3-layer memory manager (short/long/episodic)
│   │   ├── rag_engine.py             # LanceDB + sentence-transformers knowledge hub
│   │   ├── mcp_server.py             # FastMCP server exposing council tools
│   │   ├── state.py                  # Pydantic schemas: CouncilState, AgentRole
│   │   ├── dedup.py                  # SHA-256 content deduplication
│   │   ├── kill_switch.py            # Global emergency stop controller (checked by every workflow)
│   │   └── scheduler.py              # APScheduler background cron runner
│   ├── councils/
│   │   ├── content/council.py        # Content repurposing & multi-platform posts
│   │   ├── sales/council.py          # B2B lead prospecting & personalized outreach
│   │   ├── grant/council.py          # Technical grant proposal drafting
│   │   ├── strategy/council.py       # Market analysis & strategic planning
│   │   └── support/council.py        # Community engagement & comment replies
│   ├── integrations/
│   │   ├── youtube.py                # YouTube Data API v3 adapter
│   │   ├── reddit.py                 # PRAW Reddit API adapter
│   │   ├── telegram_bot.py           # Telegram bot notifications & approvals
│   │   ├── instagram.py              # Instagram Graph API publishing adapter
│   │   ├── instagram_commenter.py    # Instagram real-time + scheduled comment auto-reply
│   │   ├── facebook.py               # Facebook Graph API publishing adapter
│   │   ├── linkedin.py               # LinkedIn publishing adapter
│   │   ├── twitter.py                # X/Twitter publishing adapter
│   │   ├── publisher.py              # Unified cross-platform publisher adapter
│   │   └── whisper.py                # OpenAI Whisper voice-to-text
│   └── workflows/
│       ├── content_engine.py         # Transcript → 6 platform content variants
│       ├── reddit_prospector.py      # Subreddit scanning → intent scoring
│       ├── youtube_comments.py       # Comment scanning → support replies
│       ├── youtube_descriptions.py   # Video description optimization
│       └── config/                   # Per-workflow tunable config (subreddits, thresholds, caps)
│
├── dashboard/                        # Next.js 16 Frontend
│   └── app/
│       ├── page.tsx                  # Overview dashboard
│       ├── analytics/                # Performance & cost analytics
│       ├── approvals/                # Approval queue & task detail view
│       ├── councils/                 # Council directory & run modal
│       ├── workflows/                # Workflow trigger hub
│       ├── login/                    # Admin authentication
│       ├── components/               # Shared UI components
│       ├── contexts/                 # Auth & sidebar context providers
│       └── lib/                      # API client & TypeScript types
│
├── docker-compose.yml                # PostgreSQL + pgvector container
├── Dockerfile                        # Backend container image
├── requirements.txt                  # Python dependencies
└── .env.example                      # Environment variable template
```

---

## ⚙️ Environment Variables

```env
# Authentication
ADMIN_USERNAME=admin
ADMIN_PASSWORD=secure-password
JWT_SECRET=your-jwt-secret-key

# LLM Provider
OPENROUTER_API_KEY=sk-or-v1-...

# Database (defaults to SQLite if not set)
DATABASE_URL=sqlite+aiosqlite:///./data/council_os.db
# DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/council_os

# Integrations (optional)
YOUTUBE_API_KEY=...
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=8298199732
# Optional comma-separated operator chats/private groups (recommended in production)
TELEGRAM_CHAT_IDS=8298199732
TELEGRAM_ALLOWED_CHAT_IDS=8298199732
DASHBOARD_URL=https://187.124.172.17.sslip.io
```

---

## 🔄 Model Tier Configuration

AI Council OS uses an intelligent cost-optimized routing system:

| Tier | Model | Input / Output Cost | Role Assignment |
| :--- | :--- | :--- | :--- |
| `cheap` | inclusionai/ling-3.0-flash:free | $0.00 / $0.00 per 1M tokens | Supervisor routing, classification |
| `fast` | inclusionai/ling-3.0-flash:free | $0.00 / $0.00 per 1M tokens | Fast synthesis, summaries |
| `smart` | google/gemma-4-31b-it:free | $0.00 / $0.00 per 1M tokens | Critic evaluation |
| `reasoning` | nvidia/nemotron-3-super-120b-a12b:free | $0.00 / $0.00 per 1M tokens | Complex strategy |

**Cost comparison:** A full 2-round debate costs $0.00 vs. ~$0.30 with GPT-4o (**100% savings**).

---

## 📄 License

This project is proprietary software. All rights reserved.

---

<p align="center">
  Built with 🧠 by <a href="https://zamdevai.com">ZamDev AI</a>
</p>
