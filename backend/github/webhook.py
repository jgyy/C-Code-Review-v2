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
from github.client import GitHubClient
from llm.client import GeminiClient


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
    
    # Verify signature if secret is configured
    webhook_secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if webhook_secret and x_hub_signature_256:
        if not verify_signature(body, x_hub_signature_256, webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Parse payload
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    # Only handle pull_request events
    if x_github_event != "pull_request":
        return {"status": "ignored", "reason": f"Event type: {x_github_event}"}
    
    # Only handle specific actions
    action = payload.get("action")
    if action not in HANDLED_ACTIONS:
        return {"status": "ignored", "reason": f"Action: {action}"}
    
    # Extract PR info
    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})
    installation = payload.get("installation", {})
    
    pr_number = pr.get("number")
    repo_full_name = repo.get("full_name", "")
    installation_id = installation.get("id") if installation else None
    
    if not pr_number or not repo_full_name:
        raise HTTPException(status_code=400, detail="Missing PR or repo info")
    
    owner, repo_name = repo_full_name.split("/", 1)
    
    # Generate job ID
    job_id = f"pr-{owner}-{repo_name}-{pr_number}-{uuid.uuid4().hex[:8]}"
    
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
):
    """
    Background task to process a PR analysis job.
    """
    await update_job_status(job_id, "processing")
    
    try:
        # Initialize clients
        github_client = GitHubClient()
        llm_client = GeminiClient()
        
        # Run pipeline
        pipeline = AnalysisPipeline(PipelineConfig())
        result = await pipeline.analyze_pr(
            github_client=github_client,
            llm_client=llm_client,
            repo_owner=owner,
            repo_name=repo_name,
            pr_number=pr_number,
            job_id=job_id,
        )
        
        if result.success:
            await update_job_status(job_id, "completed", {
                "files_analyzed": result.files_analyzed,
                "functions_analyzed": result.functions_analyzed,
                "cache_hits": result.cache_hits,
                "cache_misses": result.cache_misses,
                "skipped_reason": result.skipped_reason,
                "analysis": result.analysis.model_dump() if result.analysis else None,
            })
            
            # Post comment to PR if we have analysis
            if result.analysis and not result.skipped_reason:
                comment_body = format_analysis_comment(result.analysis)
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


def format_analysis_comment(analysis) -> str:
    """Format the analysis result as a GitHub PR comment."""
    from llm.schemas import PRAnalysis, RiskLevel
    
    if not isinstance(analysis, PRAnalysis):
        return "Analysis completed but no detailed results available."
    
    # Risk level emoji/badge
    risk_badges = {
        RiskLevel.LOW: "**Low Risk**",
        RiskLevel.MEDIUM: "**Medium Risk**",
        RiskLevel.HIGH: "**High Risk**",
        RiskLevel.CRITICAL: "**CRITICAL RISK**",
    }
    
    risk_badge = risk_badges.get(analysis.risk_level, "Unknown Risk")
    
    lines = [
        "## C Code Review Analysis",
        "",
        f"### {analysis.headline}",
        "",
        f"**Risk Level:** {risk_badge} ({analysis.risk_score}/100)",
        "",
    ]
    
    if analysis.summary:
        lines.extend([
            "### Summary",
            analysis.summary,
            "",
        ])
    
    if analysis.insights:
        lines.extend([
            "### Key Insights",
            "",
        ])
        for insight in analysis.insights:
            lines.append(f"- {insight}")
        lines.append("")
    
    if analysis.recommendations:
        lines.extend([
            "### Recommendations",
            "",
        ])
        for rec in analysis.recommendations:
            lines.append(f"- {rec}")
        lines.append("")
    
    if analysis.function_analyses:
        lines.extend([
            "### Function-Level Analysis",
            "",
        ])
        for func in analysis.function_analyses[:5]:  # Limit to top 5
            lines.append(f"#### `{func.name}`")
            if func.risk_signals:
                for signal in func.risk_signals:
                    lines.append(f"- {signal}")
            if func.suggestion:
                lines.append(f"- **Suggestion:** {func.suggestion}")
            lines.append("")
    
    lines.extend([
        "---",
        "*Automated analysis by C Code Review Bot*",
    ])
    
    return "\n".join(lines)
