# Third-Party Notices

Traduttore Live is released under the MIT License. This file summarizes the
main third-party software used by the project so source and binary
distributions keep the licensing picture explicit.

This is a practical notice file, not legal advice. When producing a public
binary release, keep this file and the project `LICENSE` next to the packaged
application.

## Runtime dependencies

| Component | Purpose | License |
|---|---|---|
| PySide6 / Qt for Python | Desktop GUI toolkit | LGPL-3.0-only, GPL-3.0-only, or commercial Qt license |
| Qt | GUI framework used through PySide6 | LGPL-3.0-only, GPL-3.0-only, or commercial Qt license |
| sounddevice | Audio input bindings | MIT |
| PortAudio | Cross-platform audio I/O library used by sounddevice | MIT-style PortAudio license |
| NumPy | Numeric processing | BSD-3-Clause |
| httpx | HTTP client | BSD-3-Clause |
| PyYAML | YAML configuration parsing | MIT |
| keyring | Secure credential storage integration | MIT |
| websockets | WebSocket client support | BSD-3-Clause |

## Optional provider dependencies

These packages are only required when the matching optional providers are
installed or bundled.

| Component | Purpose | License |
|---|---|---|
| azure-cognitiveservices-speech | Azure Speech provider SDK | Microsoft Software License Terms |
| google-cloud-speech | Google Cloud Speech provider SDK | Apache-2.0 |
| faster-whisper | Local speech recognition provider | MIT |
| CTranslate2 | Inference backend used by faster-whisper | MIT |
| transformers | Local MarianMT translation provider | Apache-2.0 |
| torch | Machine learning runtime used by local providers | BSD-style PyTorch license |

Local speech and translation models may have their own license terms. Check the
specific model selected by the operator before redistributing model files.

## Build and packaging tools

| Component | Purpose | License |
|---|---|---|
| PyInstaller | Windows application packaging | GPL-2.0-or-later with PyInstaller bootloader exception |
| Inno Setup | Windows installer builder | Inno Setup License |
| pytest | Test runner | MIT |
| Ruff | Linter | MIT |

## PySide6 / Qt LGPL note

The application code remains under the MIT License. PySide6 and Qt are separate
third-party components. Binary distributions that bundle PySide6/Qt libraries
must comply with the applicable Qt for Python / Qt license terms, including the
LGPL requirements when using the LGPL option.

In practical terms, release builds should:

- include this notice file and the project `LICENSE`;
- keep PySide6/Qt license notices available to the user;
- avoid preventing reverse engineering strictly needed to debug modifications
  to the LGPL-covered Qt/PySide6 components;
- avoid statically linking Qt unless a compatible license or commercial Qt
  license permits it.

The default PyInstaller one-folder build bundles Qt/PySide6 as separate library
files, which is the intended distribution shape for this project.
