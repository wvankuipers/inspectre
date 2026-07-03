from dataclasses import dataclass

from .image_geometry import ImageGeometry


@dataclass(frozen=True)
class Canvas:
    width: int
    height: int
    dimensions_differ: bool

    @classmethod
    def from_geometries(
        cls,
        baseline: ImageGeometry,
        screenshot: ImageGeometry,
    ) -> "Canvas":
        return cls(
            width=max(baseline.width, screenshot.width),
            height=max(baseline.height, screenshot.height),
            dimensions_differ=(baseline.width != screenshot.width or baseline.height != screenshot.height),
        )
