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
import shutil
import sys
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.i18n import t

logger = logging.getLogger("app.local_runtime")

# Configure huggingface_hub BEFORE it is ever imported (it reads these at import
# time). Use the classic HTTP download, not Xet: the classic path writes the file
# into the cache dir incrementally, so polling that dir shows a real advancing
# progress bar — Xet stages large files elsewhere and materializes them only at
# the end, so the bar would look frozen. Also silence hf's console bars (no
# stderr when frozen) and give each request more slack than the 10 s default (the
# retry then resumes from the partial file on a dropped connection). This module
# is imported at startup, before any provider pulls in huggingface_hub.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")

# Versioned runtime packs (Python 3.14 x64). One per device: the CPU pack is
# torch-cpu + CTranslate2 (CPU); the CUDA pack adds the NVIDIA libraries so
# faster-whisper runs on GPU without a system CUDA install. Bump the version
# when publishing a new asset; old installs are ignored thanks to the versioned
# install directory (the two packs coexist because their versions differ).
@dataclass(frozen=True)
class RuntimePack:
    version: str
    sha256: str
    size_bytes: int
    device: str  # "cpu" | "cuda"

    @property
    def url(self) -> str:
        return (
            "https://github.com/kaffeine1/translator-lower-third-vmix/releases/download/"
            f"local-runtime-{self.version}/local-runtime-{self.version}.zip"
        )


PACKS: dict[str, RuntimePack] = {
    "cpu": RuntimePack(
        "py314-cpu-1",
        "96c88e1878b7bb13f32a069b6f8315131153fa6b4d3718b633f48a3b4fd3c1e2",
        235_884_766,
        "cpu",
    ),
    "cuda": RuntimePack(
        "py314-cu124-1",
        "24b1694518072a7cad2fc43b92bd7513b39cb2c8628d0248390d670e5bc8dd5a",
        1_200_018_280,
        "cuda",
    ),
}


def pack_for(device: str | None) -> RuntimePack:
    return PACKS["cuda"] if (device or "").strip().lower() == "cuda" else PACKS["cpu"]


# back-compat aliases: settings/wizard/tests still import these (CPU pack)
PACK_VERSION = PACKS["cpu"].version
PACK_URL = PACKS["cpu"].url
PACK_SHA256 = PACKS["cpu"].sha256
PACK_SIZE_BYTES = PACKS["cpu"].size_bytes

# marker written after a fully verified extraction: a partial/aborted install
# (crash mid-extract) is never mistaken for a working runtime
_COMPLETE_MARKER = ".complete"

# add_dll_directory handles must outlive the process, or the directories are
# dropped when the returned cookies are garbage-collected
_dll_dirs: list = []

ProgressCallback = Callable[[int, int], None]  # (done_bytes, total_bytes or 0)


class LocalRuntimeError(Exception):
    """Runtime-pack error with an operator-readable message (Italian)."""


def runtime_dir(device: str = "cpu") -> Path:
    """Versioned install directory (per device) under the user's local app data."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "TranslatorLowerThird" / "local_runtime" / pack_for(device).version


def is_installed(directory: Path | None = None, device: str = "cpu") -> bool:
    directory = directory or runtime_dir(device)
    return (directory / _COMPLETE_MARKER).exists()


def activate(directory: Path | None = None, device: str = "cpu", *, dll_registrar=None) -> bool:
    """Append the runtime to sys.path (idempotent). True if active.

    Appended, not prepended: packages bundled in the frozen app (numpy, ...)
    must keep winning over any copy inside the pack. For the CUDA pack, the
    NVIDIA DLLs live under nvidia\\*\\bin (not next to ctranslate2.dll), so PATH
    won't find them: register those directories with os.add_dll_directory before
    the first `import faster_whisper` (activate runs at startup / end of install,
    both before any provider import).
    """
    pack = pack_for(device)
    directory = directory or runtime_dir(device)
    if not is_installed(directory):
        return False
    path = str(directory)
    if path not in sys.path:
        sys.path.append(path)
        logger.info("Runtime locale attivato: %s", path)
    if pack.device == "cuda" and (dll_registrar is not None or sys.platform == "win32"):
        register = dll_registrar or getattr(os, "add_dll_directory", None)
        bindirs = [b for b in sorted((directory / "nvidia").glob("*/bin")) if b.is_dir()]
        for bindir in bindirs:
            if register is not None:
                _dll_dirs.append(register(str(bindir)))
            # also prepend to PATH: cuDNN 9's own loader resolves its secondary
            # DLLs (cudnn_ops/cnn/…) via the plain search path and does NOT
            # always honor add_dll_directory, so without PATH it fails to load
            # even though the DLLs are present
            current = os.environ.get("PATH", "")
            if str(bindir) not in current:
                os.environ["PATH"] = str(bindir) + os.pathsep + current
            logger.info("CUDA DLL dir registrata: %s", bindir)
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
    device: str = "cpu",
    url: str | None = None,
    sha256: str | None = None,
    directory: Path | None = None,
    opener=None,
    force: bool = False,
) -> Path:
    """Download the runtime pack for ``device``, verify it, extract, activate it.

    Raises LocalRuntimeError with an operator-readable message on failure.
    Safe to re-run: a complete install short-circuits, a partial one is redone.
    ``force`` re-downloads even when the marker is present — needed to repair a
    pack whose files were removed (e.g. by disk cleanup or antivirus) while the
    ``.complete`` marker survived, which otherwise looks installed but cannot
    import.
    """
    pack = pack_for(device)
    directory = directory or runtime_dir(device)
    if is_installed(directory) and not force:
        activate(directory, device=device)
        return directory
    # clear the marker up front so a failed repair does not keep looking complete
    (directory / _COMPLETE_MARKER).unlink(missing_ok=True)
    url = url or pack.url
    sha256 = pack.sha256 if sha256 is None else sha256

    directory.mkdir(parents=True, exist_ok=True)
    archive = directory.parent / f"local-runtime-{pack.version}.zip.part"
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

        (directory / _COMPLETE_MARKER).write_text(pack.version, encoding="utf-8")
    finally:
        archive.unlink(missing_ok=True)

    activate(directory, device=device)
    logger.info("Runtime locale installato in %s", directory)
    return directory


# ------------------------------------------------------------------ models

StatusCallback = Callable[[str], None]

# throttle for the MB-progress status updates during model downloads
_MODEL_PROGRESS_EVERY_S = 0.5

# how many times a single model download is retried before giving up: a large
# model over a flaky link can drop several times, and each retry resumes.
_MODEL_DOWNLOAD_ATTEMPTS = 4


def _download_repo_with_retries(
    fetch: Callable[[str], None], repo: str, status: StatusCallback | None = None
) -> None:
    """Call ``fetch(repo)``, retrying transient failures with backoff.

    Between attempts it waits (2 s, 4 s, 8 s…) and re-runs the fetch; the
    Hugging Face cache keeps the partial file, so a retry RESUMES the download
    instead of starting over. Raises the last error if every attempt fails.
    """
    for attempt in range(1, _MODEL_DOWNLOAD_ATTEMPTS + 1):
        try:
            fetch(repo)
            return
        except Exception:
            logger.warning(
                "Download modello %s: tentativo %d/%d fallito",
                repo,
                attempt,
                _MODEL_DOWNLOAD_ATTEMPTS,
                exc_info=True,
            )
            if attempt >= _MODEL_DOWNLOAD_ATTEMPTS:
                raise
            if status is not None:
                status(
                    t(
                        "runtime.model_retry",
                        name=repo,
                        attempt=attempt + 1,
                        total=_MODEL_DOWNLOAD_ATTEMPTS,
                    )
                )
            time.sleep(min(2**attempt, 15))


# Only cache directories with these prefixes are OURS to manage/remove: the
# HF cache may also hold models of other applications.
_MODEL_DIR_PREFIXES = (
    "models--Systran--faster-whisper-",
    "models--Helsinki-NLP--opus-mt-",
)


@dataclass(frozen=True)
class DownloadedModel:
    repo: str
    path: Path
    size_bytes: int


def _hf_cache_dir() -> Path:
    """The Hugging Face hub cache directory (no hf import required)."""
    env = os.environ.get("HF_HUB_CACHE")
    if env:
        return Path(env)
    home = os.environ.get("HF_HOME")
    if home:
        return Path(home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def downloaded_models() -> list[DownloadedModel]:
    """The local-provider models currently in the cache, with their size."""
    cache = _hf_cache_dir()
    if not cache.is_dir():
        return []
    result: list[DownloadedModel] = []
    for entry in sorted(cache.iterdir()):
        if not entry.is_dir() or not entry.name.startswith(_MODEL_DIR_PREFIXES):
            continue
        size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
        org, _, model = entry.name[len("models--") :].partition("--")
        result.append(DownloadedModel(f"{org}/{model}", entry, size))
    return result


def remove_downloaded_models() -> tuple[int, list[str]]:
    """Delete the local-provider models from the cache to free disk space.

    They can be re-downloaded at any time. Returns (freed bytes, repos that
    could NOT be removed — e.g. model files locked by a running translation).
    """
    freed = 0
    failed: list[str] = []
    for model in downloaded_models():
        try:
            shutil.rmtree(model.path)
        except OSError:
            logger.warning("Rimozione modello fallita: %s", model.repo)
            failed.append(model.repo)
            continue
        logger.info("Modello rimosso: %s (%d MB)", model.repo, model.size_bytes // 1_000_000)
        freed += model.size_bytes
    return freed, failed


def _repo_cache_dir(repo: str) -> Path:
    """The Hugging Face cache directory for a repo (models--org--name)."""
    return _hf_cache_dir() / ("models--" + repo.replace("/", "--"))


def _dir_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _repo_total_bytes(repo: str, model_info=None) -> int:
    """Total download size of a repo from the Hub metadata (0 if unknown).

    ``model_info`` is injectable for tests; by default it is HfApi().model_info.
    """
    if model_info is None:
        try:
            from huggingface_hub import HfApi
        except ImportError:
            return 0
        model_info = HfApi().model_info
    try:
        info = model_info(repo, files_metadata=True)
        return sum(int(getattr(s, "size", 0) or 0) for s in (info.siblings or []))
    except Exception:
        logger.warning("Dimensione del modello %s non disponibile", repo, exc_info=True)
        return 0


def _download_repo_with_progress(repo, fetch, progress, total_fn=None) -> None:
    """Run ``fetch(repo)`` while polling the repo's cache directory against its
    total size, so the GUI can show a determinate progress bar.

    The download backend does not report bytes through tqdm (Xet, disabled for
    model downloads, would stage large files elsewhere; the classic path writes
    them into the cache dir incrementally), so progress is measured by how much
    of the repo is on disk. No polling when ``progress`` is None or the total is
    unknown — the bar then stays a busy indicator.
    """
    if progress is None:
        fetch(repo)
        return
    total = (total_fn or _repo_total_bytes)(repo)
    cache = _repo_cache_dir(repo)
    stop = threading.Event()

    def poll() -> None:
        while not stop.wait(_MODEL_PROGRESS_EVERY_S):
            progress(min(_dir_size(cache), total), total)

    poller = threading.Thread(target=poll, name="model-progress", daemon=True)
    if total > 0:
        poller.start()
    try:
        fetch(repo)
    finally:
        stop.set()
        if total > 0:
            poller.join(timeout=2)
    if total > 0:
        progress(total, total)  # snap to 100% (dir size may differ slightly)


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
    progress: ProgressCallback | None = None,
) -> None:
    """Pre-download the models used by the local pipeline into the HF cache.

    Makes the first START instant instead of stalling on a hundreds-of-MB
    download. With source == target (captioning-only) the translation model is
    skipped. Requires the runtime (or a dev env) to be importable. ``status``
    receives which model is being fetched; ``progress`` receives (done, total)
    bytes for a determinate progress bar (like the component download).
    """
    if downloader is None:
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            raise LocalRuntimeError(t("runtime.not_installed")) from None

        # Xet is disabled at module import (see top of file) so the classic path
        # writes into the cache dir incrementally and the poller can show a real
        # progress bar; the retry resumes from the partial file on a drop.
        def downloader(repo: str) -> None:
            _download_repo_with_retries(lambda r: snapshot_download(r), repo, status)

    repos = required_model_repos(local_model, source_language, target_language)
    for repo in repos:
        if status is not None:
            status(t("runtime.downloading_model", name=repo))
        logger.info("Download modello avviato: %s", repo)
        try:
            _download_repo_with_progress(repo, downloader, progress)
        except Exception:
            # full traceback in the log (public repos, no secrets): "OSError"
            # alone proved undiagnosable in the field
            logger.warning("Download modello fallito (%s)", repo, exc_info=True)
            raise LocalRuntimeError(t("runtime.model_download_failed", name=repo)) from None
        logger.info("Download modello completato: %s", repo)
