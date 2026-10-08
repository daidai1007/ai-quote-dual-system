from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
service = (ROOT / "api" / "attachment_service.mjs").read_text(encoding="utf-8")
client = (ROOT / "desktop_client" / "attachment_v2_client.py").read_text(encoding="utf-8")
layout = (ROOT / "desktop_client" / "layout_refresh.py").read_text(encoding="utf-8")

for source in (service, client, layout):
    assert "attachment_images" not in source
    assert "data_base64" not in source
assert "QTableWidget(0, 6, parent)" in layout
assert '"一级分类", "名称", "尺寸 / 规格", "数量", "快速金额", "公式金额",' in layout
print("attachment image query, response, parsing and cache removed")
