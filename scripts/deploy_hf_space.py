"""Deploy QueryDoc AI to a Hugging Face Space (Docker SDK, free CPU hardware).

Prerequisites: a Hugging Face account and a login on this machine
(`hf auth login` with a token that has write access).

    python scripts/deploy_hf_space.py --space <user>/querydoc-ai \
        --backup-repo <user>/querydoc-ai-data [--admin-email you@example.com]

What it does:
  1. creates the Space (public) if needed;
  2. with --backup-repo, stores the token as the Space secret HF_TOKEN and sets
     QUERYDOC_HF_BACKUP_REPO so accounts and documents survive restarts in a
     *private* dataset;
  3. uploads the source needed by the Dockerfile; the Space builds the image.
Author: Raahul Sallagunta
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from huggingface_hub import HfApi, get_token

ROOT = Path(__file__).resolve().parents[1]
ALLOW = [
    "Dockerfile", ".dockerignore", "LICENSE", "THIRD_PARTY_NOTICES.md", "README.md",
    "backend/pyproject.toml", "backend/alembic.ini", "backend/app/**", "backend/querydoc/**", "backend/alembic/**",
    "frontend/package.json", "frontend/package-lock.json", "frontend/.npmrc", "frontend/index.html",
    "frontend/vite.config.ts", "frontend/tsconfig*.json", "frontend/components.json",
    "frontend/src/**", "frontend/public/**", "results/**",
]
IGNORE = ["**/__pycache__/**", "**/*.pyc", "results/logs/**", "frontend/src/**/*.test.tsx", "frontend/src/test/**"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space", required=True, help="<user>/<space-name>")
    ap.add_argument("--backup-repo", help="<user>/<dataset-name> (private) for durable accounts and documents")
    ap.add_argument("--admin-email", action="append", default=[], help="account(s) allowed to change server settings")
    args = ap.parse_args()

    token = get_token()
    if not token:
        raise SystemExit("Not logged in to Hugging Face. Run `hf auth login` first.")
    api = HfApi(token=token)
    api.create_repo(args.space, repo_type="space", space_sdk="docker", exist_ok=True)
    if args.backup_repo:
        api.add_space_secret(args.space, "HF_TOKEN", token)
        api.add_space_variable(args.space, "QUERYDOC_HF_BACKUP_REPO", args.backup_repo)
    if args.admin_email:
        api.add_space_variable(args.space, "QUERYDOC_ADMIN_EMAILS", json.dumps(args.admin_email))

    api.upload_folder(repo_id=args.space, repo_type="space", folder_path=ROOT, allow_patterns=ALLOW,
                      ignore_patterns=IGNORE + ["README.md"], commit_message="Deploy QueryDoc AI")
    api.upload_file(repo_id=args.space, repo_type="space", path_or_fileobj=ROOT / "deploy/huggingface/README.md",
                    path_in_repo="README.md", commit_message="Space card")
    user, name = args.space.split("/")
    print(f"Uploaded. Build logs: https://huggingface.co/spaces/{args.space}?logs=build")
    print(f"App URL (after the build, ~15-25 min): https://{user.lower()}-{name.lower().replace('_', '-')}.hf.space")


if __name__ == "__main__":
    main()
