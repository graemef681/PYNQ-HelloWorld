# remote_ui.py
# Two modes selectable on construction:
#   SimpleCaptureUI(mode="file")   -> File upload only
#   SimpleCaptureUI(mode="webcam") -> Webcam snapshot only (persistent camera)
#
# Overlay auto-loads if bitstream provided.
# "Run FPGA Resizer" allocates/frees buffers each run.
# Images displayed at relative real size using shared scale between input/output.
# On overlay load failure, the original PYNQ error is forwarded (re-raised)
# and also rendered in the UI with the full traceback.

from dataclasses import dataclass
from typing import Optional
from IPython.display import display, clear_output
import ipywidgets as widgets
import datetime, io, atexit, traceback
from html import escape as html_escape
from PIL import Image, ImageOps
import traitlets
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from pynq import allocate, Overlay

# Clean figures
matplotlib.rcParams["toolbar"] = "none"

try:
    import cv2
except Exception:
    cv2 = None


@dataclass
class UIState:
    last_filename: Optional[str] = None


def _extract_single_upload(uploader: widgets.FileUpload):
    v = uploader.value
    if not v:
        return None, None
    if isinstance(v, (tuple, list)):
        item = v[0]
        if isinstance(item, dict):
            return item.get("name"), item.get("content")
        return getattr(item, "name", None), getattr(item, "content", None)
    if isinstance(v, dict):
        (name, payload), = v.items()
        return name, payload.get("content")
    return None, None


def _cv2_bgr_to_pil(frame_bgr):
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


class SimpleCaptureUI(traitlets.HasTraits):
    """Single-mode UI for File upload or Webcam snapshot.
    mode="file"   → file-only UI
    mode="webcam" → webcam-only UI (persistent camera)
    bitstream     → overlay auto-load at startup
    """

    current_pil = traitlets.Instance(Image.Image, allow_none=True)

    def __init__(self, width=1280, height=720, bitstream: Optional[str] = None, mode="file"):
        super().__init__()
        mode = (mode or "file").strip().lower()
        assert mode in ("file", "webcam"), 'mode must be "file" or "webcam"'
        self._mode = mode
        self.S = UIState()
        self._out_pil: Optional[Image.Image] = None
        self._cap: Optional[cv2.VideoCapture] = None
        self._cam_width = width
        self._cam_height = height

        # Overlay handles
        self._overlay: Optional[Overlay] = None
        self._dma = None
        self._resizer = None

        # Widgets
        self.status = widgets.HTML(value="<i>Starting…</i>")
        self.run_fpga = widgets.Button(description="Run FPGA Resizer", button_style="primary")
        self.uploader = widgets.FileUpload(accept="image/*", multiple=False, description="Upload")
        self.snapshot = widgets.Button(description="Snapshot")

        # Layout
        card_layout = widgets.Layout(
            width="48%",
            border="1px solid #e5e7eb",
            border_radius="12px",
            padding="10px",
            box_shadow="0 1px 8px rgba(0,0,0,0.05)",
            background_color="#fff",
        )
        title_style = "margin:0 0 8px 0;font-weight:600;font-size:14px;color:#111827"
        cap_style = "margin:6px 0 0 0;color:#4b5563;font-size:12px;text-align:center"

        self.input_title = widgets.HTML(f"<p style='{title_style}'>Input</p>")
        self.input_canvas = widgets.Output(layout=widgets.Layout(min_height="320px"))
        self.input_caption = widgets.HTML(f"<p style='{cap_style}'><i>—</i></p>")
        self.input_card = widgets.VBox(
            [self.input_title, self.input_canvas, self.input_caption], layout=card_layout
        )

        self.output_title = widgets.HTML(f"<p style='{title_style}'>Output</p>")
        self.output_canvas = widgets.Output(layout=widgets.Layout(min_height="320px"))
        self.output_caption = widgets.HTML(f"<p style='{cap_style}'><i>Output Image (empty)</i></p>")
        self.output_card = widgets.VBox(
            [self.output_title, self.output_canvas, self.output_caption], layout=card_layout
        )

        self.row = widgets.HBox(
            [self.input_card, self.output_card],
            layout=widgets.Layout(justify_content="space-between", width="100%", gap="16px"),
        )

        # Events
        self.run_fpga.on_click(self._on_run_fpga)
        self.uploader.observe(self._on_upload, names="value")
        self.snapshot.on_click(self._on_snapshot)

        # Load overlay
        if bitstream:
            self._load_overlay(bitstream)
        else:
            self.status.value = "<i>Ready. (No overlay loaded yet)</i>"

        atexit.register(self._cleanup)

    # ============================================================
    # Public
    def render(self):
        if self._mode == "file":
            display(widgets.VBox([self.uploader, self.status, self.run_fpga]))
        else:
            self._open_camera()
            display(widgets.VBox([self.snapshot, self.status, self.run_fpga]))
        display(self.row)
        self._render_both()

    # ============================================================
    def _load_overlay(self, bitstream: str):
        """Load overlay and initialize fixed IP handles. If this fails,
        forward PYNQ's error by re-raising, and also render a full traceback in the UI.
        """
        try:
            self._overlay = Overlay(bitstream)
            self._dma = self._overlay.axi_dma_0
            self._resizer = self._overlay.resize_accel_0
            self.status.value = f"<b>Overlay loaded:</b> {bitstream}"
        except Exception as e:
            tb = traceback.format_exc()
            # Show detailed traceback in the UI
            self.status.value = (
                "<div style='color:#b91c1c'><b>Overlay load failed.</b>"
                f"<pre style='white-space:pre-wrap'>{html_escape(tb)}</pre></div>"
            )
            # Forward the original error so users get the real PYNQ exception too
            raise

    # ============================================================
    # Camera
    def _open_camera(self):
        if self._mode != "webcam":
            return
        if cv2 is None:
            self.status.value = "<span style='color:#b91c1c'>OpenCV not available.</span>"
            return
        if self._cap and self._cap.isOpened():
            return
        self._cap = cv2.VideoCapture(0)
        if not self._cap.isOpened():
            self.status.value = "<span style='color:#b91c1c'>Cannot open camera.</span>"
            return
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._cam_width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._cam_height)
        self.status.value = "<i>Camera ready.</i>"

    def _close_camera(self):
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    # ============================================================
    # File / Snapshot
    def _on_upload(self, change):
        if self._mode != "file":
            return
        name, content = _extract_single_upload(self.uploader)
        if not (name and content):
            self.S.last_filename = None
            self.current_pil = None
            self.status.value = "<i>No image selected</i>"
            self._out_pil = None
            self._render_both()
            return
        try:
            img = Image.open(io.BytesIO(content))
            img = ImageOps.exif_transpose(img).convert("RGB")
            self.S.last_filename = name
            self.current_pil = img
            self._out_pil = None
            self.status.value = f"<b>Uploaded:</b> {name}"
            self._render_both()
        except Exception as e:
            self.status.value = f"<span style='color:#b91c1c'>Upload failed: {e}</span>"

    def _on_snapshot(self, _btn):
        if self._mode != "webcam":
            return
        if cv2 is None or not (self._cap and self._cap.isOpened()):
            self.status.value = "<span style='color:#b91c1c'>Camera not ready.</span>"
            return
        ok, frame_bgr = self._cap.read()
        if not ok or frame_bgr is None:
            self.status.value = "<span style='color:#b91c1c'>Capture failed.</span>"
            return
        img = _cv2_bgr_to_pil(frame_bgr)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"webcam_{ts}.png"
        self.S.last_filename = name
        self.current_pil = img
        self._out_pil = None
        self.status.value = f"<b>Snapshot:</b> {name}"
        self._render_both()

    # ============================================================
    # FPGA Resize
    def _on_run_fpga(self, _btn):
        if self.current_pil is None:
            self.status.value = "<span style='color:#b45309'>No input image.</span>"
            return
        if not (self._dma and self._resizer):
            self.status.value = "<span style='color:#b45309'>FPGA not ready.</span>"
            return

        img = self.current_pil.convert("RGB")
        ow, oh = img.size
        rf = 2  # half-size
        nw, nh = max(1, ow // rf), max(1, oh // rf)

        in_buf = out_buf = None
        try:
            in_buf = allocate(shape=(oh, ow, 3), dtype=np.uint8, cacheable=1)
            out_buf = allocate(shape=(nh, nw, 3), dtype=np.uint8, cacheable=1)
            in_buf[:] = np.asarray(img, dtype=np.uint8)

            r = self._resizer
            r.register_map.src_rows = oh
            r.register_map.src_cols = ow
            r.register_map.dst_rows = nh
            r.register_map.dst_cols = nw

            d = self._dma
            d.sendchannel.transfer(in_buf)
            d.recvchannel.transfer(out_buf)
            r.write(0x00, 0x81)
            d.sendchannel.wait()
            d.recvchannel.wait()

            self._out_pil = Image.fromarray(np.array(out_buf))
            self.status.value = f"<b>FPGA resize:</b> {ow}×{oh} → {nw}×{nh}"
            self._render_both()
        except Exception as e:
            tb = traceback.format_exc()
            self.status.value = (
                "<div style='color:#b91c1c'><b>FPGA resize failed.</b>"
                f"<pre style='white-space:pre-wrap'>{html_escape(tb)}</pre></div>"
            )
            # Forward the error too, in case the caller wants to see it in the notebook output
            raise
        finally:
            try: del in_buf
            except Exception: pass
            try: del out_buf
            except Exception: pass

    # ============================================================
    # Shared scaling renderer
    def _shared_scale(self, img_in, img_out, target_px=620, dpi=100.0):
        w_in, h_in = img_in.size if img_in else (0, 0)
        w_out, h_out = img_out.size if img_out else (0, 0)
        max_w = max(w_in, w_out, 1)
        s = target_px / max_w
        return s, dpi

    def _render_one(self, out_box, caption_widget, img, label_html, s, dpi):
        clear_output(wait=True)
        if img is None:
            display(widgets.HTML("<div style='text-align:center;color:#6b7280'><i>(empty)</i></div>"))
            caption_widget.value = (
                "<p style='margin:6px 0 0 0;color:#6b7280;font-size:12px;text-align:center'><i>—</i></p>"
            )
            return
        w, h = img.size
        fig_w = (w * s) / dpi
        fig_h = (h * s) / dpi
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        ax.imshow(img)
        ax.set_xticks([]); ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
        display(fig)
        plt.close(fig)
        caption_widget.value = (
            f"<p style='margin:6px 0 0 0;color:#4b5563;font-size:12px;text-align:center'>"
            f"{label_html}<br>{w}×{h}</p>"
        )

    def _render_both(self):
        img_in, img_out = self.current_pil, self._out_pil
        s, dpi = self._shared_scale(img_in, img_out, target_px=620, dpi=100.0)
        with self.input_canvas:
            self._render_one(self.input_canvas, self.input_caption, img_in,
                             f"<b>{self.S.last_filename or '(unnamed)'}</b>", s, dpi)
        with self.output_canvas:
            label = "<b>Resized</b>" if img_out else "<i>Output Image (empty)</i>"
            self._render_one(self.output_canvas, self.output_caption, img_out, label, s, dpi)

    # ============================================================
    def _cleanup(self):
        self._close_camera()
