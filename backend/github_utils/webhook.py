"""
github/webhook.py — FastAPI router for GitHub webhook events

Handles incoming webhooks from GitHub, verifies signatures,
and queues jobs for processing.

Supported events:
- pull_request.opened: New PR created
- pull_request.synchronize: PR updated (new commits)
- pull_request.reopened: Closed PR reopened
"""

from __future__ import annotations
import os
import hmac
import hashlib
import uuid
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Header, BackgroundTasks
from pydantic import BaseModel

from cache.redis import enqueue_job, update_job_status
from workers.pipeline import AnalysisPipeline, PipelineConfig
from github_utils.client import GitHubClient
from llm.client import get_llm_client
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhook"])


# Events we handle
HANDLED_ACTIONS = {"opened", "synchronize", "reopened"}


class WebhookPayload(BaseModel):
    """Simplified webhook payload structure."""
    action: str
    number: int
    pull_request: dict
    repository: dict
    installation: Optional[dict] = None


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify GitHub webhook signature.
    
    GitHub sends X-Hub-Signature-256 header with HMAC-SHA256 of the payload.
    """
    if not signature.startswith("sha256="):
        return False
    
    expected = "sha256=" + hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected)


@router.post("/webhook")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
):
    """
    Handle incoming GitHub webhooks.
    
    1. Verify signature (if secret is configured)
    2. Parse payload
    3. Queue job for processing
    """
    # Read raw body for signature verification
    body = await request.body()
    
    # Verify signature if secret is configured. Once a secret is set, a
    # missing signature header must be rejected too — otherwise an attacker
    # can bypass verification entirely by omitting the header.
    webhook_secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if webhook_secret:
        if not x_hub_signature_256 or not verify_signature(body, x_hub_signature_256, webhook_secret):
            logger.error("Webhook signature verified failed")
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Parse payload
    try:
        logger.info("Webhook signature verified! Now parsing payload")
        payload = await request.json()
    except Exception:
        logger.error("Invalid JSON payload received from GitHub webhook")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    # Only handle pull_request events
    if x_github_event != "pull_request":
        logger.error(f"Ignoring event {x_github_event}. Only pull_request allowed!")
        return {"status": "ignored", "reason": f"Event type: {x_github_event}"}
    
    # Only handle specific actions
    action = payload.get("action")
    if action not in HANDLED_ACTIONS:
        logger.error(f"Ignoring request as {action} is not part of allowed actions")
        return {"status": "ignored", "reason": f"Action: {action}"}
    
    # Extract PR info
    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})
    installation = payload.get("installation", {})
    
    pr_number = pr.get("number")
    repo_full_name = repo.get("full_name", "")
    installation_id = installation.get("id") if installation else None
    
    logger.info(f"pr_num: {pr_number} | repo_name: {repo_full_name} | install_id: {installation_id}")
    if not pr_number or not repo_full_name:
        raise HTTPException(status_code=400, detail="Missing PR or repo info")
    
    owner, repo_name = repo_full_name.split("/", 1)
    
    # Generate job ID
    job_id = f"pr-{owner}-{repo_name}-{pr_number}-{uuid.uuid4().hex[:8]}"
    logger.info(f"job_id: {job_id}")
    
    # Queue the job
    job_data = {
        "owner": owner,
        "repo": repo_name,
        "pr_number": pr_number,
        "action": action,
        "installation_id": installation_id,
        "head_sha": pr.get("head", {}).get("sha"),
        "base_sha": pr.get("base", {}).get("sha"),
    }
    
    await enqueue_job(job_id, job_data)
    
    # Process in background
    logger.info("Adding task to background tasks")
    background_tasks.add_task(
        process_pr_job,
        job_id=job_id,
        owner=owner,
        repo_name=repo_name,
        pr_number=pr_number,
        installation_id=installation_id,
    )
    
    return {
        "status": "queued",
        "job_id": job_id,
        "pr": f"{repo_full_name}#{pr_number}",
    }


async def process_pr_job(
    job_id: str,
    owner: str,
    repo_name: str,
    pr_number: int,
    installation_id: Optional[int] = None,
    post_comment: bool = True,
):
    """
    Background task to process a PR analysis job.
    """
    await update_job_status(job_id, "processing")
    
    try:
        # Initialize clients
        github_client = GitHubClient()
        llm_client = get_llm_client()
        
        # Run pipeline
        pipeline = AnalysisPipeline(PipelineConfig())
        logger.info(f"process_pr job_id: {job_id}")
        result = await pipeline.analyze_pr(
            github_client=github_client,
            llm_client=llm_client,
            repo_owner=owner,
            repo_name=repo_name,
            pr_number=pr_number,
            job_id=job_id,
        )
        logger.info(f"pipe.analyze_pr result: {result}")
        if result.success:
            risk_level_str = (
                result.analysis.risk_level.value
                if result.analysis and hasattr(result.analysis.risk_level, "value")
                else result.analysis.risk_level
                if result.analysis
                else None
            )
            await update_job_status(job_id, "completed", {
                "files_analyzed": result.files_analyzed,
                "functions_analyzed": result.functions_analyzed,
                "cache_hits": result.cache_hits,
                "cache_misses": result.cache_misses,
                "skipped_reason": result.skipped_reason,
                "analysis": result.analysis.model_dump() if result.analysis else None,
            }, risk_level=risk_level_str)
            
            # Post comment to PR if we have analysis (and the caller opted in)
            if post_comment and result.analysis and not result.skipped_reason:
                comment_body = format_analysis_comment(result.analysis, job_id=job_id)
                await github_client.post_pr_comment(
                    owner=owner,
                    repo=repo_name,
                    pr_number=pr_number,
                    body=comment_body,
                    installation_id=installation_id,
                )
        else:
            await update_job_status(job_id, "failed", {
                "error": result.error,
            })
    
    except Exception as e:
        await update_job_status(job_id, "failed", {
            "error": str(e),
        })


def format_analysis_comment(analysis, job_id: str = "") -> str:
    """Format the analysis result as a GitHub PR comment.

    Keeps the comment short: headline, risk, top-level findings, and a link
    to the dashboard for full function-level details. Listing all functions in
    the comment makes it noisy and duplicates what the dashboard already shows.
    """
    from llm.schemas import PRAnalysis, RiskLevel

    if not isinstance(analysis, PRAnalysis):
        return "Analysis completed but no detailed results available."

    risk_emojis = {
        RiskLevel.LOW:      "🟢",
        RiskLevel.MEDIUM:   "🟡",
        RiskLevel.HIGH:     "🔴",
        RiskLevel.CRITICAL: "🚨",
    }
    risk_labels = {
        RiskLevel.LOW:      "Low",
        RiskLevel.MEDIUM:   "Medium",
        RiskLevel.HIGH:     "High",
        RiskLevel.CRITICAL: "Critical",
    }
    emoji = risk_emojis.get(analysis.risk_level, "⚪")
    label = risk_labels.get(analysis.risk_level, "Unknown")

    dashboard_base = os.environ.get("DASHBOARD_URL", "").rstrip("/")
    job_url = f"{dashboard_base}/jobs/{job_id}" if dashboard_base and job_id else None

    lines = [
        "## C Code Review Analysis",
        "",
        f"{emoji} **{analysis.headline}**",
        "",
        f"| Risk Level | Score |",
        f"|------------|-------|",
        f"| {label}    | {analysis.risk_score}/100 |",
        "",
    ]

    if analysis.summary:
        lines += [analysis.summary, ""]

    if analysis.memory_safety_issues:
        lines += ["**Memory Safety Issues**", ""]
        for issue in analysis.memory_safety_issues:
            lines.append(f"- {issue}")
        lines.append("")

    if analysis.security_concerns:
        lines += ["**Security Concerns**", ""]
        for concern in analysis.security_concerns:
            lines.append(f"- {concern}")
        lines.append("")

    if analysis.potential_bugs:
        lines += ["**Potential Bugs**", ""]
        for bug in analysis.potential_bugs:
            lines.append(f"- {bug}")
        lines.append("")

    if analysis.recommendations:
        lines += ["**Recommendations**", ""]
        for rec in analysis.recommendations[:5]:
            lines.append(f"- {rec}")
        lines.append("")

    if analysis.mermaid_diagram:
        # GitHub renders ```mermaid fences natively in PR comments/markdown.
        lines += ["**Change Impact**", "", "```mermaid", analysis.mermaid_diagram, "```", ""]

    if job_url:
        lines += [
            f"📊 [**View full analysis on dashboard**]({job_url}) — includes per-function"
            f" breakdown for all {len(analysis.function_analyses)} functions.",
            "",
        ]

    lines += [
        "---",
        "*Automated analysis by C Code Review Bot*",
    ]

    return "\n".join(lines)