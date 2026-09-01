import json
import base64
import requests
import tempfile
import os
import time
from django.conf import settings
from google import genai
from google.genai import types


class GeminiNotConfigured(RuntimeError):
    """No Gemini credential is available, so nothing can be generated.

    Raised rather than returning placeholder copy. The router treats it as a
    provider failure, which is the truth: a generation that never reached a
    provider did not happen, and must not be recorded as though it did.
    """


class GeminiGeneratorService:
    """
    Two-step pipeline:
    1. Text model (gemini-2.5-flash) → generates post title, description, hashtags,
       AND a detailed image generation prompt for the poster (analyzing the reference image if provided).
    2. Image model (gemini-3.1-flash-image) → takes that prompt (and optionally the reference image) and generates the poster.
    """

    TEXT_MODEL = 'gemini-2.5-flash'
    IMAGE_MODEL = 'gemini-3.1-flash-image'

    @classmethod
    def _resolve_api_key(cls, api_key: str = '') -> str:
        """The workspace's own key, else the server's, else nothing doing.

        A tenant that saved its own key in Settings must be able to use it -
        that credential reached the database and then went nowhere, because
        every call here read the server setting directly.
        """
        key = (api_key or '').strip() or getattr(settings, 'GEMINI_API_KEY', '')
        if not key:
            raise GeminiNotConfigured(
                "No Gemini API key is configured for this workspace or for the "
                "server, so Gemini cannot be called."
            )
        return key

    #: A provider call that never returns holds a gunicorn worker until the
    #: server kills it. The client is built with no timeout by default, so
    #: one hung socket used to cost a whole worker — and with threads it
    #: would cost every request sharing it.
    HTTP_TIMEOUT_MS = 60_000
    #: How long to wait for Gemini to finish processing an uploaded video.
    VIDEO_PROCESSING_TIMEOUT_SECONDS = 180

    @classmethod
    def _get_client(cls, api_key: str = ''):
        return genai.Client(
            api_key=cls._resolve_api_key(api_key),
            http_options={'timeout': cls.HTTP_TIMEOUT_MS},
        )
        
    @staticmethod
    def _parse_base64_image(b64_string: str):
        """Extracts mime_type and bytes from a data URI string."""
        if not b64_string or not b64_string.startswith("data:"):
            return None, None
        try:
            # data:image/jpeg;base64,....
            header, encoded = b64_string.split(",", 1)
            mime_type = header.split(";")[0].replace("data:", "")
            image_bytes = base64.b64decode(encoded)
            return mime_type, image_bytes
        except Exception as e:
            print(f"Error parsing base64 image: {e}")
            return None, None

    @classmethod
    def analyze_reference_image(cls, b64_img: str, api_key: str = '') -> dict:
        """
        Extracts recommended form fields (Campaign, Product, Occasion, Tone) 
        from a reference image.
        """
        if not b64_img:
            return {}
            
        client = cls._get_client(api_key)
        mime_type, img_bytes = cls._parse_base64_image(b64_img)
        
        if not mime_type or not img_bytes:
            return {}

        prompt = """Analyze this image and extract marketing details.
Return ONLY a valid JSON object with these exact keys:
{
  "campaignName": "A catchy 2-4 word campaign name",
  "product": "The main product or collection shown",
  "occasion": "The inferred occasion or season (e.g., Summer, Diwali, Casual)",
  "brandTone": "The visual tone (e.g., Premium, Festive, Minimalist)"
}"""
        
        contents = [
            prompt,
            types.Part.from_bytes(data=img_bytes, mime_type=mime_type)
        ]
        
        response = client.models.generate_content(
            model=cls.TEXT_MODEL,
            contents=contents,
        )
        
        raw_text = response.text.strip()
        if raw_text.startswith('```'):
            raw_text = raw_text.split('\n', 1)[1] if '\n' in raw_text else raw_text[3:]
        if raw_text.endswith('```'):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()
        if raw_text.startswith('json'):
            raw_text = raw_text[4:].strip()

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            return {}

    @classmethod
    def generate_captions_only(cls, b64_img: str, api_key: str = '') -> dict:
        """
        Takes a final poster image and writes engaging captions and hashtags for it.
        """
        if not b64_img:
            return {}
            
        client = cls._get_client(api_key)
        mime_type, img_bytes = cls._parse_base64_image(b64_img)
        
        if not mime_type or not img_bytes:
            return {}

        prompt = """You are an expert social media manager.
I am providing a finalized marketing poster.
Please write a highly engaging social media caption for this poster.

Return ONLY a valid JSON object with these exact keys:
{
  "postTitle": "A short, catchy title (max 10 words)",
  "postDescription": "An engaging social media caption with emojis (2-4 sentences)",
  "postHashtags": "5-8 relevant hashtags separated by spaces"
}"""
        
        contents = [
            prompt,
            types.Part.from_bytes(data=img_bytes, mime_type=mime_type)
        ]
        
        response = client.models.generate_content(
            model=cls.TEXT_MODEL,
            contents=contents,
        )
        
        raw_text = response.text.strip()
        if raw_text.startswith('```'):
            raw_text = raw_text.split('\n', 1)[1] if '\n' in raw_text else raw_text[3:]
        if raw_text.endswith('```'):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()
        if raw_text.startswith('json'):
            raw_text = raw_text[4:].strip()

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            return {}

    @classmethod
    def analyze_video(cls, asset_id: str, api_key: str = '') -> dict:
        """
        Downloads the video asset, uploads it to Gemini, and generates captions.
        """
        from apps.marketing.models import MarketingAsset
        
        try:
            asset = MarketingAsset.objects.get(id=asset_id)
        except MarketingAsset.DoesNotExist:
            raise Exception("Video asset not found.")
            
        if not asset.file_url:
            raise Exception("Video has no file URL.")

        client = cls._get_client(api_key)
        
        # Download the video locally to upload to Gemini File API
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
        os.close(tmp_fd)
        
        uploaded_file = None
        try:
            # 1. Download
            response = requests.get(asset.file_url, stream=True, timeout=30)
            response.raise_for_status()
            with open(tmp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    
            # 2. Upload to Gemini
            uploaded_file = client.files.upload(file=tmp_path)
            
            # 3. Wait for processing, but not forever. This loop had no
            # deadline and no attempt cap: a video Gemini never finished
            # processing pinned the request until gunicorn SIGKILLed the
            # worker, taking every other request sharing it down too.
            deadline = time.monotonic() + cls.VIDEO_PROCESSING_TIMEOUT_SECONDS
            while uploaded_file.state.name == "PROCESSING":
                if time.monotonic() > deadline:
                    raise Exception(
                        "Gemini did not finish processing this video within "
                        f"{cls.VIDEO_PROCESSING_TIMEOUT_SECONDS}s. It was not "
                        "analysed, and nothing was saved."
                    )
                time.sleep(2)
                uploaded_file = client.files.get(name=uploaded_file.name)
                
            if uploaded_file.state.name == "FAILED":
                raise Exception("Video processing failed in Gemini.")
                
            # 4. Generate Content
            prompt = """You are an expert social media manager.
I am providing a marketing video.
Please analyze the video content and write a highly engaging social media caption for it.

Return ONLY a valid JSON object with these exact keys:
{
  "campaignName": "A catchy 2-4 word campaign name describing the video",
  "postTitle": "A short, catchy title (max 10 words)",
  "postDescription": "An engaging social media caption with emojis (2-4 sentences)",
  "postHashtags": "5-8 relevant hashtags separated by spaces"
}"""
            
            gen_response = client.models.generate_content(
                model=cls.TEXT_MODEL,
                contents=[prompt, uploaded_file],
            )
            
            raw_text = gen_response.text.strip()
            if raw_text.startswith('```'):
                raw_text = raw_text.split('\n', 1)[1] if '\n' in raw_text else raw_text[3:]
            if raw_text.endswith('```'):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()
            if raw_text.startswith('json'):
                raw_text = raw_text[4:].strip()

            try:
                return json.loads(raw_text)
            except json.JSONDecodeError:
                return {}
                
        finally:
            # Clean up Gemini File
            if uploaded_file:
                try:
                    client.files.delete(name=uploaded_file.name)
                except Exception as e:
                    print(f"Failed to delete Gemini file: {e}")
            # Clean up local temp file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    @staticmethod
    def _rules_block(rules: list) -> str:
        """
        Renders the brand's learned rules as prompt instructions.

        Empty when nothing has been learned yet, so the prompt is byte-for-byte
        what it was before Phase 6 until a reviewer has actually rejected the
        same thing twice.
        """
        lines = [str(r).strip() for r in (rules or []) if str(r).strip()]
        if not lines:
            return ""
        body = "\n".join(f"- {line}" for line in lines)
        return (
            "\n\nLEARNED BRAND RULES — these come from this brand's own reviewers "
            "rejecting past work for the same reason more than once. Treat them as "
            "hard constraints and do not repeat those mistakes:\n"
            f"{body}\n"
        )

    @staticmethod
    def _variety_block(recent) -> str:
        """
        Renders the workspace's recent headlines as a do-not-repeat constraint.

        Two similar briefs used to come back with the same title and concept —
        nothing told the model what it already said. Empty when the workspace
        has no history, so a first generation's prompt is unchanged.
        """
        lines = [str(h).strip() for h in (recent or []) if str(h).strip()][:6]
        if not lines:
            return ""
        listed = "\n".join(f'- "{line}"' for line in lines)
        return (
            "\n\nALREADY PUBLISHED — this brand's recent posts used these "
            "headlines. Your postTitle must NOT reuse, rephrase or echo any of "
            "them, and your imagePrompt must choose a visibly different setting "
            "and concept from what they suggest:\n"
            f"{listed}\n"
        )

    @classmethod
    def generate_text_and_image_prompt(cls, request_data: dict, api_key: str = '') -> dict:
        """
        Step 1: Use the text model to generate captions + image prompt.
        If a reference_image_base64 is provided, it analyzes the image too.
        """
        client = cls._get_client(api_key)

        campaign = request_data.get('campaign_name', '')
        product = request_data.get('product', '')
        audience = request_data.get('target_audience', '')
        location = request_data.get('location', '')
        occasion = request_data.get('occasion', '')
        offer = request_data.get('offer', '')
        brand_tone = request_data.get('brand_tone', '')
        b64_img = request_data.get('reference_image_base64', '')
        # Rules the training engine has learned from repeated reviewer
        # rejections, merged with the Context Gateway's brand-context lines -
        # the queued and revision paths send `brand_context` and not
        # `brand_rules`, and a constraint that only reaches one path is not a
        # constraint. Deduplicated because the synchronous path sends the same
        # lines under both keys. Placed near the end of the prompt, where the
        # model weights instructions most heavily.
        brand_rules = list(dict.fromkeys([
            *(request_data.get('brand_rules') or []),
            *(request_data.get('brand_context') or []),
        ]))
        variety_block = cls._variety_block(request_data.get('recent_headlines'))
        creative_direction = request_data.get('creative_direction') or {}
        creative_lines = creative_direction.get('instructions') or []
        creative_block = ''
        if creative_lines:
            creative_block = (
                "\n\nUSER-SELECTED CREATIVE DIRECTION - these references were "
                "chosen for this generation. USE means draw from only the named "
                "qualities; AVOID means do not reproduce that quality. Never copy "
                "protected artwork, logos or unverified claims:\n"
                + "\n".join(f"- {str(line).strip()}" for line in creative_lines if str(line).strip())
                + "\n"
            )

        prompt_text = f"""You are an elite, award-winning creative director and social media marketing expert.

Given the following campaign details, generate TWO things:

A) Social media post content (title, description, hashtags)
B) A highly detailed image generation prompt that will be sent to an AI image model to create a breathtaking, professional marketing poster.

Campaign Details:
- Campaign/Promotion: {campaign}
- Product/Collection: {product}
- Target Audience: {audience}
- Location: {location}
- Occasion/Festival: {occasion}
- Offer: {offer}
- Brand Tone: {brand_tone}

For the `imagePrompt`, you MUST be wildly creative and imaginative. Do NOT just place text on a plain background. Re-imagine the product in a visually stunning, high-end editorial or cinematic setting. Be extremely detailed about:
- **Visual Style & Medium**: (e.g., 8k resolution, photorealistic fashion editorial, 3D surrealism, Vogue magazine cover, cinematic lighting).
- **The Setting/Background**: Place the product in a dynamic, immersive environment (e.g., a glowing enchanted forest, a high-end minimalist marble studio, a neon-lit futuristic street). 
- **Lighting & Atmosphere**: (e.g., dramatic chiaroscuro, soft golden hour sunlight, moody rim lighting).
- **Color Palette**: Highly curated colors that perfectly match the "{brand_tone}" tone.
- **Mood & Emotion**: (e.g., luxurious and mysterious, vibrant and energetic).
- Make it suitable for Instagram (1080x1350 portrait).

CRITICAL — NO TEXT IN THE IMAGE: the `imagePrompt` must describe a photograph/visual with absolutely no text, lettering, numbers, captions, watermarks or logos rendered anywhere in it. All headlines, offers and typography are composed onto the image later by a separate layout engine; text baked into the image gets cropped and fights the real typography. The `imagePrompt` itself must end with the sentence: "No text, no lettering, no words, no logos, no watermarks anywhere in the image."

{cls._rules_block(brand_rules)}
{variety_block}
{creative_block}
Respond ONLY with a valid JSON object (no markdown, no code fences, no extra text):
{{
  "postTitle": "A catchy, short title (max 10 words)",
  "postDescription": "An engaging social media caption (2-4 sentences with emojis)",
  "postHashtags": "5-8 relevant hashtags separated by spaces",
  "imagePrompt": "A highly creative, detailed image generation prompt (at least 5-6 sentences describing a breathtaking, transformative campaign poster)"
}}"""

        contents = [prompt_text]
        
        # If the user uploaded a reference image, attach it for Multimodal Vision analysis!
        mime_type, img_bytes = cls._parse_base64_image(b64_img)
        if mime_type and img_bytes:
            contents.append(
                types.Part.from_bytes(data=img_bytes, mime_type=mime_type)
            )
            # Add an extra instruction for multimodal processing
            contents[0] += "\n\nIMPORTANT: I have attached a reference image of the product. DO NOT just recreate this image exactly. Your `imagePrompt` MUST radically transform the setting, lighting, and mood. Take the product shown in the reference image and re-imagine it placed within a stunning, professional, high-budget creative campaign environment as described above."

        response = client.models.generate_content(
            model=cls.TEXT_MODEL,
            contents=contents,
        )

        raw_text = response.text.strip()
        if raw_text.startswith('```'):
            raw_text = raw_text.split('\n', 1)[1] if '\n' in raw_text else raw_text[3:]
        if raw_text.endswith('```'):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()
        if raw_text.startswith('json'):
            raw_text = raw_text[4:].strip()

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed = {
                "postTitle": f"{campaign} — {occasion}",
                "postDescription": raw_text[:300],
                "postHashtags": f"#{occasion.replace(' ', '')} #{product.replace(' ', '')}",
                "imagePrompt": (
                    f"Professional marketing visual for {campaign}, {product}, "
                    f"{occasion}, {brand_tone} tone, Instagram portrait format "
                    "1080x1350. No text, no lettering, no words, no logos, no "
                    "watermarks anywhere in the image."
                )
            }

        return parsed

    @classmethod
    def generate_poster_image(cls, image_prompt: str, reference_image_base64: str = "",
                              api_key: str = '') -> str:
        """
        Step 2: Send the AI-generated image prompt to the image model.
        Also send the original reference image if provided.
        """
        client = cls._get_client(api_key)
        
        # We ONLY pass the text prompt to the image model.
        # The reference image was already analyzed in Step 1 to create this highly detailed prompt.
        # Passing it here again restricts the AI to just editing the original image instead of generating a brand new creative one.
        #
        # The no-text suffix is appended here as well as demanded of Step 1:
        # the composition engine owns every word on the poster, and an image
        # model that renders its own headline produces the half-cropped double
        # text reviewers called "unfinished".
        contents = [
            image_prompt.rstrip()
            + "\n\nStrict requirement: no text, no lettering, no words, no "
            "numbers, no logos, no watermarks anywhere in the image."
        ]

        response = client.models.generate_content(
            model=cls.IMAGE_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE']
            )
        )

        # Extract the image from the response
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                mime_type = part.inline_data.mime_type
                image_bytes = part.inline_data.data
                b64_str = base64.b64encode(image_bytes).decode('utf-8')
                return f"data:{mime_type};base64,{b64_str}"

        return ""

    @classmethod
    def _mock_content(cls, request_data: dict) -> dict:
        """Placeholder copy, for local work without a key. Never reachable
        unless GEMINI_MOCK_MODE was deliberately switched on."""
        campaign = request_data.get('campaign_name', 'Mock Campaign')
        return {
            "postTitle": f"{campaign} Announcement",
            "postDescription": f"Exciting news! We are launching {campaign}. Stay tuned!",
            "postHashtags": "#Launch #ExcitingNews",
            "posterImageUrl": request_data.get('reference_image_base64', ''),
            "imagePrompt": "",
            "generated_text": f"Generated content for {campaign}",
            "metadata": {"mocked": True}
        }

    @classmethod
    def generate_marketing_content(cls, request_data: dict, api_key: str = '') -> dict:
        # Checked before the credential, not as a fallback for the lack of one:
        # mock mode is a deliberate choice, and tying it to "no key" is exactly
        # how placeholder copy reached production as a real ContentItem.
        if getattr(settings, 'GEMINI_MOCK_MODE', False):
            return cls._mock_content(request_data)

        # Raises GeminiNotConfigured when neither the workspace nor the server
        # has a key, so the router records a failed attempt and nothing is
        # persisted.
        api_key = cls._resolve_api_key(api_key)

        # Step 1: Generate text content + image prompt
        text_result = cls.generate_text_and_image_prompt(request_data, api_key=api_key)
        image_prompt = text_result.get("imagePrompt", "")

        # Step 2: Generate poster image from the AI-crafted prompt
        poster_url = ""
        try:
            if image_prompt:
                poster_url = cls.generate_poster_image(
                    image_prompt=image_prompt,
                    reference_image_base64=request_data.get('reference_image_base64', ''),
                    api_key=api_key,
                )
        except Exception as e:
            print(f"[Gemini] Step 2 failed: {e}")
            import traceback
            traceback.print_exc()

        return {
            "postTitle": text_result.get("postTitle", ""),
            "postDescription": text_result.get("postDescription", ""),
            "postHashtags": text_result.get("postHashtags", ""),
            "posterImageUrl": poster_url,
            "imagePrompt": image_prompt,
            "generated_text": text_result.get("postDescription", ""),
            "metadata": {
                "mocked": False,
                "text_model": cls.TEXT_MODEL,
                "image_model": cls.IMAGE_MODEL,
                "imagePrompt": image_prompt,
            }
        }
