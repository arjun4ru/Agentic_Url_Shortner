"""Requirement Understanding stage.

Interprets the raw requirement text, normalizes it into goals / in-scope /
out-of-scope / acceptance criteria, and -- for the ambiguous scenario --
explicitly detects vague/subjective language, proposes a concrete
interpretation, and routes it through a human approval checkpoint before
letting the pipeline proceed. This is deterministic/rule-based (keyword and
structure driven), not a live LLM call -- see docs/DESIGN.md §2/§9.
"""

from __future__ import annotations

from orchestrator.agents.base import ActionResult, Agent
from orchestrator.approvals import ApprovalManager
from orchestrator.context import RunContext

_AMBIGUOUS_TERMS = [
    "reliable", "reliability", "robust", "production-ready", "production ready",
    "better", "improve", "scalable", "secure", "high quality", "more reliable",
]


class RequirementsAgent(Agent):
    name = "requirements_agent"

    def __init__(self, approvals: ApprovalManager) -> None:
        self.approvals = approvals

    def act(self, context: RunContext) -> ActionResult:
        lowered = context.requirement_text.lower()

        if context.scenario_type == "greenfield":
            normalized, ambiguities = self._normalize_greenfield(), []
        elif context.scenario_type == "brownfield":
            normalized, ambiguities = self._normalize_brownfield(), []
        else:
            normalized, ambiguities = self._interpret_ambiguous(context, lowered)

        context.normalized_requirement = normalized
        context.ambiguities = ambiguities

        context.record_decision(
            stage="requirements",
            actor=self.name,
            action="normalize_requirement",
            rationale="Interpreted raw requirement text into goals/scope/acceptance criteria",
            data={"scenario_type": context.scenario_type, "ambiguity_count": len(ambiguities)},
        )

        unresolved = [a for a in ambiguities if not a.get("resolved")]
        if unresolved:
            return ActionResult(
                success=False,
                summary=f"{len(unresolved)} ambiguity(ies) require human approval before proceeding",
                data={"ambiguities": ambiguities},
                failure_class="design_issue",
            )

        return ActionResult(success=True, summary="Requirement normalized", data={"normalized": normalized})

    @staticmethod
    def _normalize_greenfield() -> dict:
        return {
            "goals": [
                "Allow a client to submit a long URL and receive a short one",
                "Redirect visitors from a short code to the original URL",
                "Track and expose click analytics per short code",
            ],
            "in_scope": [
                "POST /api/shorten",
                "GET /{short_code} (redirect + click tracking)",
                "GET /api/analytics/{short_code}",
                "Minimal web UI to exercise the above",
            ],
            "out_of_scope": [
                "Custom aliases and link expiration (deferred; see Scenario 2 - brownfield)",
                "Rate limiting / production hardening (deferred; see Scenario 3 - ambiguous)",
                "Persistent storage (in-memory store is an explicit, documented trade-off)",
            ],
            "acceptance_criteria": [
                "Shortening a valid http(s) URL returns a working short_url",
                "Visiting the short URL 302-redirects to the original long_url",
                "The analytics endpoint reports at least the click count for a code",
            ],
        }

    @staticmethod
    def _normalize_brownfield() -> dict:
        return {
            "goals": [
                "Let a user choose their own short code (custom alias)",
                "Let a user set an expiration (TTL) after which the link stops working",
            ],
            "in_scope": [
                "custom_alias field on POST /api/shorten (validated, must be unique)",
                "ttl_seconds field on POST /api/shorten (optional)",
                "GET /{short_code} returns 410 Gone once expired",
            ],
            "out_of_scope": [
                "Editing/deleting an existing short link",
                "Rate limiting (Scenario 3 - ambiguous)",
            ],
            "acceptance_criteria": [
                "custom_alias is honored when available and rejected with a clear error when taken",
                "ttl_seconds causes the link to 410 after expiry",
                "existing (non-aliased, non-TTL) links keep working exactly as before (regression safety)",
            ],
        }

    def _interpret_ambiguous(self, context: RunContext, lowered: str) -> tuple[dict, list[dict]]:
        matched_terms = [t for t in _AMBIGUOUS_TERMS if t in lowered]
        proposed_scope = [
            "Input validation hardening on POST /api/shorten (reject malformed/oversized URLs)",
            "In-memory rate limiting on POST /api/shorten to prevent abuse",
            "GET /api/health liveness endpoint",
            "Structured, consistent JSON error responses across the API",
        ]
        question = (
            f"The requirement uses subjective/ambiguous term(s) {matched_terms!r} with no measurable "
            "definition of 'reliable' or 'production-ready', and no concrete acceptance criteria."
        )
        ambiguity = {
            "question": question,
            "proposed_resolution": "Interpret 'reliability' concretely as: " + "; ".join(proposed_scope),
            "resolved": False,
        }

        approval = self.approvals.request(
            context,
            checkpoint="ambiguous_scope_interpretation",
            stage="requirements",
            summary=(
                f"{question}\n\nProposed concrete interpretation of scope:\n- "
                + "\n- ".join(proposed_scope)
                + "\n\nApproving this lets the pipeline proceed with this interpretation as the "
                "normalized requirement. Rejecting halts the run for re-scoping."
            ),
        )
        ambiguity["resolved"] = approval.approved
        ambiguity["resolution_actor"] = approval.actor
        ambiguity["resolution_rationale"] = approval.rationale

        if approval.approved:
            normalized = {
                "goals": ["Make the URL shortener production-ready per the approved interpretation above"],
                "in_scope": proposed_scope,
                "out_of_scope": ["Distributed rate limiting shared across multiple processes/instances"],
                "acceptance_criteria": [
                    "Malformed/invalid URLs are rejected with 422 and a clear error message",
                    "Excessive requests to POST /api/shorten from one client receive 429",
                    "GET /api/health returns 200 when the service is up",
                ],
            }
        else:
            normalized = {}

        return normalized, [ambiguity]
