import shutil
import subprocess
import pathlib
import logging
import os

logger = logging.getLogger(__name__)

AGENT_DIR = pathlib.Path("/hyperagent/agent")
GIT_DIR = pathlib.Path("/hyperagent/agent_git/")
AGENT_BRANCH = "working"


def git_check():
    GIT_DIR.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["GIT_DIR"] = str(GIT_DIR)
    env["GIT_WORK_TREE"] = str(AGENT_DIR)

    check_init = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=AGENT_DIR,
        capture_output=True,
        text=True,
        env=env
    )

    if check_init.returncode != 0:
        logger.info(f"Initializing Git repository: {GIT_DIR}")

        if GIT_DIR.exists():
            for item in GIT_DIR.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

        subprocess.run(
            ["git", "init", "--bare", str(GIT_DIR)],
            check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "agent@hyper.local"],
            cwd=AGENT_DIR, env=env, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Hyper Agent"],
            cwd=AGENT_DIR, env=env, check=True
        )

    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=AGENT_DIR, capture_output=True, text=True, env=env
    )
    current_branch = result.stdout.strip()

    if current_branch != AGENT_BRANCH:
        check = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{AGENT_BRANCH}"],
            cwd=AGENT_DIR, env=env
        )
        if check.returncode == 0:
            subprocess.run(
                ["git", "switch", AGENT_BRANCH],
                cwd=AGENT_DIR, check=True, env=env
            )
        else:
            if current_branch:
                subprocess.run(
                    ["git", "switch", "-c", AGENT_BRANCH],
                    cwd=AGENT_DIR, check=True, env=env
                )

    subprocess.run(
        ["git", "add", "."],
        cwd=AGENT_DIR, check=True, env=env
    )

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=AGENT_DIR, capture_output=True, text=True, env=env
    )

    if result.returncode != 0:
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=AGENT_DIR, capture_output=True, text=True, env=env
        )

        if not status_result.stdout.strip():
            logger.info("Agent directory is empty")
            (AGENT_DIR / ".gitkeep").touch()
            subprocess.run(
                ["git", "add", ".gitkeep"],
                cwd=AGENT_DIR, check=True, env=env
            )

        subprocess.run(
            ["git", "commit", "-m", "Initial STABLE state"],
            cwd=AGENT_DIR, capture_output=True, text=True, env=env
        )

        current = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=AGENT_DIR, capture_output=True, text=True, env=env
        ).stdout.strip()

        if current != AGENT_BRANCH:
            subprocess.run(
                ["git", "switch", "-c", AGENT_BRANCH],
                cwd=AGENT_DIR, check=True, env=env
            )
    else:
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=AGENT_DIR, capture_output=True, text=True, env=env
        )

        if status_result.stdout.strip():
            subprocess.run(
                ["git", "commit", "-m", "STABLE state (auto-commit on startup)"],
                cwd=AGENT_DIR, capture_output=True, text=True, env=env
            )
            logger.info("Created new commit")
        else:
            logger.info("No changes to commit")
            return None

    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=AGENT_DIR, capture_output=True, text=True, env=env
    )
    sha = sha_result.stdout.strip()
    logger.info(f"SHA: {sha}")
    return sha

