import ffmpeg
import os
import uuid
from typing import Optional, Tuple
from app.settings.config import settings


class FFmpegService:
    def __init__(self):
        self.download_dir = settings.DOWNLOAD_DIR
        os.makedirs(self.download_dir, exist_ok=True)

    def get_video_info(self, file_path: str) -> dict:

        try:
            probe = ffmpeg.probe(file_path)
            video_stream = next(
                (s for s in probe['streams'] if s['codec_type'] == 'video'),
                None
            )
            audio_stream = next(
                (s for s in probe['streams'] if s['codec_type'] == 'audio'),
                None
            )

            return {
                'duration': float(probe['format'].get('duration', 0)),
                'size': int(probe['format'].get('size', 0)),
                'bitrate': int(probe['format'].get('bit_rate', 0)),
                'video': {
                    'codec': video_stream.get('codec_name') if video_stream else None,
                    'width': video_stream.get('width') if video_stream else None,
                    'height': video_stream.get('height') if video_stream else None,
                    'fps': eval(video_stream.get('r_frame_rate', '0/1')) if video_stream else None
                },
                'audio': {
                    'codec': audio_stream.get('codec_name') if audio_stream else None,
                    'sample_rate': audio_stream.get('sample_rate') if audio_stream else None,
                    'channels': audio_stream.get('channels') if audio_stream else None
                }
            }
        except ffmpeg.Error as e:
            raise Exception(f"FFprobe error: {e.stderr.decode() if e.stderr else str(e)}")

    def convert_format(
        self,
        input_path: str,
        output_format: str,
        output_path: Optional[str] = None
    ) -> str:

        if not output_path:
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            output_path = os.path.join(self.download_dir, f"{base_name}.{output_format}")

        try:
            (
                ffmpeg
                .input(input_path)
                .output(output_path, acodec='aac', vcodec='libx264')
                .overwrite_output()
                .run(quiet=True)
            )
            return output_path
        except ffmpeg.Error as e:
            raise Exception(f"Conversion error: {e.stderr.decode() if e.stderr else str(e)}")

    def extract_audio(
        self,
        input_path: str,
        output_format: str = "mp3",
        bitrate: str = "192k"
    ) -> str:

        base_name = os.path.splitext(os.path.basename(input_path))[0]
        output_path = os.path.join(self.download_dir, f"{base_name}.{output_format}")

        try:
            (
                ffmpeg
                .input(input_path)
                .output(output_path, acodec='libmp3lame', audio_bitrate=bitrate, vn=None)
                .overwrite_output()
                .run(quiet=True)
            )
            return output_path
        except ffmpeg.Error as e:
            raise Exception(f"Audio extraction error: {e.stderr.decode() if e.stderr else str(e)}")

    def resize_video(
        self,
        input_path: str,
        width: int,
        height: int,
        output_path: Optional[str] = None
    ) -> str:

        if not output_path:
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            ext = os.path.splitext(input_path)[1]
            output_path = os.path.join(self.download_dir, f"{base_name}_resized{ext}")

        try:
            (
                ffmpeg
                .input(input_path)
                .filter('scale', width, height)
                .output(output_path, acodec='copy')
                .overwrite_output()
                .run(quiet=True)
            )
            return output_path
        except ffmpeg.Error as e:
            raise Exception(f"Resize error: {e.stderr.decode() if e.stderr else str(e)}")

    def trim_video(
        self,
        input_path: str,
        start_time: float,
        end_time: float,
        output_path: Optional[str] = None
    ) -> str:

        if not output_path:
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            ext = os.path.splitext(input_path)[1]
            output_path = os.path.join(self.download_dir, f"{base_name}_trimmed{ext}")

        duration = end_time - start_time

        try:
            (
                ffmpeg
                .input(input_path, ss=start_time, t=duration)
                .output(output_path, acodec='copy', vcodec='copy')
                .overwrite_output()
                .run(quiet=True)
            )
            return output_path
        except ffmpeg.Error as e:
            raise Exception(f"Trim error: {e.stderr.decode() if e.stderr else str(e)}")

    def generate_thumbnail(
        self,
        input_path: str,
        time_offset: float = 1.0,
        output_path: Optional[str] = None
    ) -> str:

        if not output_path:
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            output_path = os.path.join(self.download_dir, f"{base_name}_thumb.jpg")

        try:
            (
                ffmpeg
                .input(input_path, ss=time_offset)
                .filter('scale', 320, -1)
                .output(output_path, vframes=1)
                .overwrite_output()
                .run(quiet=True)
            )
            return output_path
        except ffmpeg.Error as e:
            raise Exception(f"Thumbnail error: {e.stderr.decode() if e.stderr else str(e)}")

    def compress_video(
        self,
        input_path: str,
        crf: int = 28,
        output_path: Optional[str] = None
    ) -> str:

        if not output_path:
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            ext = os.path.splitext(input_path)[1]
            output_path = os.path.join(self.download_dir, f"{base_name}_compressed{ext}")

        try:
            (
                ffmpeg
                .input(input_path)
                .output(output_path, vcodec='libx264', crf=crf, acodec='aac')
                .overwrite_output()
                .run(quiet=True)
            )
            return output_path
        except ffmpeg.Error as e:
            raise Exception(f"Compression error: {e.stderr.decode() if e.stderr else str(e)}")
