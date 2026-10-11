from io import BytesIO
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

PROFILE_PICTURE_SIZE = 512
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
# Well below Pillow's own bomb threshold: a tiny, highly compressible PNG can
# still claim enough pixels to eat hundreds of MB once decoded.
MAX_PIXELS = 50_000_000


def process_profile_picture(file):
    """Re-encode an uploaded image into a small, metadata-free JPEG.

    /media is public, so this is what keeps GPS/camera EXIF off the internet,
    stops non-images (e.g. an .html "picture") from being served from our own
    origin, and keeps 36px avatars from costing several MB each. The random
    name also stops URLs being guessable.
    """
    if file.size > MAX_UPLOAD_BYTES:
        raise ValidationError("Image is too large.")
    try:
        file.seek(0)
        with Image.open(file) as im:
            if im.width * im.height > MAX_PIXELS:
                raise ValidationError("Image is too large.")
            icc_profile = im.info.get("icc_profile")
            # For JPEGs this decodes at a reduced scale (still >= the target),
            # so large camera photos never get fully decompressed.
            im.draft("RGB", (PROFILE_PICTURE_SIZE, PROFILE_PICTURE_SIZE))
            im = ImageOps.exif_transpose(im)
            im.thumbnail((PROFILE_PICTURE_SIZE, PROFILE_PICTURE_SIZE), Image.Resampling.LANCZOS)
            im = _flatten(im)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as e:
        raise ValidationError("Not a valid image.") from e

    buf = BytesIO()
    # No exif= here: Pillow only writes metadata it's explicitly handed. The ICC
    # profile is kept so wide-gamut phone photos don't shift colour.
    im.save(buf, "JPEG", quality=85, optimize=True, icc_profile=icc_profile)
    return ContentFile(buf.getvalue(), name=f"{uuid4().hex}.jpg")


def _flatten(im):
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        background = Image.new("RGB", im.size, "white")
        background.paste(im, mask=im.getchannel("A"))
        return background
    return im.convert("RGB")
