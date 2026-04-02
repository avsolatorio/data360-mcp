#!/usr/bin/env python3
# scripts/sync_github_issues.py
"""Syncs TODO task files with GitHub Issues."""

import os
import re
import subprocess
import yaml
from pathlib import Path
from github import Auth, Github

REPO_SLUG = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GITHUB_TOKEN"]
EVENT_NAME = os.environ.get("GITHUB_EVENT_NAME", "")

STATUS_LABELS = {
    "pending": "status:pending",
    "in_progress": "status:in-progress",
    "done": "status:done",
    "cancelled": "status:cancelled",
    "duplicate": "status:duplicate",
}

PRIORITY_LABELS = {
    "high": "priority:high",
    "medium": "priority:medium",
    "low": "priority:low",
}

CLOSED_STATUSES = {"done", "cancelled", "duplicate"}
SKIP_FILES = {"README.md", "CROSS-REPO-GRAPH.md"}


def parse_task_file(path: Path) -> dict | None:
    """Parse frontmatter + body from a task markdown file."""
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not match:
        return None
    frontmatter = yaml.safe_load(match.group(1))
    body = match.group(2).strip()
    return {"frontmatter": frontmatter, "body": body, "path": path}


def build_issue_body(task: dict) -> str:
    fm = task["frontmatter"]
    lines = [task["body"], "", "---", f"*Task file: `{task['path']}`*"]
    if fm.get("depends_on"):
        lines.append(f"*Depends on: {', '.join(fm['depends_on'])}*")
    if fm.get("blocks"):
        lines.append(f"*Blocks: {', '.join(fm['blocks'])}*")
    return "\n".join(lines)


def ensure_labels(repo, labels: list[str]):
    existing = {l.name for l in repo.get_labels()}
    for label in labels:
        if label not in existing:
            color = "0075ca" if label.startswith("status") else "e4e669"
            repo.create_label(name=label, color=color)


def sync_task(repo, task: dict):
    fm = task["frontmatter"]
    task_id = fm.get("id", "")
    status = fm.get("status", "pending")
    priority = fm.get("priority", "medium")
    assignee = fm.get("assignee")
    issue_number = fm.get("github_issue")

    title = f"[{task_id}] {fm.get('title', '')}"
    body = build_issue_body(task)
    labels = [STATUS_LABELS.get(status, ""), PRIORITY_LABELS.get(priority, "")]
    labels = [l for l in labels if l]
    ensure_labels(repo, labels)

    if issue_number:
        issue = repo.get_issue(issue_number)
        issue.edit(
            title=title,
            body=body,
            state="closed" if status in CLOSED_STATUSES else "open",
            labels=labels,
        )
        if assignee:
            issue.edit(assignee=assignee)
    else:
        kwargs = {"title": title, "body": body, "labels": labels}
        if assignee:
            kwargs["assignee"] = assignee
        issue = repo.create_issue(**kwargs)
        if status in CLOSED_STATUSES:
            issue.edit(state="closed")
        write_issue_number(task["path"], issue.number)

    print(f"  {task_id} → issue #{issue.number} ({status})")


def write_issue_number(path: Path, number: int):
    text = path.read_text()
    if "github_issue:" in text:
        text = re.sub(r"github_issue: \d+", f"github_issue: {number}", text)
    else:
        text = text.replace("---\n", f"---\ngithub_issue: {number}\n", 1)
    path.write_text(text)


def get_changed_task_files(todo_dir: Path) -> list[Path] | None:
    """Return task files touched in the last commit, or None to signal full sync."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD~1", "HEAD", "--", str(todo_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    paths = [
        Path(p.strip())
        for p in result.stdout.splitlines()
        if p.strip() and Path(p.strip()).name not in SKIP_FILES
    ]
    return paths if paths else []


def main():
    g = Github(auth=Auth.Token(TOKEN))
    repo = g.get_repo(REPO_SLUG)
    todo_dir = Path("TODO")

    if not todo_dir.exists():
        print("No TODO directory found.")
        return

    # workflow_dispatch has no meaningful HEAD~1 diff — always do full sync
    if EVENT_NAME == "workflow_dispatch":
        changed = None
    else:
        changed = get_changed_task_files(todo_dir)

    if changed is None:
        task_files = [f for f in todo_dir.glob("*.md") if f.name not in SKIP_FILES]
        print(f"Full sync: {len(task_files)} task files")
    elif not changed:
        print("No task files changed — nothing to sync.")
        return
    else:
        task_files = [f for f in changed if f.exists()]
        print(f"Incremental sync: {len(task_files)} changed task file(s)")

    for path in sorted(task_files):
        task = parse_task_file(path)
        if task and task["frontmatter"].get("id"):
            sync_task(repo, task)


if __name__ == "__main__":
    main()
