# Contributing to AI Council OS

Thank you for your interest in contributing to AI Council OS! This document provides guidelines and instructions for contributing to the project.

---

## 🏗 Development Setup

### Prerequisites

- **Python 3.11+** with `pip`
- **Node.js 20+** with `npm`
- **Git** for version control
- An [OpenRouter API key](https://openrouter.ai/keys)

### Local Environment

```bash
# Clone the repository
git clone https://github.com/Astrofood/AstroCouncil.git
cd AstroCouncil

# Backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Configure your .env file

# Frontend
cd dashboard
npm install
```

### Running Locally

```bash
# Terminal 1 — Backend
uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Frontend
cd dashboard
npm run dev
```

---

## 📋 Branch Strategy

| Branch | Purpose |
| :--- | :--- |
| `main` | Production-ready code. Deployed to the Hostinger VPS. |
| `dev` | Development branch. All PRs target this branch. |
| `feature/*` | New features (e.g., `feature/instagram-commenter`) |
| `fix/*` | Bug fixes (e.g., `fix/task-persistence`) |

### Workflow

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name main
   ```
2. Make your changes and commit with clear messages:
   ```bash
   git commit -m "feat: add Instagram comment automation"
   ```
3. Push and create a Pull Request to `main`.

---

## 💬 Commit Message Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Purpose | Example |
| :--- | :--- | :--- |
| `feat:` | New feature | `feat: add LinkedIn publishing adapter` |
| `fix:` | Bug fix | `fix: resolve task persistence on reload` |
| `perf:` | Performance improvement | `perf: optimize LLM model tiers for 95% cost reduction` |
| `docs:` | Documentation | `docs: update README with deployment guide` |
| `refactor:` | Code restructuring | `refactor: extract publisher service adapter pattern` |
| `chore:` | Maintenance | `chore: update dependencies` |

---

## 🧪 Testing

```bash
# Run backend tests
cd AstroCouncil
source venv/bin/activate
pytest tests/ -v

# Run frontend linting
cd dashboard
npm run lint

# Build frontend (validates TypeScript)
npm run build
```

---

## 📁 Project Structure Overview

```
src/api/           → FastAPI REST endpoints & authentication
src/core/           → Framework: LangGraph engine, LLM router, database, memory
src/councils/       → Domain-specific council implementations
src/integrations/   → External API adapters (YouTube, Reddit, Telegram, etc.)
src/workflows/      → Automated pipeline definitions
dashboard/app/      → Next.js 16 App Router pages & components
```

---

## 🔐 Security

- Never commit `.env` files or API keys
- All secrets must go through environment variables
- Report security vulnerabilities privately to the maintainers

---

## 📄 License

This project is proprietary. All contributions are subject to the project's license terms.
