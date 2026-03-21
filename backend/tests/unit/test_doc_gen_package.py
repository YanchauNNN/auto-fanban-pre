from __future__ import annotations

import importlib
import sys


def test_importing_pdf_engine_does_not_eagerly_import_cad_renderer() -> None:
    to_remove = [
        name
        for name in list(sys.modules)
        if name == "src.doc_gen"
        or name.startswith("src.doc_gen.")
        or name == "src.cad"
        or name.startswith("src.cad.")
    ]
    for name in to_remove:
        sys.modules.pop(name, None)

    module = importlib.import_module("src.doc_gen.pdf_engine")

    assert hasattr(module, "PDFExporter")
    assert "src.cad.dxf_pdf_exporter" not in sys.modules
