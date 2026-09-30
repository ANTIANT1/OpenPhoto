from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Crop(StrictModel):
    x: float = Field(0, ge=0, le=1)
    y: float = Field(0, ge=0, le=1)
    w: float = Field(1, gt=0, le=1)
    h: float = Field(1, gt=0, le=1)

    @model_validator(mode="after")
    def contained(self):
        if self.x + self.w > 1.000001 or self.y + self.h > 1.000001:
            raise ValueError("Crop must lie inside the oriented image")
        return self


class Stroke(StrictModel):
    points: list[tuple[float, float]] = Field(min_length=1, max_length=10000)
    radius: float = Field(0.025, gt=0, le=0.3)

    @model_validator(mode="after")
    def normalized(self):
        if any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in self.points):
            raise ValueError("Brush coordinates must be normalized")
        return self


class HealSpot(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    radius: float = Field(0.008, gt=0, le=0.1)
    source_x: float | None = Field(None, ge=0, le=1)
    source_y: float | None = Field(None, ge=0, le=1)


class Develop(StrictModel):
    exposure: float = Field(0, ge=-5, le=5)
    temperature: int | None = Field(None, ge=2000, le=12000)
    tint: float = Field(1, ge=0.5, le=2)
    recover_highlights: bool = True
    denoise: float = Field(0, ge=0, le=1)
    lens_correction: bool = True


class Color(StrictModel):
    exposure: float = Field(0, ge=-2, le=2)
    contrast: float = Field(0, ge=-0.5, le=0.5)
    saturation: float = Field(1, ge=0, le=2)
    warmth: float = Field(0, ge=-0.3, le=0.3)
    tint: float = Field(0, ge=-0.2, le=0.2)
    shadows: float = Field(0, ge=-0.3, le=0.3)
    highlights: float = Field(0, ge=-0.3, le=0.3)
    black_point: float = Field(0, ge=-0.1, le=0.1)
    shadow_hue: float = Field(0, ge=-0.15, le=0.15)
    highlight_hue: float = Field(0, ge=-0.15, le=0.15)
    strength: float = Field(1, ge=0, le=1)
    protect_skin: bool = True


class Retouch(StrictModel):
    strength: float = Field(0, ge=0, le=0.6)
    color_evenness: float = Field(0, ge=0, le=0.6)
    protected: list[Stroke] = Field(default_factory=list, max_length=500)
    healing: list[HealSpot] = Field(default_factory=list, max_length=500)
    disabled_faces: list[int] = Field(default_factory=list)
    body_strength: float = Field(0, ge=0, le=0.6)
    body_color_evenness: float = Field(0, ge=0, le=0.6)


class EditRecipe(StrictModel):
    version: Literal[1, 2] = 2
    develop: Develop = Field(default_factory=Develop)
    color: Color = Field(default_factory=Color)
    retouch: Retouch = Field(default_factory=Retouch)
    crop: Crop = Field(default_factory=Crop)
    rotation: float = Field(0, ge=-15, le=15)
    lock_crop: bool = False
    engine: Literal["rawtherapee-5.13"] = "rawtherapee-5.13"
    working_space: Literal["linear-prophoto"] = "linear-prophoto"
    runtime: dict[str, str] = Field(default_factory=dict)


class ImportRequest(StrictModel):
    paths: list[str] = Field(min_length=1, max_length=1000)
    shoot_name: str = Field("Новая съёмка", min_length=1, max_length=200)
    recursive: bool = True


class JobRequest(StrictModel):
    photo_ids: list[str] = Field(default_factory=list, max_length=10000)
    shoot_id: str | None = None
    profile_id: str | None = None
    strength: float = Field(0.6, ge=0, le=1)


class WorkflowRequest(JobRequest):
    selection: Literal["all", "suggested"] = "suggested"
    retouch_strength: float = Field(0.15, ge=0, le=0.4)
    export_directory: str | None = None


class DecisionRequest(StrictModel):
    photo_ids: list[str] = Field(min_length=1, max_length=10000)
    action: Literal["keep", "reject", "clear", "rating", "compare", "accept_crop", "remove", "restore_removed"]
    value: int | str | None = None
    other_id: str | None = None


class RecipeRequest(StrictModel):
    recipe: EditRecipe
    expected_revision: int = Field(ge=0)
    source: Literal["manual", "crop_accept", "style_accept", "geometry_migration"] = "manual"


class BatchRecipeRequest(StrictModel):
    harmonize_exposure: bool = False
    photo_ids: list[str] = Field(min_length=1, max_length=10000)
    sections: list[Literal["develop", "color", "retouch", "crop"]]
    recipe: EditRecipe
    preserve_manual: bool = True
    source_photo_id: str | None = None
    scope: Literal["selection", "group", "shoot"] = "selection"


class ExportRequest(JobRequest):
    directory: str = Field(min_length=1)
    format: Literal["jpeg", "tiff"] = "jpeg"
    profile: Literal["srgb", "prophoto"] = "srgb"
    long_edge: int = Field(0, ge=0, le=20000)
    quality: int = Field(95, ge=1, le=100)
    sharpen: float = Field(0.2, ge=0, le=1)
    xmp: bool = True
    recipes: bool = True
    include_proposed: bool = False


class ProfileRequest(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    paths: list[str] = Field(default_factory=list, max_length=1000)
    roles: list[Literal["color", "composition", "mood"]] = Field(
        default_factory=lambda: ["color", "composition", "mood"]
    )


class GroupRequest(StrictModel):
    photo_ids: list[str] = Field(min_length=1, max_length=10000)
    action: Literal["merge", "split"]


class RecipeFileRequest(StrictModel):
    photo_id: str
    path: str
    expected_revision: int = Field(ge=0)


class ReferenceRolesRequest(StrictModel):
    roles: list[Literal["color", "composition", "mood"]] = Field(min_length=1, max_length=3)


class SettingsPatch(StrictModel):
    models_directory: str | None = None
    cpu_threads: int | None = Field(None, ge=1, le=4)
    worker_idle_seconds: int | None = Field(None, ge=10, le=120)
    rawtherapee: str | None = None
    exiftool: str | None = None
    cache_gb: float | None = Field(None, ge=1, le=500)
    auto_crop: bool | None = None
    crop_min_area: float | None = Field(None, ge=0.5, le=1)
    crop_validated: bool | None = None
    keeper_fraction: float | None = Field(None, ge=0.01, le=1)
