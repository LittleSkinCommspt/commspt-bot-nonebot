"""Minecraft 皮肤 3D 渲染与后处理工具

调用 SkinRenderMC API 渲染皮肤正反面预览图并添加水印。

主要接口：
- request_skinrendermc: 请求 SkinRenderMC 接口获取正反面 3D 渲染图字节流
- process_image: 裁剪渲染图边缘并添加 Mojangles 字体水印
"""

from io import BytesIO

import httpx
from PIL import Image, ImageDraw, ImageFont

from plugins.commspt_bot.config import ASSETS_DIR, S_


async def request_skinrendermc(skin_url: str | None, cape_url: str | None, name_tag: str | None):
    """向 SkinRenderMC API 请求 3D 皮肤与披风正反面渲染图"""
    p = {
        "skinUrl": skin_url,
        "capeUrl": cape_url,
        "nameTag": name_tag,
    }

    # 删除值为 None 的键值对
    # （SkinRenderMC 只判断键值对是否存在，传递 None 或空值参数会导致远端解析错误）
    for x in [k for k in p if not p[k]]:
        p.pop(x)

    # 建立 HTTP/2 客户端发起 GET 请求，渲染接口耗时通常在 15 秒内
    async with httpx.AsyncClient(http2=True, base_url=S_.api_skinrendermc.endpoint, follow_redirects=True) as client:
        resp = await client.get(
            "/url/image/both",
            params=p,
            timeout=30,  # 通常只需要不到 15 秒
        )
        # if resp.status_code == 200:
        #     image = resp.read()
        #     return image
        # else:
        #     return
        # 校验响应状态码并直接返回图片二进制数据
        resp.raise_for_status()
        return resp.content


def process_image(image_bytes: bytes, text: str) -> bytes:
    """对皮肤渲染图进行后处理：裁剪底部阴影/多余边距并在右下角添加水印"""
    # Open the image from the byte representation
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    # 裁剪底部约 13% 区域以去除渲染图底部的多余空白和阴影
    image = image.crop((0, 0, image.width, int(image.height * 0.87)))

    # Create a draw object to draw on the image
    draw = ImageDraw.Draw(image)

    # Define the font to be used for the watermark
    # 使用静态资源目录下的 Minecraft 风格字体 Mojangles 渲染水印
    font = ImageFont.truetype(str(ASSETS_DIR / "fonts" / "mojangles.ttf"), size=12)

    # Set the margin around the watermark
    margin_x = 20
    margin_y = 10

    # Calculate the width and height of the watermark text
    text_width = font.getmask(text).getbbox()[2]
    text_height = font.getmask(text).getbbox()[3]

    # Calculate the coordinates to place the watermark text
    x = image.width - margin_x - text_width
    y = image.height - margin_y - text_height

    # Draw the watermark text on the image
    draw.text((x, y), text, font=font, fill=(0, 0, 0))

    # Save the modified image as byte representation
    output_bytes = BytesIO()
    image.save(output_bytes, format="PNG")

    # Return the byte representation of the modified image
    return output_bytes.getvalue()
