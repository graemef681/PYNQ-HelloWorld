## PYNQ.remote-Helloworld

# PYNQ Remote Resizer Demo

A lightweight demo showcasing **PYNQ.remote** capabilities using host-side hardware integration.  
This example provides a graphical interface (via `ipywidgets`) that connects a host webcam or uploaded image to an FPGA-based image resizer running remotely on a PYNQ board (e.g., ZCU104).

---

## Overview

This repository provides a single installable Python package, `remote_ui`, which offers a ready-to-use UI built with Jupyter widgets.

You can use it to:
- Demonstrate the **PYNQ.remote** workflow between a host PC and FPGA target.  
- Capture webcam snapshots from the host and process them via FPGA acceleration.
- Observe **PYNQ.remote** behavior through a live, interactive demo.

---

## ⚙️ Installation

### 1️. Prerequisites

You’ll need the following installed **on the host system**:

- Python **≥3.8**
- JupyterLab or Jupyter Notebook
- PYNQ ≥ 3.1
- Xilinx board `PYNQ.remote` image
- OpenCV (for webcam functionality)

---

### 2️. Python Dependencies

Install all required dependencies:

```bash
pip install -r requirements.txt
```

### 3. Installing PYNQ v3.1
Currently this repository is compatible with `pynq` package v3.1. 

First clone the PYNQ repository from here [v3.1.1](https://github.com/Xilinx/PYNQ/tree/image_v3.1)

```sh
git clone -b image_v3.1 https://github.com/Xilinx/PYNQ.git
```

Then install PYNQ v3.1 onto your host system using pip: 

```sh
cd PYNQ/
pip install .
```

## Running the demo

Clone this repository:

```sh
git clone https://github.com/<yourname>/pynq-remote-resizer.git
cd pynq_helloworld/notebooks
```

Then ensure that your board is running a PYNQ.remote image, is turned on, and you know the IP of the board.

Also ensure that a USB webcam is plugged into your PC and accessible by Jupyter Notebooks and your Python installation. 

Open "resizer_remote_cam.ipynb" on your host PC using Jupyter Notebooks:

Populate the PYNQ_REMOTE_DEVICES environment variable with the IP of your board.
```py
os.environ['PYNQ_REMOTE_DEVICES'] = "xilinx-zcu104-20241"  # or "<BOARD_IP>"
```

Also, make sure you have the relevant bitstream for your board. This is the same bitstream used for the [PYNQ-Helloworld demo](https://github.com/Xilinx/PYNQ-HelloWorld)

## How It Works

The host system continuously maintains a connection to the webcam (via OpenCV).

When you click Snapshot, a frame is captured and stored as a PIL.Image object.

Clicking Run FPGA Resizer:

1. Allocates input/output buffers via pynq.allocate()

2. Writes image data to the FPGA through the DMA send channel

3. Triggers the resize_accel IP using MMIO

4. Waits for DMA completion

5. Displays the resized image next to the original

6. Both images are scaled proportionally so the output’s size ratio reflects the actual resizer output.


## Supported Boards

Currently this repository is supporting:

* **Zynq-7000 boards**: Pynq-Z2
* **Zynq Ultrascale boards**: ZCU104, RFSoC4x2

## License

**PYNQ** License : [BSD 3-Clause License](https://github.com/Xilinx/PYNQ/blob/master/LICENSE)
