"""皮肤图片后处理测试；隔离 NoneBot 父插件加载及外部服务配置。"""

import ast
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont


@pytest.fixture
def process_image(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "plugins/commspt_bot/utils/skinrendermcapi.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "process_image")
    namespace = {
        "BytesIO": BytesIO,
        "Image": Image,
        "ImageDraw": ImageDraw,
        "ImageFont": ImageFont,
        "ASSETS_DIR": path.parent,
    }
    font = ImageFont.load_default()
    monkeypatch.setattr(ImageFont, "truetype", lambda *args, **kwargs: font)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102 -- 仅执行仓库内的目标函数
    return namespace["process_image"]


@pytest.mark.parametrize("alpha", [0, 128, 255])
def test_process_image_preserves_alpha(process_image, alpha):
    image = Image.new("RGBA", (400, 200), (12, 34, 56, alpha))
    source = BytesIO()
    image.save(source, format="PNG")

    result = Image.open(BytesIO(process_image(source.getvalue(), "test")))

    assert result.format == "PNG"
    assert result.mode == "RGBA"
    assert result.size == (400, 174)
    assert result.getpixel((0, 0)) == (12, 34, 56, alpha)


def test_process_image_accepts_rgb(process_image):
    source = BytesIO()
    Image.new("RGB", (400, 200), (12, 34, 56)).save(source, format="PNG")

    result = Image.open(BytesIO(process_image(source.getvalue(), "test")))

    assert result.getpixel((0, 0)) == (12, 34, 56, 255)
