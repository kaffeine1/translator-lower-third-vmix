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
