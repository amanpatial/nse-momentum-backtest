"""Tests the checksum-verified price download (ingest.download_prices_csv) offline, via file:// URLs.

Run: python -m pytest tests/   or   python tests/test_download.py
"""
import hashlib
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # import the repo-root modules
import ingest  # noqa: E402

CONTENT = b"Date,Ticker,Open,High,Low,Close,Volume\n2024-01-01,AAA,1,1,1,1,100\n"
GOOD = hashlib.sha256(CONTENT).hexdigest()


def make_source(tmp: pathlib.Path) -> str:
    """Write a small 'remote' CSV and return its file:// URL."""
    src = tmp / "remote.csv"
    src.write_bytes(CONTENT)
    return src.as_uri()


def test_download_verifies_checksum_and_saves():
    """A matching checksum saves the file and leaves no .part file behind."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        dest = tmp / "data" / "prices.csv"
        ingest.download_prices_csv(dest, url=make_source(tmp), sha256=GOOD)
        assert dest.read_bytes() == CONTENT
        assert not dest.with_name(dest.name + ".part").exists()
    finally:
        shutil.rmtree(tmp)


def test_checksum_mismatch_raises_and_keeps_nothing():
    """A changed/corrupt source raises and leaves neither the file nor a .part behind."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        dest = tmp / "prices.csv"
        try:
            ingest.download_prices_csv(dest, url=make_source(tmp), sha256="0" * 64)
            raise AssertionError("expected a checksum error")
        except RuntimeError as e:
            assert "checksum mismatch" in str(e)
        assert not dest.exists() and not dest.with_name(dest.name + ".part").exists()
    finally:
        shutil.rmtree(tmp)


def test_existing_verified_file_is_not_downloaded_again():
    """A present file with the right checksum is kept (the bogus URL is never fetched)."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        dest = tmp / "prices.csv"
        dest.write_bytes(CONTENT)
        ingest.download_prices_csv(dest, url=(tmp / "does-not-exist.csv").as_uri(), sha256=GOOD)
        assert dest.read_bytes() == CONTENT
    finally:
        shutil.rmtree(tmp)


def test_existing_corrupt_file_is_refused_unless_forced():
    """A present file with the wrong checksum raises; force=True replaces it with a verified copy."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        dest = tmp / "prices.csv"
        dest.write_bytes(b"corrupt")
        url = make_source(tmp)
        try:
            ingest.download_prices_csv(dest, url=url, sha256=GOOD)
            raise AssertionError("expected an error for the corrupt existing file")
        except RuntimeError as e:
            assert "does not match" in str(e)
        ingest.download_prices_csv(dest, url=url, sha256=GOOD, force=True)
        assert dest.read_bytes() == CONTENT
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
