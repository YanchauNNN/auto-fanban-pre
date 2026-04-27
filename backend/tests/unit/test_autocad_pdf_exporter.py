from __future__ import annotations


class _FakeApp:
    def __init__(self, version: str = "24.1") -> None:
        self.Version = version


class _FakeClient:
    def __init__(self) -> None:
        self.dispatch_ex_calls: list[str] = []
        self.get_active_calls: list[str] = []
        self.dispatch_calls: list[str] = []

    def DispatchEx(self, prog_id: str):  # noqa: N802
        self.dispatch_ex_calls.append(prog_id)
        raise RuntimeError(f"DispatchEx failed: {prog_id}")

    def GetActiveObject(self, prog_id: str):  # noqa: N802
        self.get_active_calls.append(prog_id)
        raise RuntimeError(f"GetActiveObject failed: {prog_id}")

    def Dispatch(self, prog_id: str):  # noqa: N802
        self.dispatch_calls.append(prog_id)
        return _FakeApp()


class _FakeWin32ComModule:
    def __init__(self, client: _FakeClient) -> None:
        self.client = client


def test_dispatch_autocad_falls_back_to_dispatch_when_dispatchex_and_activeobject_fail() -> None:
    from src.cad.autocad_pdf_exporter import _dispatch_autocad

    client = _FakeClient()
    win32com_module = _FakeWin32ComModule(client)

    app = _dispatch_autocad(
        win32com_module,
        ["AutoCAD.Application.24.1", "AutoCAD.Application.24.0"],
    )

    assert app.Version == "24.1"
    assert client.dispatch_ex_calls == ["AutoCAD.Application.24.1", "AutoCAD.Application.24.0"]
    assert client.get_active_calls == [
        "AutoCAD.Application.24.1",
        "AutoCAD.Application.24.0",
        "AutoCAD.Application",
    ]
    assert client.dispatch_calls == ["AutoCAD.Application.24.1"]
