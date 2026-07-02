import re
import subprocess
from dataclasses import dataclass

from django.conf import settings

_GEOMETRY_RE = re.compile(r"(\d+)x(\d+)")


class ImageDiffError(Exception):
    """Raised when ImageMagick fails or produces unparseable output."""


@dataclass(frozen=True)
class ImageGeometry:
    width: int
    height: int

    @classmethod
    def from_file(cls, path: str) -> "ImageGeometry":
        try:
            result = subprocess.run(
                ["identify", "-format", "%wx%h", str(path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=settings.IMAGEMAGICK_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise ImageDiffError("ImageMagick timed out") from exc
        if result.returncode != 0:
            raise ImageDiffError(f"identify failed for {path}: {result.stderr.strip()}")
        match = _GEOMETRY_RE.search(result.stdout)
        if not match:
            raise ImageDiffError(f"could not parse identify output: {result.stdout!r}")
        return cls(width=int(match.group(1)), height=int(match.group(2)))
