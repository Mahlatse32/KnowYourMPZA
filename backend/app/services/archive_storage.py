from pathlib import Path
from typing import Protocol


class ArchiveStorage(Protocol):
    def write_text(self, path: str, content: str) -> str:
        ...

    def write_bytes(self, path: str, content: bytes) -> str:
        ...


class LocalArchiveStorage:
    def write_text(self, path: str, content: str) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)

    def write_bytes(self, path: str, content: bytes) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return str(target)


class S3ArchiveStorageStub:
    def write_text(self, path: str, content: str) -> str:
        raise NotImplementedError("S3-compatible archive storage is documented but not implemented in V1.")

    def write_bytes(self, path: str, content: bytes) -> str:
        raise NotImplementedError("S3-compatible archive storage is documented but not implemented in V1.")


def get_archive_storage(mode: str = "local") -> ArchiveStorage:
    if mode.lower() == "local":
        return LocalArchiveStorage()
    if mode.lower() in {"s3", "s3-compatible"}:
        return S3ArchiveStorageStub()
    raise ValueError(f"Unsupported archive storage mode: {mode}")
