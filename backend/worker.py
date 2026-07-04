# import json
# from github_utils.webhook import process_pr_job

# def lambda_handler(event, context):
#     """
#     Handles jobs from SQS
#     """
#     for record in event['Records']:
#         job_data = json.loads(record['body'])
#         try:
#             process_pr_job(
#                 job_id=job_data["job_id"],
#                 owner=job_data["owner"],
#                 repo_name=job_data["repo_name"],
#                 pr_number=job_data["pr_number"],
#                 installation_id=job_data["installation_id"]
#             )
#         except Exception as e:
#             print(f"Job {job_data['job_id']} failed: {e}")
"""
worker.py — Lambda entry point for background PR analysis

This handler is invoked asynchronously (InvocationType='Event') by the api
Lambda via boto3. It has a 900s timeout and no API Gateway in front of it,
so it can run the full pipeline without the 30s ceiling.

WHY init_redis() IS CALLED HERE:
  The FastAPI lifespan hook (main.py) that normally calls init_redis() only
  runs inside the Mangum/FastAPI app. This Lambda handler bypasses FastAPI
  entirely — it is a plain Lambda handler, not an HTTP request. Without
  explicitly calling init_redis(), redis_client stays None for the entire
  invocation, update_job_status() silently returns False, and the job is
  never marked as processing/completed/failed, leaving it stuck as "pending".
"""

import asyncio
import logging

from cache.redis import init_redis
from github_utils.webhook import process_pr_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def _run(event: dict) -> None:
    """Initialise dependencies then run the pipeline."""
    # Must be called before any Redis operations.
    # In the api Lambda this is done by the FastAPI lifespan hook;
    # here we do it explicitly.
    await init_redis()

    # Warm up the tree-sitter parser (same as FastAPI lifespan)
    from core.parser import extract_file_ast
    extract_file_ast("int main() { return 0; }")

    await process_pr_job(
        job_id=event["job_id"],
        owner=event["owner"],
        repo_name=event["repo_name"],
        pr_number=event["pr_number"],
        installation_id=event.get("installation_id"),
        post_comment=event.get("post_comment", True),
    )


def lambda_handler(event: dict, context) -> None:
    """
    Lambda entry point.

    asyncio.run() is correct here: this is a plain synchronous Lambda handler
    (not inside FastAPI/Mangum), so there is no existing event loop to conflict
    with. asyncio.run() creates a fresh loop, runs _run() to completion, then
    closes the loop cleanly.
    """
    logger.info(f"Worker invoked for job: {event.get('job_id')}")
    try:
        asyncio.run(_run(event))
        logger.info(f"Worker completed for job: {event.get('job_id')}")
    except Exception:
        # process_pr_job has its own try/except that writes "failed" to Redis.
        # This outer catch is a last-resort log for crashes before/after that.
        logger.exception(f"Worker crashed for job: {event.get('job_id')}")
        raise  # Re-raise so Lambda marks the invocation as failed in CloudWatch