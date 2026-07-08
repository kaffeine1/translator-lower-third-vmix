# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Local-runtime pack tests: download/verify/extract/activate, no network."""

from __future__ import annotations

import hashlib
import io
import sys
import zipfile
from contextlib import contextmanager

import pytest

from app import local_runtime
from app.local_runtime import (
    LocalRuntimeError,
    activate,
    download_and_install,
    download_models,
    is_installed,
    whisper_repo,
)


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def _opener_for(payload: bytes, status_code: int = 200):
    """Fake httpx.stream context manager serving ``payload``."""

    class FakeResponse:
        def __init__(self) -> None:
            self.status_code = status_code
            self.headers = {"content-length": str(len(payload))}

        def iter_bytes(self):
            for i in range(0, len(payload), 4096):
                yield payload[i : i + 4096]

    @contextmanager
    def opener(url):
        yield FakeResponse()

    return opener


def test_install_extracts_verifies_and_activates(tmp_path):
    payload = _zip_bytes({"fake_pkg/__init__.py": "x = 1\n"})
    sha = hashlib.sha256(payload).hexdigest()
    target = tmp_path / "runtime"

    done = download_and_install(
        url="https://example.invalid/pack.zip",
        sha256=sha,
        directory=target,
        opener=_opener_for(payload),
    )
    assert done == target
    assert is_installed(target)
    assert (target / "fake_pkg" / "__init__.py").read_text() == "x = 1\n"
    assert str(target) in sys.path
    sys.path.remove(str(target))  # cleanup for other tests


def test_force_redownloads_over_stale_marker(tmp_path):
    # a pack whose files were removed (disk cleanup / antivirus) while the
    # ".complete" marker survived must be repairable: force re-downloads it
    payload = _zip_bytes({"fake_pkg/__init__.py": "x = 1\n"})
    sha = hashlib.sha256(payload).hexdigest()
    target = tmp_path / "runtime"

    inner = _opener_for(payload)
    calls = {"n": 0}

    def counting_opener(url):
        calls["n"] += 1
        return inner(url)

    download_and_install(url="u", sha256=sha, directory=target, opener=counting_opener)
    assert calls["n"] == 1 and is_installed(target)

    # simulate the gutted pack: file gone, marker still present
    (target / "fake_pkg" / "__init__.py").unlink()

    # a normal re-run short-circuits on the marker (no repair, no download)
    download_and_install(url="u", sha256=sha, directory=target, opener=counting_opener)
    assert calls["n"] == 1
    assert not (target / "fake_pkg" / "__init__.py").exists()

    # force re-downloads and restores the files
    download_and_install(
        url="u", sha256=sha, directory=target, opener=counting_opener, force=True
    )
    assert calls["n"] == 2
    assert (target / "fake_pkg" / "__init__.py").read_text() == "x = 1\n"
    assert is_installed(target)
    if str(target) in sys.path:
        sys.path.remove(str(target))


def test_install_reports_progress(tmp_path):
    payload = _zip_bytes({"a.py": "1"})
    calls: list[tuple[int, int]] = []
    download_and_install(
        url="u",
        sha256="",  # empty hash = skip verification
        directory=tmp_path / "r",
        opener=_opener_for(payload),
        progress=lambda done, total: calls.append((done, total)),
    )
    assert calls and calls[-1][0] == len(payload)
    sys.path.remove(str(tmp_path / "r"))


def test_install_rejects_checksum_mismatch(tmp_path):
    payload = _zip_bytes({"a.py": "1"})
    target = tmp_path / "r"
    with pytest.raises(LocalRuntimeError):
        download_and_install(
            url="u", sha256="0" * 64, directory=target, opener=_opener_for(payload)
        )
    assert not is_installed(target)  # partial install never looks complete
    assert not list(target.parent.glob("*.part"))  # temp archive removed


def test_install_rejects_corrupt_archive(tmp_path):
    target = tmp_path / "r"
    with pytest.raises(LocalRuntimeError):
        download_and_install(
            url="u", sha256="", directory=target, opener=_opener_for(b"not a zip")
        )
    assert not is_installed(target)


def test_install_rejects_http_error(tmp_path):
    target = tmp_path / "r"
    with pytest.raises(LocalRuntimeError):
        download_and_install(
            url="u",
            sha256="",
            directory=target,
            opener=_opener_for(b"", status_code=404),
        )
    assert not is_installed(target)


def test_install_short_circuits_when_already_installed(tmp_path):
    target = tmp_path / "r"
    target.mkdir()
    (target / ".complete").write_text("x", encoding="utf-8")

    def exploding_opener(url):
        raise AssertionError("must not download when already installed")

    done = download_and_install(
        url="u", sha256="", directory=target, opener=exploding_opener
    )
    assert done == target
    sys.path.remove(str(target))


def test_activate_is_idempotent_and_requires_marker(tmp_path):
    target = tmp_path / "r"
    target.mkdir()
    assert activate(target) is False  # no marker -> not activated
    (target / ".complete").write_text("x", encoding="utf-8")
    assert activate(target) is True
    assert activate(target) is True
    assert sys.path.count(str(target)) == 1  # appended exactly once
    sys.path.remove(str(target))


# ------------------------------------------------------------------ models


def test_download_models_fetches_whisper_and_marian():
    fetched: list[str] = []
    statuses: list[str] = []
    download_models(
        "small", "it", "en", status=statuses.append, downloader=fetched.append
    )
    assert fetched == ["Systran/faster-whisper-small", "Helsinki-NLP/opus-mt-it-en"]
    assert len(statuses) == 2


def test_download_models_same_language_skips_translation_model():
    fetched: list[str] = []
    download_models("tiny", "it", "IT", downloader=fetched.append)
    assert fetched == ["Systran/faster-whisper-tiny"]  # captioning-only


def test_download_models_failure_is_readable():
    def broken(repo):
        raise RuntimeError("network down")

    with pytest.raises(LocalRuntimeError):
        download_models("tiny", "it", "en", downloader=broken)


def test_whisper_repo_naming():
    assert whisper_repo("large-v3") == "Systran/faster-whisper-large-v3"


def test_pack_constants_are_consistent():
    # the URL must embed the pack version so a bump cannot desync them
    assert local_runtime.PACK_VERSION in local_runtime.PACK_URL


def test_required_model_repos_pair_and_captioning():
    from app.local_runtime import required_model_repos

    assert required_model_repos("small", "it", "en") == [
        "Systran/faster-whisper-small",
        "Helsinki-NLP/opus-mt-it-en",
    ]
    # captioning-only: no translation model
    assert required_model_repos("tiny", "it", "IT") == ["Systran/faster-whisper-tiny"]


def test_models_cached_uses_checker_over_all_repos():
    from app.local_runtime import models_cached

    seen: list[str] = []

    def checker(repo: str) -> bool:
        seen.append(repo)
        return True

    assert models_cached("small", "es", "it", checker=checker) is True
    assert seen == ["Systran/faster-whisper-small", "Helsinki-NLP/opus-mt-es-it"]
    # one missing -> False
    assert models_cached("small", "es", "it", checker=lambda r: "whisper" in r) is False


def test_progress_tqdm_reports_cumulative_megabytes():
    # large models with only a busy bar look frozen: byte updates must reach
    # the status callback as cumulative MB
    from app.local_runtime import _progress_tqdm

    seen: list[str] = []
    cls = _progress_tqdm(seen.append, "Systran/faster-whisper-large-v3")
    bar = cls(total=100, unit="B")
    bar.update(7_000_000)
    assert seen and "large-v3" in seen[-1] and "7 MB" in seen[-1]
    bar.close()


def test_progress_tqdm_ignores_non_byte_bars():
    from app.local_runtime import _progress_tqdm

    seen: list[str] = []
    cls = _progress_tqdm(seen.append, "repo")
    bar = cls(total=10, unit="it")  # file-count bar, not bytes
    bar.update(3)
    assert seen == []
    bar.close()


# ------------------------------------------------------------------ model removal


def _fake_cache(tmp_path, monkeypatch) -> object:
    cache = tmp_path / "hub"
    cache.mkdir()
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    return cache


def _fake_model(cache, dirname: str, size: int) -> None:
    d = cache / dirname / "snapshots" / "abc"
    d.mkdir(parents=True)
    (d / "model.bin").write_bytes(b"x" * size)


def test_downloaded_models_lists_only_ours_with_sizes(tmp_path, monkeypatch):
    from app.local_runtime import downloaded_models

    cache = _fake_cache(tmp_path, monkeypatch)
    _fake_model(cache, "models--Systran--faster-whisper-large-v3", 3000)
    _fake_model(cache, "models--Helsinki-NLP--opus-mt-it-en", 2000)
    _fake_model(cache, "models--altra-app--modello-estraneo", 500)  # NOT ours

    models = downloaded_models()
    repos = {m.repo for m in models}
    assert repos == {"Systran/faster-whisper-large-v3", "Helsinki-NLP/opus-mt-it-en"}
    assert {m.size_bytes for m in models} == {3000, 2000}


def test_remove_downloaded_models_frees_only_ours(tmp_path, monkeypatch):
    from app.local_runtime import downloaded_models, remove_downloaded_models

    cache = _fake_cache(tmp_path, monkeypatch)
    _fake_model(cache, "models--Systran--faster-whisper-tiny", 1000)
    _fake_model(cache, "models--altra-app--modello-estraneo", 500)

    freed, failed = remove_downloaded_models()
    assert freed == 1000
    assert failed == []
    assert downloaded_models() == []  # ours gone
    assert (cache / "models--altra-app--modello-estraneo").exists()  # untouched


def test_downloaded_models_empty_without_cache(tmp_path, monkeypatch):
    from app.local_runtime import downloaded_models

    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "inesistente"))
    assert downloaded_models() == []


# ------------------------------------------------------------------ device-aware packs


def test_pack_for_selects_by_device():
    from app.local_runtime import PACKS, pack_for

    assert pack_for("cuda").device == "cuda"
    assert pack_for("CUDA").device == "cuda"  # case-insensitive
    for value in ("cpu", "tpu", "", None):
        assert pack_for(value).device == "cpu"
    # every pack's url embeds its version (a bump can't desync them)
    for pack in PACKS.values():
        assert pack.version in pack.url


def test_runtime_dir_differs_per_device(monkeypatch, tmp_path):
    from app.local_runtime import runtime_dir

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert runtime_dir("cpu") != runtime_dir("cuda")
    assert runtime_dir("cpu").name == "py314-cpu-1"
    assert runtime_dir("cuda").name == "py314-cu124-1"


def test_install_cuda_marks_with_cuda_version(tmp_path):
    payload = _zip_bytes({"faster_whisper/__init__.py": "\n"})
    target = tmp_path / "gpu"
    download_and_install(
        device="cuda", sha256="", directory=target, opener=_opener_for(payload)
    )
    assert (target / ".complete").read_text() == "py314-cu124-1"
    sys.path.remove(str(target))


def test_activate_cuda_registers_nvidia_dll_dirs(tmp_path):
    from app.local_runtime import activate

    target = tmp_path / "gpu"
    for sub in ("cublas", "cudnn", "cuda_runtime"):
        (target / "nvidia" / sub / "bin").mkdir(parents=True)
    (target / ".complete").write_text("py314-cu124-1", encoding="utf-8")

    import os

    registered: list[str] = []
    ok = activate(target, device="cuda", dll_registrar=registered.append)
    assert ok is True
    assert len(registered) == 3  # one per nvidia/*/bin
    assert all("bin" in p for p in registered)
    # also prepended to PATH (cuDNN's own loader needs it)
    path_entries = os.environ["PATH"].split(os.pathsep)
    assert sum(1 for p in path_entries if "nvidia" in p and str(target) in p) == 3
    sys.path.remove(str(target))


def test_activate_cpu_does_not_register_dll_dirs(tmp_path):
    from app.local_runtime import activate

    target = tmp_path / "cpu"
    target.mkdir()
    (target / ".complete").write_text("py314-cpu-1", encoding="utf-8")
    registered: list[str] = []
    ok = activate(target, device="cpu", dll_registrar=registered.append)
    assert ok is True
    assert registered == []  # CPU pack: no CUDA dirs
    sys.path.remove(str(target))
