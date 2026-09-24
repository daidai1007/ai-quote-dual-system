from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    ROOT / "packaging" / "AIQuoteDualSystem_installer.spec",
    ROOT / "packaging" / "build_review_client.ps1",
    ROOT / "packaging" / "build_installer.ps1",
    ROOT / "tests" / "verify_review_package.py",
)


def test_client_executable_name_is_v0_everywhere():
    for path in FILES:
        source = path.read_text(encoding="utf-8-sig")
        assert "AIQuoteDualSystem_layout_v0" in source, path
        assert "AIQuoteDualSystem_layout_v6" not in source, path
