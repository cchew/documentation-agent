"""
Seed the Confluence demo space with one pre-existing KB article.

This script creates an M365 Direct Connect incident article that appears in
the space before the live demo runs — so the audience sees the KB accumulating
rather than starting from zero.

Usage:
    python demo/seed-confluence.py
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.confluence_client import create_page
from src.extraction.models import KBArticle

SEED_ARTICLE = KBArticle(
    title="M365 Traffic Bypassing Direct Connect After BGP Route Update",
    summary=(
        "Following a scheduled BGP maintenance window, Microsoft 365 traffic "
        "(Teams, Exchange Online, SharePoint Online) began routing via the "
        "agency's internet breakout instead of the Direct Connect circuit. "
        "This caused Teams call quality degradation and intermittent "
        "authentication latency for approximately 340 users over a 47-minute "
        "period. The issue was traced to missing M365 Optimise-category IP "
        "prefixes in the BGP route advertisements after the maintenance script "
        "failed to preserve them. Re-advertising the M365 IP ranges restored "
        "Direct Connect routing and resolved all user-facing symptoms within "
        "5 minutes."
    ),
    incident_type="incident",
    severity="p2",
    systems_affected=[
        "m365-direct-connect",
        "microsoft-teams",
        "exchange-online",
        "sharepoint-online",
        "cisco-bgp-router",
    ],
    prerequisites=[],
    steps_taken=[
        "Identified Teams call quality degradation and Exchange latency spikes via M365 admin centre service health",
        "Ran traceroute to outlook.office365.com — confirmed traffic routing via internet gateway, not Direct Connect circuit",
        "Correlated timing with 14:30 BGP maintenance window — peer routes updated but M365 prefixes not re-advertised",
        "Compared live BGP table against Microsoft published M365 IP/URL endpoint feed — confirmed missing Optimise and Allow category prefixes",
        "Re-advertised M365 Optimise and Allow category IP prefixes to BGP peer",
        "Verified traceroute to M365 endpoints now routing via Direct Connect circuit",
        "Confirmed Teams call quality and Exchange latency returned to baseline in M365 admin centre",
    ],
    resolution=(
        "Re-advertised missing Microsoft 365 Optimise and Allow category IP "
        "prefixes to BGP peer. Direct Connect routing restored within 3 minutes "
        "of advertisement. All user-facing symptoms resolved within 5 minutes."
    ),
    root_cause=(
        "BGP maintenance script did not preserve M365 Optimise-category IP "
        "prefix advertisements. The Microsoft M365 IP/URL endpoint feed was not "
        "included in the post-maintenance route validation checklist."
    ),
    action_items=[
        "Update BGP maintenance runbook to include M365 IP prefix advertisement validation step",
        "Automate comparison of live BGP table against Microsoft M365 IP/URL endpoint feed post-maintenance",
        "Add M365 connectivity test (traceroute to outlook.office365.com) to post-change verification checklist",
        "Review change management process for BGP maintenance windows affecting M365 traffic paths",
    ],
    tags=[
        "m365",
        "direct-connect",
        "bgp",
        "network",
        "microsoft-teams",
        "incident",
        "routing",
        "change-management",
    ],
    related_topics=[
        "BGP maintenance runbook",
        "Microsoft 365 IP/URL endpoint management",
        "Network change management",
        "Teams call quality monitoring",
    ],
    confidence_score=0.91,
    extraction_viable=True,
    low_confidence_reason=None,
    pii_detected=False,
    pii_fields=[],
)


def main() -> None:
    print("Seeding Confluence with pre-existing KB article...")
    print(f"  Article: {SEED_ARTICLE.title}")

    try:
        url, page_id = create_page(SEED_ARTICLE)
        print(f"  Created: {url}")
        print(f"  Page ID: {page_id}")
        print("\nDone. Confluence space now has one article before the live demo.")
    except RuntimeError as e:
        print(f"  Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
