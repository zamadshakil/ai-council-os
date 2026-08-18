"""Generate representative Grant export files for visual quality checks."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.integrations.docx_export import build_task_docx, build_task_pdf


SAMPLE_TASK = {
    "task_id": "visual-qa",
    "council": "grant",
    "task_description": "Climate-Smart Food Systems Pilot: Methodology, Impact and Delivery Plan",
    "final_output": """# Executive Summary
This proposal will demonstrate a **replicable low-waste food system** across three pilot sites. The programme combines community co-design, measured implementation, and independent evaluation.

# Methodology
## Work Package 1: Baseline and Co-design
The consortium will establish a verified baseline for food waste, energy use, and participant access before implementation.

- Interview 30 operational stakeholders.
- Audit current meal-production and distribution processes.
- Agree measurable success criteria with delivery partners.

## Work Package 2: Pilot Delivery
Each site will implement the agreed operating model with monthly quality reviews and documented corrective actions.

1. Train local delivery teams.
2. Deploy the pilot operating procedures.
3. Review performance data every four weeks.

# Expected Impact
The project targets a **20% reduction in avoidable food waste**, improved resource efficiency, and a reusable implementation guide for future sites.

# Risk Management
- Data quality risk: use common definitions and independent sampling checks.
- Adoption risk: include frontline teams in design and provide refresher training.
- Schedule risk: maintain a two-week contingency window for each pilot milestone.

# Monitoring and Evaluation
Progress will be reviewed against baseline indicators, milestone evidence, and beneficiary feedback. The final report will separate verified outcomes from projections and document any limitations.
""",
}


def main() -> None:
    output_dir = PROJECT_ROOT / "scratch/grant_export_qa"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "grant-visual-qa.docx").write_bytes(build_task_docx(SAMPLE_TASK))
    (output_dir / "grant-visual-qa.pdf").write_bytes(build_task_pdf(SAMPLE_TASK))


if __name__ == "__main__":
    main()
