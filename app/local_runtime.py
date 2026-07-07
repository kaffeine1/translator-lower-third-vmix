# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Local-provider runtime pack: download, install and activate at runtime.

The local providers (Faster-Whisper, MarianMT) need heavy Python packages
(torch, transformers, ctranslate2, ...) that would triple the installer size,
so they are NOT bundled. Instead they are published as a "runtime pack" (a zip
of a ``pip install --target`` tree built for the same Python/platform as the
frozen app) attached to a GitHub release. This module downloads that pack with
progress, verifies its SHA-256, extracts it under the user's local app data and
appends it to ``sys.path`` — after which the optional imports simply work, no
reinstall and no restart required (a previously failed ``import`` is not
cached, so retrying after activation succeeds).

The download URL/hash are versioned constants: a new pack means a new release
asset and a constants bump. Everything is injectable for tests (no network).
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

from app.i18n import t

logger = logging.getLogger("app.local_runtime")

# Versioned runtime pack (Python 3.14 x64, CPU torch). Bump PACK_VERSION when
# publishing a new asset; old installs are ignored thanks to the versioned dir.
PACK_VERSION = "py314-cpu-1"
PACK_URL = (
    "https://github.com/kaffeine1/translator-lower-third-vmix/releases/download/"
    f"local-runtime-{PACK_VERSION}/local-runtime-{PACK_VERSION}.zip"
)
PACK_SHA256 = "96c88e1878b7bb13f32a069b6f8315131153fa6b4d3718b633f48a3b4fd3c1e2"
PACK_SIZE_BYTES = 235_884_766  # informative, for the progress bar before headers arrive

# marker written after a fully verified extraction: a partial/aborted install
# (crash mid-extract) is never mistaken for a working runtime
_COMPLETE_MARKER = ".complete"

ProgressCallback = Callable[[int, int], None]  # (done_bytes, total_bytes or 0)


class LocalRuntimeError(Exception):
    """Runtime-pack error with an operator-readable message (Italian)."""


def runtime_dir() -> Path:
    """Versioned install directory under the user's local app data."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "TranslatorLowerThird" / "local_runtime" / PACK_VERSION


def is_installed(directory: Path | None = None) -> bool:
    directory = directory or runtime_dir()
    return (directory / _COMPLETE_MARKER).exists()


def activate(directory: Path | None = None) -> bool:
    """Append the runtime to sys.path (idempotent). True if active.

    Appended, not prepended: packages bundled in the frozen app (numpy, ...)
    must keep winning over any copy inside the pack.
    """
    directory = directory or runtime_dir()
    if not is_installed(directory):
        return False
    path = str(directory)
    if path not in sys.path:
        sys.path.append(path)
        logger.info("Runtime locale attivato: %s", path)
    return True


def _download(
    url: str,
    destination: Path,
    progress: ProgressCallback | None,
    opener=None,
) -> None:
    """Stream ``url`` to ``destination`` reporting progress. httpx by default."""
    if opener is None:
        import httpx

        def opener(u):  # pragma: no cover - thin wrapper, exercised live
            return httpx.stream("GET", u, follow_redirects=True, timeout=60.0)

    with opener(url) as response:
        status = getattr(response, "status_code", 200)
        if status != 200:
            raise LocalRuntimeError(t("runtime.download_failed"))
        total = int(response.headers.get("content-length", 0)) or PACK_SIZE_BYTES
        done = 0
        with open(destination, "wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def download_and_install(
    progress: ProgressCallback | None = None,
    *,
    url: str | None = None,
    sha256: str | None = None,
    directory: Path | None = None,
    opener=None,
) -> Path:
    """Download the runtime pack, verify it, extract it and activate it.

    Raises LocalRuntimeError with an operator-readable message on failure.
    Safe to re-run: a complete install short-circuits, a partial one is redone.
    """
    directory = directory or runtime_dir()
    if is_installed(directory):
        activate(directory)
        return directory
    url = url or PACK_URL
    sha256 = PACK_SHA256 if sha256 is None else sha256

    directory.mkdir(parents=True, exist_ok=True)
    archive = directory.parent / f"local-runtime-{PACK_VERSION}.zip.part"
    try:
        try:
            _download(url, archive, progress, opener=opener)
        except LocalRuntimeError:
            raise
        except Exception as exc:
            logger.warning("Download runtime locale fallito: %s", type(exc).__name__)
            raise LocalRuntimeError(t("runtime.download_failed")) from None

        if sha256:
            actual = _sha256(archive)
            if actual != sha256:
                logger.warning("SHA-256 runtime non corrispondente: %s", actual)
                raise LocalRuntimeError(t("runtime.checksum_mismatch"))

        try:
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(directory)
        except zipfile.BadZipFile:
            raise LocalRuntimeError(t("runtime.archive_corrupt")) from None

        (directory / _COMPLETE_MARKER).write_text(PACK_VERSION, encoding="utf-8")
    finally:
        archive.unlink(missing_ok=True)

    activate(directory)
    logger.info("Runtime locale installato in %s", directory)
    return directory


# ------------------------------------------------------------------ models

StatusCallback = Callable[[str], None]

# throttle for the MB-progress status updates during model downloads
_MODEL_PROGRESS_EVERY_S = 0.5


def _progress_tqdm(status: StatusCallback | None, repo: str):
    """A tqdm subclass for snapshot_download that reports cumulative MB.

    Large models (large-v3 is ~3 GB) with only a busy indicator look frozen and
    operators give up: routing hf's byte updates into the status callback shows
    real movement. Console output is disabled (the frozen app has no stderr).
    """
    import time

    from huggingface_hub.utils import tqdm as base_tqdm

    state = {"bytes": 0, "last": 0.0}

    class _StatusTqdm(base_tqdm):
        def __init__(self, *args, **kwargs) -> None:
            # captured before init: a disabled tqdm skips setting self.unit
            self._reports_bytes = kwargs.get("unit") == "B"
            kwargs["disable"] = True  # no console writing, we only count bytes
            super().__init__(*args, **kwargs)

        def update(self, n=1):
            if status is not None and n and self._reports_bytes:
                state["bytes"] += int(n)
                now = time.monotonic()
                if now - state["last"] >= _MODEL_PROGRESS_EVERY_S:
                    state["last"] = now
                    status(
                        t(
                            "runtime.downloading_model_mb",
                            name=repo,
                            mb=state["bytes"] // 1_000_000,
                        )
                    )
            return super().update(n)

    return _StatusTqdm


def whisper_repo(model: str) -> str:
    """Hugging Face repo of the faster-whisper checkpoints (Systran)."""
    return f"Systran/faster-whisper-{model}"


def required_model_repos(
    local_model: str, source_language: str, target_language: str
) -> list[str]:
    """The model repos the local pipeline needs for this configuration.

    With source == target (captioning-only) the translation model is skipped.
    """
    repos = [whisper_repo(local_model)]
    source = (source_language or "").strip().lower()
    target = (target_language or "").strip().lower()
    if source and target and source != target:
        from app.providers.local_translate import default_model_name

        repos.append(default_model_name(source, target))
    return repos


def models_cached(
    local_model: str,
    source_language: str,
    target_language: str,
    checker=None,
) -> bool | None:
    """Whether the models for this configuration are already downloaded.

    Disk-only check (no network). Returns None when it cannot tell (runtime
    components not installed) — callers should then simply say nothing.
    """
    if checker is None:
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            return None

        def checker(repo: str) -> bool:
            try:
                snapshot_download(repo, local_files_only=True)
                return True
            except Exception:
                return False

    return all(
        checker(repo)
        for repo in required_model_repos(local_model, source_language, target_language)
    )


def download_models(
    local_model: str,
    source_language: str,
    target_language: str,
    status: StatusCallback | None = None,
    downloader=None,
) -> None:
    """Pre-download the models used by the local pipeline into the HF cache.

    Makes the first START instant instead of stalling on a hundreds-of-MB
    download. With source == target (captioning-only) the translation model is
    skipped. Requires the runtime (or a dev env) to be importable.
    """
    if downloader is None:
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            raise LocalRuntimeError(t("runtime.not_installed")) from None

        def downloader(repo: str) -> None:
            snapshot_download(repo, tqdm_class=_progress_tqdm(status, repo))

    repos = required_model_repos(local_model, source_language, target_language)
    for repo in repos:
        if status is not None:
            status(t("runtime.downloading_model", name=repo))
        logger.info("Download modello avviato: %s", repo)
        try:
            downloader(repo)
        except Exception as exc:
            logger.warning("Download modello fallito (%s): %s", repo, type(exc).__name__)
            raise LocalRuntimeError(t("runtime.model_download_failed", name=repo)) from None
        logger.info("Download modello completato: %s", repo)
