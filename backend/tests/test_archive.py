import io
import zipfile

import pytest

from app.services.archive import ArchiveError, extract_zip


def _zip_with_cp866_name(path, name: str, data: bytes) -> None:
    """Как делает архиватор Windows: имя в CP866, без UTF-8 флага.

    zipfile сам так писать не умеет, поэтому пишем ASCII-заглушку той же длины и подменяем байты.
    """
    raw = name.encode("cp866")
    placeholder = b"x" * len(raw)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(placeholder.decode(), data)
    path.write_bytes(buf.getvalue().replace(placeholder, raw))


def test_cyrillic_cp866_names(tmp_path):
    archive = tmp_path / "docs.zip"
    _zip_with_cp866_name(archive, "Проект контракта.pdf", b"%PDF-1.4 test")
    files = extract_zip(archive, tmp_path / "out", max_files=10, max_unpacked_bytes=10**6)
    assert [f.relative_path for f in files] == ["Проект контракта.pdf"]
    assert files[0].supported and files[0].stored_path.read_bytes() == b"%PDF-1.4 test"


def test_utf8_names_nested_and_junk(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("ТЗ.docx", b"PK..")
    archive = tmp_path / "docs.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Документация/Извещение.pdf", b"%PDF")
        zf.writestr("Документация/приложения.zip", inner.getvalue())
        zf.writestr("__MACOSX/._Извещение.pdf", b"x")
        zf.writestr("~$temp.docx", b"x")
        zf.writestr("readme.exe", b"x")
    files = extract_zip(archive, tmp_path / "out", max_files=10, max_unpacked_bytes=10**6)
    paths = {f.relative_path: f.supported for f in files}
    assert paths == {
        "Документация/Извещение.pdf": True,
        "Документация/приложения.zip/ТЗ.docx": True,
        "readme.exe": False,
    }


def test_zip_slip_is_neutralized(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../../etc/passwd.pdf", b"%PDF")
        zf.writestr("ok.pdf", b"%PDF")
    out = tmp_path / "out"
    files = extract_zip(archive, out, max_files=10, max_unpacked_bytes=10**6)
    assert [f.relative_path for f in files] == ["ok.pdf"]
    assert all(f.stored_path.parent == out for f in files)


def test_limits(tmp_path):
    archive = tmp_path / "big.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a.pdf", b"0" * 5000)
        zf.writestr("b.pdf", b"0" * 5000)
    with pytest.raises(ArchiveError):
        extract_zip(archive, tmp_path / "o1", max_files=10, max_unpacked_bytes=6000)
    with pytest.raises(ArchiveError):
        extract_zip(archive, tmp_path / "o2", max_files=1, max_unpacked_bytes=10**6)


def test_not_a_zip(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(ArchiveError):
        extract_zip(bad, tmp_path / "o", max_files=10, max_unpacked_bytes=10**6)
