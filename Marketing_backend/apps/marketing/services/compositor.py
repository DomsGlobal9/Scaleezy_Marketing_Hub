"""
apps/marketing/services/compositor.py

Applies brand add-ons (Brand Logo at top-right, Contact Phone Number & Website in Footer frame)
onto AI-generated posters using high-quality PIL compositing.
"""
import io
import logging
import os
import re
from typing import Any, Dict, Optional

# Ensure SSL log proxy on Windows does not interfere with urllib3 requests
os.environ.pop('SSLKEYLOGFILE', None)

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)


class BrandAddonCompositor:
    """
    Composites real brand artwork (Logo) and contact details (Phone number, Website, CTA)
    onto generated poster imagery.
    """

    @classmethod
    def composite_poster(
        cls,
        image_bytes: bytes,
        *,
        logo_url: str = '',
        include_logo: bool = True,
        phone_number: str = '',
        include_phone: bool = True,
        website: str = '',
        cta: str = '',
        brand_name: str = '',
        palette: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        if not image_bytes:
            return image_bytes

        # If neither logo nor phone is requested, return untouched image
        if not (include_logo and logo_url) and not (include_phone and phone_number):
            return image_bytes

        try:
            base_image = Image.open(io.BytesIO(image_bytes)).convert('RGBA')
            width, height = base_image.size

            # 1. Overlay Brand Logo at Top Right
            if include_logo and logo_url:
                base_image = cls._overlay_logo(base_image, logo_url, width, height)

            # 2. Overlay Footer Section Frame (Phone, Website, CTA)
            if include_phone and phone_number:
                base_image = cls._overlay_footer(
                    base_image,
                    phone_number=phone_number,
                    website=website,
                    cta=cta,
                    brand_name=brand_name,
                    width=width,
                    height=height,
                    palette=palette or {},
                )

            # Convert back to RGB JPEG bytes
            output = io.BytesIO()
            rgb_image = base_image.convert('RGB')
            rgb_image.save(output, format='JPEG', quality=95, optimize=True)
            return output.getvalue()

        except Exception as exc:
            logger.exception("BrandAddonCompositor error, returning original image: %s", exc)
            return image_bytes

    @classmethod
    def _make_white_transparent(cls, img: Image.Image, threshold: int = 240) -> Image.Image:
        """If a brand logo is on a solid white background, converts white to transparent."""
        img = img.convert('RGBA')
        datas = list(img.getdata())

        # If image already has transparent pixels, keep as is
        has_alpha = any(item[3] < 240 for item in datas)
        if has_alpha:
            return img

        new_data = []
        for item in datas:
            r, g, b, a = item
            if r >= threshold and g >= threshold and b >= threshold:
                diff = min(r, g, b) - threshold
                alpha = max(0, int(255 - (diff / (255 - threshold + 1e-5)) * 255))
                new_data.append((r, g, b, alpha))
            else:
                new_data.append(item)

        img.putdata(new_data)
        return img

    @classmethod
    def _overlay_logo(cls, base: Image.Image, logo_url: str, width: int, height: int) -> Image.Image:
        try:
            os.environ.pop('SSLKEYLOGFILE', None)
            resp = requests.get(logo_url, timeout=12)
            resp.raise_for_status()
            logo_raw = Image.open(io.BytesIO(resp.content)).convert('RGBA')

            logo = cls._make_white_transparent(logo_raw)
            bbox = logo.getbbox()
            if bbox:
                logo = logo.crop(bbox)

            # Max dimensions: ~20% width, ~6.5% height
            max_w = max(1, int(width * 0.20))
            max_h = max(1, int(height * 0.065))
            ratio = min(max_w / max(1, logo.width), max_h / max(1, logo.height))
            new_size = (max(1, int(logo.width * ratio)), max(1, int(logo.height * ratio)))
            logo_resized = logo.resize(new_size, Image.Resampling.LANCZOS)

            pad_x = 16
            pad_y = 9
            badge_w = logo_resized.width + pad_x * 2
            badge_h = logo_resized.height + pad_y * 2

            pos_x = max(0, width - badge_w - 36)
            pos_y = 36

            # Apply subtle backdrop blur under the badge
            patch_x1 = max(0, pos_x - 4)
            patch_y1 = max(0, pos_y - 4)
            patch_x2 = min(width, pos_x + badge_w + 4)
            patch_y2 = min(height, pos_y + badge_h + 4)
            patch = base.crop((patch_x1, patch_y1, patch_x2, patch_y2))
            blurred_patch = patch.filter(ImageFilter.GaussianBlur(8))
            base.paste(blurred_patch, (patch_x1, patch_y1))

            # Elegant frosted capsule badge
            badge = Image.new('RGBA', (badge_w, badge_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(badge)
            draw.rounded_rectangle(
                [(0, 0), (badge_w, badge_h)],
                radius=14,
                fill=(255, 255, 255, 230),
                outline=(255, 255, 255, 170),
                width=1,
            )
            # Paste logo inside badge
            badge.alpha_composite(logo_resized, (pad_x, pad_y))

            base.alpha_composite(badge, (pos_x, pos_y))

        except Exception as exc:
            logger.warning("Could not overlay brand logo: %s", exc)

        return base

    @classmethod
    def _overlay_footer(
        cls,
        base: Image.Image,
        phone_number: str,
        website: str,
        cta: str,
        brand_name: str,
        width: int,
        height: int,
        palette: Dict[str, Any],
    ) -> Image.Image:
        try:
            clean_website = re.sub(r'^https?://', '', website or '').rstrip('/')
            
            clean_phone = str(phone_number).strip()
            if not clean_phone.startswith('+') and len(clean_phone) == 10:
                clean_phone = f"+91 {clean_phone[:5]} {clean_phone[5:]}"

            margin_x = 36
            margin_bottom = 32
            card_w = width - (margin_x * 2)
            card_h = max(82, int(height * 0.068))
            pos_x = margin_x
            pos_y = height - card_h - margin_bottom

            # Apply backdrop blur for frosted glass effect
            f_x1 = max(0, pos_x - 4)
            f_y1 = max(0, pos_y - 4)
            f_x2 = min(width, pos_x + card_w + 4)
            f_y2 = min(height, pos_y + card_h + 4)
            f_patch = base.crop((f_x1, f_y1, f_x2, f_y2))
            f_blurred = f_patch.filter(ImageFilter.GaussianBlur(10))
            base.paste(f_blurred, (f_x1, f_y1))

            card = Image.new('RGBA', (card_w, card_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(card)
            
            draw.rounded_rectangle(
                [(0, 0), (card_w, card_h)],
                radius=16,
                fill=(12, 16, 26, 225),
                outline=(255, 255, 255, 38),
                width=1,
            )

            font_title = None
            font_sub = None
            for font_name in ('arial.ttf', 'seguiemj.ttf', 'segoeui.ttf', 'DejaVuSans.ttf'):
                try:
                    font_title = ImageFont.truetype(font_name, size=max(14, int(card_h * 0.30)))
                    font_sub = ImageFont.truetype(font_name, size=max(11, int(card_h * 0.22)))
                    break
                except Exception:
                    continue

            if font_title is None:
                font_title = ImageFont.load_default()
                font_sub = ImageFont.load_default()

            phone_label = f"Call: {clean_phone}"
            phone_y = int(card_h * 0.20)
            draw.text((28, phone_y), phone_label, fill=(255, 255, 255, 255), font=font_title)

            sub_text = cta or "Book Consultation" or brand_name
            draw.text((28, phone_y + int(card_h * 0.38)), sub_text, fill=(165, 185, 215, 235), font=font_sub)

            if clean_website:
                draw.text(
                    (card_w - 28, int(card_h * 0.34)),
                    clean_website,
                    fill=(195, 245, 140, 255),
                    font=font_title,
                    anchor="ra",
                )

            base.alpha_composite(card, (pos_x, pos_y))

        except Exception as exc:
            logger.warning("Could not overlay footer frame: %s", exc)

        return base
