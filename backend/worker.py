import json
from github_utils.webhook import process_pr_job

def lambda_handler(event, context):
    """
    Handles jobs from SQS
    """
    for record in event['Records']:
        job_data = json.loads(record['body'])
        try:
            process_pr_job(
                job_id=job_data["job_id"],
                owner=job_data["owner"],
                repo_name=job_data["repo_name"],
                pr_number=job_data["pr_number"],
                installation_id=job_data["installation_id"]
            )
        except Exception as e:
            print(f"Job {job_data['job_id']} failed: {e}")