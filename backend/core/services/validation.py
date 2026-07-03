"""POST /tests parameter validation.

Sanitizes everything before it reaches the shell. The legacy app interpolated
fuzz_level / highlight_colour / crop_area straight into the ImageMagick
command — the rebuild rejects malformed values at the API boundary
(decisions.md, "Bugs / risks fixed by the rebuild").
"""

import re

from rest_framework.exceptions import ValidationError

# Anchored — `.fullmatch()`, not `.match()` — so payloads like "30%; rm -rf /"
# cannot slip past a prefix check.
_FUZZ_RE = re.compile(r"\d+(\.\d+)?%")
_COLOUR_RE = re.compile(r"[0-9a-fA-F]{6}")
_CROP_RE = re.compile(r"\d+x\d+\+\d+\+\d+")


def validate_test_params(data):
    """Return a sanitized dict; raise DRF ValidationError → 400 on bad input."""
    errors: dict[str, str] = {}

    run_id = data.get("run_id")
    name = data.get("name")
    browser = data.get("browser")
    size = data.get("size")

    if not run_id:
        errors["run_id"] = "is required"
    if not name:
        errors["name"] = "is required"
    if not browser:
        errors["browser"] = "is required"
    if not size:
        errors["size"] = "is required"

    fuzz = data.get("fuzz_level") or "30%"
    colour = data.get("highlight_colour") or "ff0000"
    crop = data.get("crop_area") or ""

    if not isinstance(fuzz, str):
        errors["fuzz_level"] = "must be a string"
    elif not _FUZZ_RE.fullmatch(fuzz):
        errors["fuzz_level"] = r"must match /^\d+(\.\d+)?%$/"
    elif float(fuzz[:-1]) > 100:
        errors["fuzz_level"] = "must be between 0 and 100%"

    if not isinstance(colour, str):
        errors["highlight_colour"] = "must be a string"
    elif not _COLOUR_RE.fullmatch(colour):
        errors["highlight_colour"] = "must be a 6-char hex string, no leading #"

    if not isinstance(crop, str):
        errors["crop_area"] = "must be a string"
    elif crop and not _CROP_RE.fullmatch(crop):
        errors["crop_area"] = r"must match /^\d+x\d+\+\d+\+\d+$/"

    if errors:
        raise ValidationError(errors)

    return {
        "run_id": run_id,
        "name": name,
        "browser": browser,
        "size": size,
        "source_url": data.get("source_url") or "",
        "fuzz_level": fuzz,
        "highlight_colour": colour,
        "crop_area": crop,
    }
