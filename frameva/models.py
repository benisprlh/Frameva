"""Validated public request schemas, shared by the browser and MCP bridge."""
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class SessionInput(Input):
    token: str = Field(min_length=1, max_length=512)

class ProjectInput(Input):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=4000)

class ProjectPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)

class ShotInput(Input):
    name: str = Field(default='Untitled shot', min_length=1, max_length=120)
    prompt: str = Field(default='', max_length=8000)
    negative_prompt: str = Field(default='', max_length=4000)
    provider: Literal['preview','comfyui','recording'] = 'preview'
    workflow_id: str | None = None
    reference_asset_id: str | None = None
    video_asset_id: str | None = None
    trim_start: float = Field(default=0, ge=0, le=3600)
    playback_rate: float = Field(default=1, ge=0.25, le=4)
    focus_x: float = Field(default=0.5, ge=0, le=1)
    focus_y: float = Field(default=0.5, ge=0, le=1)
    zoom: float = Field(default=1, ge=1, le=2.5)
    keep_audio: bool = True
    camera: Literal['static','dolly_in','dolly_out','pan_left','pan_right','orbit'] = 'dolly_in'
    style: Literal['cinematic','natural','noir','dream'] = 'cinematic'
    width: int = Field(default=1280, ge=64, le=2560)
    height: int = Field(default=720, ge=64, le=2560)
    duration: float = Field(default=3, ge=1, le=120)
    fps: int = Field(default=24, ge=8, le=30)
    seed: int = Field(default=42, ge=0, le=2**32-1)
    headline: str = Field(default='', max_length=120)
    caption: str = Field(default='', max_length=300)
    brand_color: str = Field(default='#b8ff65', pattern=r'^#[0-9a-fA-F]{6}$')
    layout: Literal['showcase','title','detail'] = 'showcase'

    @field_validator('width','height')
    @classmethod
    def dimensions(cls, value):
        if value % 2:
            raise ValueError('Video dimensions must be even.')
        return value

    @model_validator(mode='after')
    def provider_limits(self):
        if self.provider != 'recording' and self.duration>30:
            raise ValueError('Product motion and ComfyUI shots support at most 30 seconds; recording shots support 120 seconds.')
        if self.provider == 'recording' and not self.video_asset_id:
            raise ValueError('A recording shot requires a video_asset_id.')
        return self

class ShotPatch(Input):
    # Validation of merged complete data is performed with ShotInput.
    name: str | None = None
    prompt: str | None = None
    negative_prompt: str | None = None
    provider: str | None = None
    workflow_id: str | None = None
    reference_asset_id: str | None = None
    video_asset_id: str | None = None
    trim_start: float | None = None
    playback_rate: float | None = None
    focus_x: float | None = None
    focus_y: float | None = None
    zoom: float | None = None
    keep_audio: bool | None = None
    camera: str | None = None
    style: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    fps: int | None = None
    seed: int | None = None
    headline: str | None = None
    caption: str | None = None
    brand_color: str | None = None
    layout: str | None = None

class OrderInput(Input):
    shot_ids: list[str] = Field(max_length=200)

class JobInput(Input):
    shot_id: str = Field(min_length=1, max_length=64)

class ExportInput(Input):
    shot_ids: list[str] | None = Field(default=None, max_length=200)
    width: int = Field(default=1280, ge=64, le=2560)
    height: int = Field(default=720, ge=64, le=2560)
    fps: int = Field(default=24, ge=8, le=30)
    audio_asset_id: str | None = None
    transition: Literal['cut','crossfade'] = 'crossfade'
    transition_duration: float = Field(default=0.35, ge=0, le=0.8)

    @field_validator('width','height')
    @classmethod
    def dimensions(cls, value):
        if value % 2: raise ValueError('Video dimensions must be even.')
        return value

class RendererInput(Input):
    comfy_url: str = Field(min_length=1, max_length=2048)

class Binding(Input):
    node_id: str = Field(min_length=1, max_length=100)
    input: str = Field(min_length=1, max_length=100)

class WorkflowInput(Input):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=2000)
    graph: dict[str, Any]
    bindings: dict[str, Binding]
    frame_multiple: Literal[1,4,8] = 4

class LaunchPlanInput(Input):
    replace_existing: bool = False
    aspect: Literal['landscape','portrait','square'] = 'landscape'

class SourceAnalysisInput(Input):
    analysis: dict[str, Any]
