"""
github/client.py — PyGithub wrapper for PR operations

Provides async-compatible methods for:
- Fetching PR details and files
- Getting file content at specific SHAs
- Posting review comments
- Creating check runs

Uses PyGithub under the hood but wraps sync calls in asyncio.to_thread
for non-blocking operation in FastAPI.
"""

from __future__ import annotations
import os
import asyncio
from typing import Optional
from functools import cached_property

from github import Github, GithubIntegration, Auth
from github.PullRequest import PullRequest
from github.Repository import Repository
from dotenv import load_dotenv

load_dotenv()

class GitHubClient:
    """
    Async-compatible GitHub API client.
    
    Can be initialized with:
    - Personal access token (for testing)
    - GitHub App credentials (for production)
    """
    
    def __init__(
        self,
        token: Optional[str] = None,
        app_id: Optional[str] = None,
        private_key: Optional[str] = None,
    ):
        self._token = token or os.environ.get("GITHUB_TOKEN")
        self._app_id = app_id or os.environ.get("GITHUB_APP_ID")
        self._private_key = private_key or os.environ.get("GITHUB_PRIVATE_KEY")
        
        self._github: Optional[Github] = None
        self._installation_tokens: dict[int, str] = {}
    
    def _get_github(self, installation_id: Optional[int] = None) -> Github:
        """Get a Github instance, optionally for a specific installation."""
        
        # If we have a personal access token, use it
        if self._token:
            return Github(auth=Auth.Token(self._token))
        
        # If we have app credentials and an installation ID, get an installation token
        if self._app_id and self._private_key and installation_id:
            if installation_id not in self._installation_tokens:
                auth = Auth.AppAuth(int(self._app_id), self._private_key)
                gi = GithubIntegration(auth=auth)
                installation = gi.get_installation(installation_id)
                token = gi.get_access_token(installation.id).token
                self._installation_tokens[installation_id] = token
            
            return Github(auth=Auth.Token(self._installation_tokens[installation_id]))
        
        # Fall back to unauthenticated (rate-limited)
        return Github()
    
    async def get_pr_info(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        installation_id: Optional[int] = None,
    ) -> Optional[dict]:
        """
        Fetch PR information including base/head SHAs.
        
        Returns dict with:
        - number: PR number
        - title: PR title
        - body: PR description
        - base: {sha, ref} - base branch info
        - head: {sha, ref} - head branch info
        - state: open/closed
        - user: {login} - author info
        """
        def _sync():
            gh = self._get_github(installation_id)
            try:
                repo_obj = gh.get_repo(f"{owner}/{repo}")
                pr = repo_obj.get_pull(pr_number)
                return {
                    "number": pr.number,
                    "title": pr.title,
                    "body": pr.body or "",
                    "base": {
                        "sha": pr.base.sha,
                        "ref": pr.base.ref,
                    },
                    "head": {
                        "sha": pr.head.sha,
                        "ref": pr.head.ref,
                    },
                    "state": pr.state,
                    "user": {
                        "login": pr.user.login,
                    },
                }
            except Exception as e:
                print(f"Error fetching PR info: {e}")
                return None
        
        return await asyncio.to_thread(_sync)
    
    async def get_pr_files(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        installation_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Get list of files changed in a PR.
        
        Returns list of dicts with:
        - filename: file path
        - status: added/removed/modified/renamed
        - additions: lines added
        - deletions: lines removed
        - changes: total lines changed
        - patch: unified diff (if available)
        - previous_filename: for renames
        """
        def _sync():
            gh = self._get_github(installation_id)
            try:
                repo_obj = gh.get_repo(f"{owner}/{repo}")
                pr = repo_obj.get_pull(pr_number)
                files = pr.get_files()
                return [
                    {
                        "filename": f.filename,
                        "status": f.status,
                        "additions": f.additions,
                        "deletions": f.deletions,
                        "changes": f.changes,
                        "patch": f.patch or "",
                        "previous_filename": f.previous_filename,
                    }
                    for f in files
                ]
            except Exception as e:
                print(f"Error fetching PR files: {e}")
                return []
        
        return await asyncio.to_thread(_sync)
    
    async def get_file_content(
        self,
        owner: str,
        repo: str,
        sha: str,
        filepath: str,
        installation_id: Optional[int] = None,
    ) -> Optional[str]:
        """
        Fetch file content at a specific commit SHA.
        
        Returns the file content as a string, or None if not found.
        """
        def _sync():
            gh = self._get_github(installation_id)
            try:
                repo_obj = gh.get_repo(f"{owner}/{repo}")
                content = repo_obj.get_contents(filepath, ref=sha)
                
                # get_contents can return a list for directories
                if isinstance(content, list):
                    return None
                
                return content.decoded_content.decode("utf-8", errors="replace")
            except Exception as e:
                # File might not exist at this SHA (e.g., newly added file)
                return None
        
        return await asyncio.to_thread(_sync)
    
    async def post_pr_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        installation_id: Optional[int] = None,
    ) -> bool:
        """
        Post a comment on a PR.
        
        Returns True on success, False on failure.
        """
        def _sync():
            gh = self._get_github(installation_id)
            try:
                repo_obj = gh.get_repo(f"{owner}/{repo}")
                pr = repo_obj.get_pull(pr_number)
                pr.create_issue_comment(body)
                return True
            except Exception as e:
                print(f"Error posting comment: {e}")
                return False
        
        return await asyncio.to_thread(_sync)
    
    async def post_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        event: str = "COMMENT",  # APPROVE, REQUEST_CHANGES, COMMENT
        comments: Optional[list[dict]] = None,
        installation_id: Optional[int] = None,
    ) -> bool:
        """
        Post a review on a PR.
        
        Args:
            body: Review summary
            event: APPROVE, REQUEST_CHANGES, or COMMENT
            comments: List of inline comments with {path, line, body}
        
        Returns True on success, False on failure.
        """
        def _sync():
            gh = self._get_github(installation_id)
            try:
                repo_obj = gh.get_repo(f"{owner}/{repo}")
                pr = repo_obj.get_pull(pr_number)
                
                # Convert comments to PyGithub format
                review_comments = []
                if comments:
                    for c in comments:
                        review_comments.append({
                            "path": c["path"],
                            "line": c["line"],
                            "body": c["body"],
                        })
                
                pr.create_review(
                    body=body,
                    event=event,
                    comments=review_comments if review_comments else None,
                )
                return True
            except Exception as e:
                print(f"Error posting review: {e}")
                return False
        
        return await asyncio.to_thread(_sync)
    
    async def create_check_run(
        self,
        owner: str,
        repo: str,
        head_sha: str,
        name: str,
        status: str = "in_progress",  # queued, in_progress, completed
        conclusion: Optional[str] = None,  # success, failure, neutral, etc.
        output: Optional[dict] = None,  # {title, summary, text}
        installation_id: Optional[int] = None,
    ) -> Optional[int]:
        """
        Create or update a check run.
        
        Returns the check run ID on success, None on failure.
        """
        def _sync():
            gh = self._get_github(installation_id)
            try:
                repo_obj = gh.get_repo(f"{owner}/{repo}")
                
                kwargs = {
                    "name": name,
                    "head_sha": head_sha,
                    "status": status,
                }
                
                if conclusion:
                    kwargs["conclusion"] = conclusion
                
                if output:
                    kwargs["output"] = output
                
                check_run = repo_obj.create_check_run(**kwargs)
                return check_run.id
            except Exception as e:
                print(f"Error creating check run: {e}")
                return None
        
        return await asyncio.to_thread(_sync)
