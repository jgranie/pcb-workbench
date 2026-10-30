# PCB Workbench

A local prototype for inspecting a PCB photograph, proposing solder joints and tracing possible copper paths. It combines optional WeVisOne segmentation/detection with a deterministic CPU tracing workflow and manual corrections.

> Experimental research software. Generated paths are hypotheses, not electrically verified connections or a netlist.

## Features

- Import PNG images or individual layers from a GIMP XCF file.
- Prepare a board crop and review proposed epoxy removal.
- Propose solder joints by section, then add, move or reject points.
- Trace candidate paths using a CPU multi-source Dijkstra scan, review pin-row exclusions and edit paths manually.
- Save and reopen a workspace, including annotations and settings.

## CPU setup

Requirements: Python 3.12, Node.js 26, and optionally GIMP 3 for XCF import. From the repository root:

```sh
cd app
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
./workshop run --input examples/synthetic.png --output results/example
./workshop serve results/example
```

Open the loopback address printed by the server. See [the original guide](app/docs/GUIDED_RUN.md) and [trace tools](app/docs/TRACES.md) for details (French).

## Optional WeVisOne-VL integration

[WeVisOne-VL](https://github.com/Tencent/WeVisOne-VL) is a vision-language model from Tencent's WeChat Vision team. PCB Workbench uses it locally to **propose a board outline, epoxy removal and solder-joint bounding boxes**. These proposals require review. Copper path detection is a separate CPU-based geometric process.

The repository includes an adapter in `wevisone-vl/`, but **does not include the upstream `wevisone_vl` package, model weights or a ready-to-use model environment**. The adapter targets Apple Silicon using PyTorch MPS and BF16, with pinned 2B and 4B model revisions. It runs offline and does not automatically download a model or fall back to another backend.

To use this experimental integration, prepare a separate Python environment with the upstream package and the matching model assets, then configure these environment variables before starting the app:

- `PCB_WEVISONE_RUNTIME`: absolute path to this repository's `wevisone-vl` directory.
- `PCB_WEVISONE_PYTHON`: absolute path to the Python executable in the prepared model environment.
- `PCB_WEVISONE_MODELS_DIR`: absolute path to the directory containing the prepared model assets.

The adapter checks specific model revisions and preparation receipts (`preparation.json` for 2B and `download.json` for 4B); downloading the upstream weights alone does not create these receipts. **The full setup and receipt-generation procedure is not yet provided or validated on a fresh machine.** See [the upstream project](https://github.com/Tencent/WeVisOne-VL) for its package and model documentation. The CPU-only workflow above does not require WeVisOne.

## Persistence

Workspace JSON stores edits and references to separately stored images and crop masks. Back up the complete result directory rather than the JSON alone. No user board photograph, annotated workspace or model weights are included in this repository.

## Status and rights

Paths, solder detections and board masks need manual review; bright reflections, inscriptions and broad conductive-looking areas can cause false connections. This project has no license declared yet. Third-party dependencies and provenance are described in [THIRD_PARTY.md](app/THIRD_PARTY.md).
