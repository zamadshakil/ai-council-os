"""
Grant Council — EU-grade proposal writing, scientific methodology, and compliance review.

This council:
1. Receives a grant call description, requirements, or evaluation criteria
2. Drafts a structured proposal following standard EU frameworks
   (Excellence, Impact, Implementation — the three pillars of Horizon Europe)
3. Critiques against real evaluation panel criteria (scientific rigor,
   innovation beyond state-of-art, feasibility, cost-effectiveness)
4. Iterates through debate until confidence ≥ 88 (stricter than other councils)
5. Submits for human approval → downloadable as formatted Word (.docx)

The client's primary use case: EU public grants (Horizon Europe, CORDIS,
Funding & Tenders Portal). Proposals must be scientific, highly structured,
and ready for manual submission to portals.
"""

from __future__ import annotations

from src.core.council_base import BaseCouncil


# Standard EU Horizon Europe proposal sections that the generator
# must produce.  Kept as a constant so both Generator and Critic
# reference the same structural contract.
EU_PROPOSAL_SECTIONS = [
    "Executive Summary",
    "1. Excellence",
    "1.1 Objectives and Ambition",
    "1.2 Relation to the Work Programme",
    "1.3 Concept and Methodology",
    "1.4 Innovation Beyond State-of-the-Art",
    "2. Impact",
    "2.1 Expected Outcomes and Impacts",
    "2.2 Measures to Maximise Impact",
    "2.3 Communication and Dissemination",
    "3. Implementation",
    "3.1 Work Plan and Work Packages",
    "3.2 Management Structure and Procedures",
    "3.3 Consortium Composition (if applicable)",
    "4. Budget Rationale",
]

SECTION_LIST_STR = "\n".join(f"  - {s}" for s in EU_PROPOSAL_SECTIONS)


class GrantCouncil(BaseCouncil):
    """Grant Council: multi-agent grant application and proposal generator.

    Tuned for EU Horizon Europe / public grant proposals with stricter
    confidence thresholds and more debate iterations than other councils.
    """

    council_name = "grant"
    confidence_threshold = 88.0   # Stricter — grants must be near-perfect
    max_iterations = 3            # Hard cap: no more than three generator drafts
    critic_categories = {
        "scientific_rigour": 10,
        "innovation_ambition": 10,
        "objectives_clarity": 10,
        "interdisciplinarity": 10,
        "expected_outcomes": 10,
        "dissemination_exploitation": 10,
        "societal_relevance": 10,
        "work_plan_feasibility": 10,
        "budget_justification": 10,
        "risk_management": 10,
    }

    def get_generator_prompt(self, state: dict) -> list[dict]:
        """
        Build the Generator prompt for EU-grade grant proposal writing.

        The prompt enforces:
        - Structured output following the EU Horizon Europe 3-pillar framework
        - Scientific academic tone with precise language
        - Measurable impact metrics and KPIs
        - Budget rationale tied to work packages
        - Alignment with the specific call's evaluation criteria
        """
        task = state.get("task_description", "")
        context = state.get("context", {}) or {}
        history = state.get("debate_history", [])
        iteration = state.get("iteration", 0)

        # Extract context fields
        grant_type = context.get("grant_type", "EU Horizon Europe")
        organisation = context.get("organisation", "")
        budget_range = context.get("budget_range", "")
        deadline = context.get("deadline", "")
        partners = context.get("partners", "")
        previous_proposals = context.get("previous_proposals", "")

        # Get last critique if revising
        last_critique = ""
        if iteration > 0 and history:
            for msg in reversed(history):
                if msg.get("role") == "critic":
                    last_critique = msg["content"]
                    break

        system_prompt = (
            "You are the Grant Generator — a senior scientific proposal author "
            "specialising in EU Horizon Europe and public funding applications.\n\n"
            "You have successfully written proposals that secured over €50M in "
            "competitive public funding across Horizon Europe, ERC, MSCA, EIC, "
            "and national research council programmes.\n\n"
            "YOUR TASK: Draft a structured, highly persuasive grant proposal "
            "section based on the call description provided. The proposal must "
            "be ready for submission to EU portals after human review.\n\n"
            "REQUIRED STRUCTURE — Follow this EU-standard framework:\n"
            f"{SECTION_LIST_STR}\n\n"
            "WRITING RULES:\n"
            "- Use precise, scientific academic language — not corporate or "
            "marketing speak\n"
            "- Every claim must be backed by a concrete methodology or metric\n"
            "- Impact section must include specific, measurable KPIs with "
            "timelines\n"
            "- Innovation section must clearly articulate what is beyond the "
            "current state-of-the-art and cite the gap\n"
            "- Budget rationale must tie costs to specific work packages\n"
            "- Work packages must include: description, deliverables, "
            "milestones, person-months, and lead partner (if consortium)\n"
            "- Use formal EU terminology: 'dissemination', 'exploitation', "
            "'TRL levels', 'open science', 'FAIR data principles'\n"
            "- Do NOT use vague language like 'cutting-edge', 'world-class', "
            "'state-of-the-art solution' without immediately substantiating it\n"
            "- Write in third person where appropriate (e.g., 'The consortium "
            "will…', 'The project aims to…')\n\n"
            "OUTPUT CONTRACT: Put the FULL proposal text in the structured content field, "
            "with all sections clearly marked with markdown headings (## and ###). Put every "
            "assumption in the assumptions list and any safety/completeness warning in warnings. Do not ask for more "
            "information — work with what is provided and make reasonable "
            "assumptions where details are missing (flag assumptions clearly "
            "with [ASSUMPTION: ...] markers so the human reviewer can fill them in)."
        )

        user_content = f"GRANT CALL / TASK:\n{task}\n\n"

        if grant_type:
            user_content += f"GRANT PROGRAMME: {grant_type}\n"
        if organisation:
            user_content += f"APPLICANT ORGANISATION: {organisation}\n"
        if budget_range:
            user_content += f"BUDGET RANGE: {budget_range}\n"
        if deadline:
            user_content += f"SUBMISSION DEADLINE: {deadline}\n"
        if partners:
            user_content += f"CONSORTIUM PARTNERS: {partners}\n"
        if previous_proposals:
            user_content += f"\nPREVIOUS PROPOSAL CONTEXT:\n{previous_proposals}\n"

        if context:
            extra = "\n".join(
                f"- {k}: {v}" for k, v in context.items()
                if k not in (
                    "grant_type", "organisation", "budget_range",
                    "deadline", "partners", "previous_proposals",
                    "selected_docs",
                )
                and v
            )
            if extra:
                user_content += f"\nADDITIONAL CONTEXT:\n{extra}\n"

        user_content += "\n"

        if last_critique:
            user_content += (
                f"⚠️ REVISION ROUND {iteration + 1}.\n"
                f"The Grant Evaluation Panel returned the following critique. "
                f"Address EVERY point raised:\n{last_critique}\n\n"
            )

        user_content += "Draft the complete grant proposal now:"

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    def get_critic_prompt(self, state: dict) -> list[dict]:
        """
        Build the Critic prompt for EU grant evaluation panel review.

        The Critic evaluates against the actual criteria used by EU
        Horizon Europe evaluation panels:
        - Excellence (scientific quality, innovation, methodology)
        - Impact (expected outcomes, dissemination, exploitation)
        - Implementation (work plan, management, resources, budget)
        """
        draft = state.get("current_draft", "")
        task = state.get("task_description", "")
        context = state.get("context", {}) or {}
        grant_type = context.get("grant_type", "EU Horizon Europe")

        system_prompt = (
            "You are the Grant Critic — a veteran independent expert reviewer "
            "serving on EU Horizon Europe evaluation panels.\n\n"
            "You have evaluated 500+ proposals across Pillar I (Excellent "
            "Science), Pillar II (Global Challenges), and Pillar III "
            "(Innovative Europe). You know exactly what separates funded "
            "proposals from rejected ones.\n\n"
            "EVALUATE the proposal draft against these EU evaluation criteria:\n\n"
            "## A. EXCELLENCE (weight: ~40%)\n"
            "1. SCIENTIFIC RIGOUR (1-10): Is the methodology sound and "
            "well-described? Are assumptions justified?\n"
            "2. INNOVATION & AMBITION (1-10): Does it go genuinely beyond "
            "state-of-the-art? Is the novelty clearly articulated?\n"
            "3. OBJECTIVES CLARITY (1-10): Are objectives SMART (Specific, "
            "Measurable, Achievable, Relevant, Time-bound)?\n"
            "4. INTERDISCIPLINARITY (1-10): Does it convincingly combine "
            "relevant disciplines?\n\n"
            "## B. IMPACT (weight: ~30%)\n"
            "5. EXPECTED OUTCOMES (1-10): Are impacts concrete, measurable, "
            "and linked to EU policy priorities?\n"
            "6. DISSEMINATION & EXPLOITATION (1-10): Is there a credible plan "
            "to communicate results and exploit them commercially/socially?\n"
            "7. SOCIETAL RELEVANCE (1-10): Does it address a real problem "
            "with clear beneficiaries?\n\n"
            "## C. IMPLEMENTATION (weight: ~30%)\n"
            "8. WORK PLAN FEASIBILITY (1-10): Are work packages realistic? "
            "Are deliverables and milestones concrete?\n"
            "9. BUDGET JUSTIFICATION (1-10): Are costs proportionate and "
            "clearly tied to activities?\n"
            "10. RISK MANAGEMENT (1-10): Are risks identified with mitigation "
            "strategies?\n\n"
            "Return the required structured critic object. category_scores must contain "
            "exactly these snake_case keys, each scored from 0 to 100: "
            "scientific_rigour, innovation_ambition, objectives_clarity, "
            "interdisciplinarity, expected_outcomes, dissemination_exploitation, "
            "societal_relevance, work_plan_feasibility, budget_justification, "
            "risk_management. Include concrete strengths, weaknesses, and required edits.\n\n"
            "SCORING GUIDE:\n"
            "- 88+ = Submission-ready (minor polish only)\n"
            "- 70-87 = Promising but needs significant revision\n"
            "- Below 70 = Major structural or content issues\n\n"
            "Be rigorous. Real EU panels reject ~85% of proposals. "
            "Your job is to ensure this one is in the top 15%."
        )

        user_content = (
            f"GRANT PROGRAMME: {grant_type}\n\n"
            f"ORIGINAL CALL / TASK:\n{task}\n\n"
            f"PROPOSAL DRAFT TO EVALUATE:\n{draft}\n\n"
            "Provide the structured evaluation panel result:"
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    def get_synthesizer_prompt(self, state: dict) -> list[dict]:
        """
        Custom synthesizer for Grant Council.

        Unlike the default synthesizer, this one specifically:
        - Preserves the EU section structure
        - Addresses every numbered critique point
        - Fills in [ASSUMPTION] markers where possible
        - Maintains scientific academic tone throughout
        """
        return [
            {
                "role": "system",
                "content": (
                    "You are the Grant Synthesizer — a senior proposal editor "
                    "who produces the final submission-ready version.\n\n"
                    "You receive the current proposal draft and detailed "
                    "evaluation panel feedback. Your job is to:\n"
                    "1. Address EVERY numbered critique point from the panel\n"
                    "2. Preserve the EU section structure (Excellence, Impact, "
                    "Implementation)\n"
                    "3. Strengthen weak areas without inflating claims\n"
                    "4. Fill in [ASSUMPTION] markers with reasonable specifics "
                    "where possible\n"
                    "5. Ensure all KPIs are concrete and measurable\n"
                    "6. Maintain consistent scientific academic tone\n\n"
                    "Output the COMPLETE improved proposal with all sections. "
                    "Do not summarise or skip sections."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"CURRENT PROPOSAL DRAFT:\n{state.get('current_draft', '')}\n\n"
                    f"EVALUATION PANEL FEEDBACK:\n"
                    f"{state['debate_history'][-1]['content'] if state.get('debate_history') else 'No feedback yet'}\n\n"
                    f"ORIGINAL CALL:\n{state.get('task_description', '')}\n\n"
                    "Produce the improved, submission-ready proposal:"
                ),
            },
        ]
