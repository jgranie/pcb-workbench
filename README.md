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

## Optional WeVisOne integration

The bundled adapter targets the separately installed WeVisOne-VL Transformers runtime on Apple Silicon with MPS and BF16. Weights, runtime environment and original upstream code are not included. Set `PCB_WEVISONE_RUNTIME` to the absolute path of this repository's `wevisone-vl` folder, `PCB_WEVISONE_PYTHON` to the separately prepared model environment's Python, and `PCB_WEVISONE_MODELS_DIR` to the folder containing verified model assets. The adapter also requires the `wevisone_vl` Python package and pinned model preparation receipts. The full portable setup is not yet documented or validated on a fresh machine. The CPU pipeline is independent of this optional integration.

## Persistence

Workspace JSON stores edits and references to separately stored images and crop masks. Back up the complete result directory rather than the JSON alone. No user board photograph, annotated workspace or model weights are included in this repository.

## Status and rights

Paths, solder detections and board masks need manual review; bright reflections, inscriptions and broad conductive-looking areas can cause false connections. This project has no license declared yet. Third-party dependencies and provenance are described in [THIRD_PARTY.md](app/THIRD_PARTY.md).
