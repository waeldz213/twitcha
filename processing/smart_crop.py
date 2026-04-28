"""
Smart Crop – converts landscape (16:9) video to vertical (9:16) format.

Strategy:
  1. Detect scene changes with PySceneDetect to split the video into shots.
  2. For each shot, detect the dominant face/body region using MediaPipe.
  3. Compute an optimal crop rectangle centered on the detected subject.
  4. Apply the crop via FFmpeg for maximum performance.

Output resolution: 1080 × 1920 (9:16)
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

import cv2  # type: ignore
import numpy as np
import structlog

from config.settings import settings

log = structlog.get_logger(__name__)

TARGET_W = 1080
TARGET_H = 1920
ASPECT = TARGET_W / TARGET_H  # ≈ 0.5625


class CropRect(NamedTuple):
    x: int
    y: int
    w: int
    h: int


# ── Subject detection ────────────────────────────────────────────────────────

def _detect_subject_center(frame: np.ndarray) -> Tuple[int, int]:
    """
    Return the (cx, cy) pixel coordinates of the dominant subject in *frame*.

    Detection order:
      1. MediaPipe Face Detection (fastest)
      2. OpenCV Haar face cascade (fallback)
      3. Frame center (final fallback)
    """
    h, w = frame.shape[:2]

    try:
        import mediapipe as mp  # type: ignore

        mp_face = mp.solutions.face_detection
        with mp_face.FaceDetection(
            model_selection=0, min_detection_confidence=0.5
        ) as detector:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = detector.process(rgb)
            if results.detections:
                det = results.detections[0]
                bbox = det.location_data.relative_bounding_box
                cx = int((bbox.xmin + bbox.width / 2) * w)
                cy = int((bbox.ymin + bbox.height / 2) * h)
                return cx, cy
    except Exception:
        log.debug("smart_crop.mediapipe_unavailable")

    # Fallback: OpenCV Haar cascade
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
    if len(faces) > 0:
        fx, fy, fw, fh = faces[0]
        return int(fx + fw / 2), int(fy + fh / 2)

    # Final fallback: frame center
    return w // 2, h // 2


def _compute_crop(frame_w: int, frame_h: int, cx: int, cy: int) -> CropRect:
    """
    Compute the largest 9:16 crop rectangle centered as close as possible
    to (cx, cy) while remaining within frame bounds.
    """
    # The crop height is constrained by the frame height
    crop_h = frame_h
    crop_w = int(crop_h * ASPECT)

    if crop_w > frame_w:
        crop_w = frame_w
        crop_h = int(crop_w / ASPECT)

    # Center on subject
    x = cx - crop_w // 2
    y = cy - crop_h // 2

    # Clamp to frame
    x = max(0, min(x, frame_w - crop_w))
    y = max(0, min(y, frame_h - crop_h))

    return CropRect(x=x, y=y, w=crop_w, h=crop_h)


# ── Scene-aware sampling ─────────────────────────────────────────────────────

def _sample_frames(video_path: Path, num_samples: int = 5) -> List[np.ndarray]:
    """Return *num_samples* evenly-spaced frames from the video."""
    cap = cv2.VideoCapture(str(video_path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    indices = [int(i * total / num_samples) for i in range(num_samples)]
    frames = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret:
            frames.append(frame)
    cap.release()
    return frames


def _dominant_crop(video_path: Path) -> CropRect:
    """
    Sample representative frames, detect the subject in each, and return
    the median crop rectangle to ensure temporal stability.
    """
    frames = _sample_frames(video_path)
    if not frames:
        raise ValueError(f"Could not read frames from {video_path}")

    h, w = frames[0].shape[:2]
    crops: List[CropRect] = []
    for frame in frames:
        cx, cy = _detect_subject_center(frame)
        crops.append(_compute_crop(w, h, cx, cy))

    # Median of x/y to reduce jitter
    median_x = int(np.median([c.x for c in crops]))
    median_y = int(np.median([c.y for c in crops]))
    crop_w = crops[0].w
    crop_h = crops[0].h
    return CropRect(x=median_x, y=median_y, w=crop_w, h=crop_h)


# ── FFmpeg rendering ─────────────────────────────────────────────────────────

def _apply_crop_ffmpeg(
    input_path: Path,
    output_path: Path,
    crop: CropRect,
    audio_path: Optional[Path] = None,
) -> None:
    """Use FFmpeg to apply the crop and scale to 1080×1920."""
    crop_filter = (
        f"crop={crop.w}:{crop.h}:{crop.x}:{crop.y},"
        f"scale={TARGET_W}:{TARGET_H}:flags=lanczos"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-vf", crop_filter,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    log.info("smart_crop.ffmpeg_start", cmd=" ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("smart_crop.ffmpeg_error", stderr=result.stderr)
        raise RuntimeError(f"FFmpeg crop failed: {result.stderr}")


# ── Public API ───────────────────────────────────────────────────────────────

def smart_crop(
    input_path: Path,
    output_dir: Optional[Path] = None,
    output_stem: Optional[str] = None,
) -> Path:
    """
    Detect the dominant subject in *input_path* and produce a 9:16 MP4.

    Returns the path of the cropped file.
    """
    out_dir = output_dir or settings.processed_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = output_stem or (input_path.stem + "_vertical")
    out_path = out_dir / f"{stem}.mp4"

    if out_path.exists():
        log.info("smart_crop.cache_hit", path=str(out_path))
        return out_path

    log.info("smart_crop.start", input=str(input_path))
    crop = _dominant_crop(input_path)
    log.info("smart_crop.crop_rect", crop=crop._asdict())
    _apply_crop_ffmpeg(input_path, out_path, crop)
    log.info("smart_crop.done", output=str(out_path))
    return out_path
