"""Storage backends for the study site: a local folder, or a PRIVATE Hugging Face dataset (Space deployment)."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path


class LocalStore:
    def __init__(self, root):
        self.root = Path(root)

    def exists(self, rel):
        return (self.root / rel).exists()

    def read_json(self, rel):
        try:
            return json.loads((self.root / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write(self, rel, data: bytes):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)

    def path(self, rel):
        return str(self.root / rel)

    def list(self, prefix):
        base = self.root / prefix
        return sorted(str(p.relative_to(self.root)).replace("\\", "/") for p in base.rglob("*") if p.is_file()) \
            if base.exists() else []


class HFStore:
    def __init__(self, repo, token):
        from huggingface_hub import HfApi
        self.api, self.repo, self.token = HfApi(token=token), repo, token

    def exists(self, rel):
        return self.api.file_exists(self.repo, rel, repo_type="dataset")

    def path(self, rel):
        from huggingface_hub import hf_hub_download
        try:
            from huggingface_hub.errors import EntryNotFoundError
        except ImportError:
            from huggingface_hub.utils import EntryNotFoundError
        try:
            return hf_hub_download(self.repo, rel, repo_type="dataset", token=self.token)
        except EntryNotFoundError:
            return None

    def read_json(self, rel):
        p = self.path(rel)
        return json.loads(Path(p).read_text(encoding="utf-8")) if p else None

    def write(self, rel, data: bytes):
        self.api.upload_file(path_or_fileobj=io.BytesIO(data), path_in_repo=rel, repo_id=self.repo,
                             repo_type="dataset", commit_message=f"study: {rel.split('/')[0]}")

    def list(self, prefix):
        return sorted(f for f in self.api.list_repo_files(self.repo, repo_type="dataset") if f.startswith(prefix))


def get_store():
    repo = os.environ.get("STUDY_HF_DATASET")
    if repo:
        return HFStore(repo, os.environ.get("HF_TOKEN"))
    return LocalStore(os.environ.get("STUDY_DIR", r"D:\fashion_project_data\user_study"))


def write_json(st, rel, obj):
    st.write(rel, json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8"))
