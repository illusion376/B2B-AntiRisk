import io
import zipfile

import pytest

from app.services.archive import ArchiveError, extract_archive, extract_zip


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


# --- RAR, 7Z, зашифрованные и вложенные архивы ---

import shutil
import subprocess

needs_rar = pytest.mark.skipif(shutil.which("rar") is None, reason="для создания RAR в тесте нужен rar")


def _encrypt_zip_entry(path, index: int) -> None:
    """Выставляет бит шифрования у записи — как у архива с паролем на один файл."""
    data = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as zf:
        info = zf.infolist()[index]
    data[info.header_offset + 6] |= 1
    central = data.find(b"PK\x01\x02")
    for _ in range(index):
        central = data.find(b"PK\x01\x02", central + 4)
    data[central + 8] |= 1
    path.write_bytes(bytes(data))


def test_encrypted_entry_does_not_reject_archive(tmp_path):
    archive = tmp_path / "docs.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Извещение.pdf", b"%PDF-1.4")
        zf.writestr("Секретное.pdf", b"%PDF-1.4")
    _encrypt_zip_entry(archive, 1)
    files = {f.relative_path: f for f in extract_zip(archive, tmp_path / "o", max_files=10, max_unpacked_bytes=10**6)}
    assert files["Извещение.pdf"].supported
    assert not files["Секретное.pdf"].supported and "паролем" in files["Секретное.pdf"].error


def test_7z_with_cyrillic_names(tmp_path):
    py7zr = pytest.importorskip("py7zr")
    archive = tmp_path / "docs.7z"
    with py7zr.SevenZipFile(archive, "w") as z:
        z.writestr(b"%PDF-1.4 seven", "Документация/Проект контракта.pdf")
        z.writestr(b"x", "__MACOSX/._junk")
    files = extract_archive(archive, tmp_path / "o", max_files=10, max_unpacked_bytes=10**6)
    assert [f.relative_path for f in files] == ["Документация/Проект контракта.pdf"]
    assert files[0].supported and files[0].stored_path.read_bytes() == b"%PDF-1.4 seven"
    assert not any(p.name.startswith(".7z_") for p in (tmp_path / "o").iterdir())  # временная папка убрана


def test_7z_nested_in_zip_and_broken_nested(tmp_path):
    py7zr = pytest.importorskip("py7zr")
    inner = tmp_path / "inner.7z"
    with py7zr.SevenZipFile(inner, "w") as z:
        z.writestr(b"PK..", "ТЗ.docx")
    archive = tmp_path / "docs.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(inner, "Приложения.7z")
        zf.writestr("Битый.rar", b"not a rar")
    files = {f.relative_path: f for f in extract_archive(archive, tmp_path / "o", max_files=10, max_unpacked_bytes=10**6)}
    assert files["Приложения.7z/ТЗ.docx"].supported
    assert not files["Битый.rar"].supported and "повреждён" in files["Битый.rar"].error


def test_nested_archive_limits_still_reject(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.pdf", b"0" * 50_000)
    archive = tmp_path / "docs.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("inner.zip", inner.getvalue())
    with pytest.raises(ArchiveError):
        extract_archive(archive, tmp_path / "o", max_files=10, max_unpacked_bytes=20_000)


@needs_rar
def test_rar_with_cyrillic_and_encrypted_file(tmp_path):
    pytest.importorskip("rarfile")
    if not (shutil.which("unar") or shutil.which("unrar") or shutil.which("bsdtar")):
        pytest.skip("для распаковки RAR нужен unar/unrar/bsdtar")
    src = tmp_path / "src" / "Документация"
    src.mkdir(parents=True)
    (src / "Проект контракта.pdf").write_bytes(b"%PDF-1.4 rar")
    plain = tmp_path / "plain.rar"
    subprocess.run(["rar", "a", "-ep1", "-r", "-inul", str(plain), str(src)], check=True)
    secret = tmp_path / "secret.rar"
    subprocess.run(["rar", "a", "-ep1", "-psecret", "-inul", str(secret), str(src / "Проект контракта.pdf")], check=True)

    files = extract_archive(plain, tmp_path / "o1", max_files=10, max_unpacked_bytes=10**6)
    assert [f.relative_path for f in files] == ["Документация/Проект контракта.pdf"]
    assert files[0].stored_path.read_bytes() == b"%PDF-1.4 rar"

    files = extract_archive(secret, tmp_path / "o2", max_files=10, max_unpacked_bytes=10**6)
    assert len(files) == 1 and not files[0].supported and "паролем" in files[0].error
