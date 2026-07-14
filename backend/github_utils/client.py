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
import logging
from typing import Optional
from functools import cached_property

from github import Github, GithubIntegration, Auth
from github.PullRequest import PullRequest
from github.Repository import Repository
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

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
                logger.error(f"Error fetching PR info: {e}")
                return None
        
        return await asyncio.to_thread(_sync)
    
    # --- User-token methods (dashboard) --------------------------------
    #
    # These act on behalf of the logged-in user via their GitHub OAuth
    # access token, rather than the app-level PAT/installation token used
    # by the rest of this client. Each call builds its own short-lived
    # Github instance since the token differs per request.

    async def list_user_repos(self, user_token: str, limit: int = 30) -> list[dict]:
        """
        List repos the authenticated user can access (owned, collaborator,
        or org member), most recently pushed first — used for the
        dashboard's "recent repositories" section.
        """
        def _sync():
            gh = Github(auth=Auth.Token(user_token))
            user = gh.get_user()
            repos = user.get_repos(
                sort="pushed",
                direction="desc",
                affiliation="owner,collaborator,organization_member",
            )
            results = []
            for repo in repos[:limit]:
                results.append({
                    "owner": repo.owner.login,
                    "name": repo.name,
                    "full_name": repo.full_name,
                    "avatar_url": repo.owner.avatar_url,
                    "private": repo.private,
                    "description": repo.description,
                    "pushed_at": repo.pushed_at.isoformat() if repo.pushed_at else None,
                })
            return results

        return await asyncio.to_thread(_sync)

    async def list_user_orgs(self, user_token: str) -> list[str]:
        """List org logins the user belongs to, for the 'team PRs' query."""
        def _sync():
            gh = Github(auth=Auth.Token(user_token))
            return [org.login for org in gh.get_user().get_orgs()]

        return await asyncio.to_thread(_sync)

    async def search_pull_requests(
        self,
        user_token: str,
        query: str,
        limit: int = 20,
    ) -> list[dict]:
        """
        Run a GitHub search-issues query scoped to pull requests and
        return lightweight cards for the dashboard.

        Using the Search API (rather than iterating every repo the user
        can see) is what keeps this fast for users with hundreds of repos
        or thousands of open PRs — one API call instead of N.
        """
        def _sync():
            gh = Github(auth=Auth.Token(user_token))
            issues = gh.search_issues(query=query, sort="updated", order="desc")
            results = []
            for issue in issues[:limit]:
                raw = issue.raw_data
                results.append({
                    "number": issue.number,
                    "title": issue.title,
                    "author": issue.user.login,
                    "author_avatar_url": issue.user.avatar_url,
                    "repo_full_name": issue.repository.full_name,
                    "draft": bool(raw.get("draft", False)),
                    "labels": [label.name for label in issue.labels],
                    "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
                    "html_url": issue.html_url,
                })
            return results

        return await asyncio.to_thread(_sync)

    async def list_open_pull_requests(
        self,
        owner: str,
        repo: str,
        user_token: str,
        limit: int = 30,
    ) -> Optional[list[dict]]:
        """
        List open pull requests for a repo, newest first, as the calling user.

        Authenticated with the caller's own GitHub OAuth token rather than an
        installation_id, so results are naturally scoped to repos that user
        can actually see (GitHub itself enforces the access check).

        Returns a list of lightweight dicts (not full PR objects) so the
        dashboard's PR picker can render number/title/author/avatar without
        pulling diffs or file lists. Returns None if the repo/owner can't be
        resolved (e.g. typo, private repo without access) so the caller can
        tell "no open PRs" apart from "couldn't reach that repo".
        """
        def _sync():
            gh = Github(auth=Auth.Token(user_token))
            try:
                repo_obj = gh.get_repo(f"{owner}/{repo}")
                pulls = repo_obj.get_pulls(
                    state="open", sort="created", direction="desc"
                )
                results = []
                for pr in pulls[:limit]:
                    results.append({
                        "number": pr.number,
                        "title": pr.title,
                        "author": pr.user.login,
                        "author_avatar_url": pr.user.avatar_url,
                        "head_ref": pr.head.ref,
                        "base_ref": pr.base.ref,
                        "created_at": pr.created_at.isoformat() if pr.created_at else None,
                        "updated_at": pr.updated_at.isoformat() if pr.updated_at else None,
                        "html_url": pr.html_url,
                    })
                return results
            except Exception as e:
                logger.error(f"Error listing open PRs for {owner}/{repo}: {e}")
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
                logger.error(f"Error fetching PR files: {e}")
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
                logger.error(f"Error posting comment: {e}")
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
                logger.error(f"Error posting review: {e}")
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
                logger.error(f"Error creating check run: {e}")
                return None
        
        return await asyncio.to_thread(_sync)
    