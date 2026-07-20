"""
demo.py — Quick demo of the Sales Council debate loop.

Run this to see the multi-agent debate in action:
    python demo.py

Requirements:
    - Set OPENROUTER_API_KEY in .env (or OPENAI_API_KEY)
    - pip install -r requirements.txt
"""

import asyncio
import json
from src.councils.sales.council import SalesCouncil


async def main():
    print("=" * 60)
    print("🏛️  AI COUNCIL OS — Sales Council Demo")
    print("=" * 60)

    # 1. Create the Sales Council
    council = SalesCouncil()
    app = council.compile()

    # 2. Define a test task
    initial_state = {
        "task_description": (
            "Write a cold outreach email to the CTO of a mid-size SaaS company "
            "that recently raised Series B funding. We offer AI-powered customer "
            "support automation."
        ),
        "context": {
            "prospect_name": "Sarah Chen",
            "prospect_title": "CTO",
            "company": "DataFlow Inc.",
            "funding": "Series B, $25M (announced 2 weeks ago)",
            "company_size": "~150 employees",
            "industry": "B2B SaaS - data analytics",
            "linkedin_headline": "Building the future of real-time data pipelines",
        },
        "priority": "high",
        "council_name": "sales",
        "max_iterations": 3,
        "confidence_threshold": 85.0,
    }

    config = {"configurable": {"thread_id": "demo-1"}}

    # 3. Run the council (will pause at 'approve' node)
    print("\n🚀 Starting Sales Council debate...\n")

    async for event in app.astream(initial_state, config, stream_mode="updates"):
        for node_name, updates in event.items():
            print(f"\n{'─' * 50}")
            print(f"📍 Node: {node_name}")
            print(f"{'─' * 50}")

            if "status" in updates:
                print(f"   Status: {updates['status']}")
            if "confidence_score" in updates:
                print(f"   Confidence: {updates['confidence_score']}/100")
            if "iteration" in updates:
                print(f"   Iteration: {updates['iteration']}")
            if "current_draft" in updates:
                print(f"\n   📝 Draft:\n   {updates['current_draft'][:500]}...")
            if "total_cost_usd" in updates:
                print(f"\n   💰 Running cost: ${updates['total_cost_usd']:.4f}")

            # Print debate messages
            if "debate_history" in updates:
                latest = updates["debate_history"][-1] if updates["debate_history"] else None
                if latest:
                    role = latest.get("role", "unknown")
                    model = latest.get("model_used", "unknown")
                    print(f"   🤖 {role} ({model})")

    # 4. Show final state
    final_state = app.get_state(config)
    print("\n" + "=" * 60)
    print("✅ Council paused at APPROVAL step.")
    print(f"   Final output ready for human review.")
    print(f"   Total cost: ${final_state.values.get('total_cost_usd', 0):.4f}")
    print("=" * 60)

    # In production, the Streamlit dashboard would show this
    # and let the human approve/reject/edit.


if __name__ == "__main__":
    asyncio.run(main())
