"""Seletor nativo de pastas do Windows via COM (IFileOpenDialog).

O browser não expõe o caminho real de uma pasta escolhida pelo usuário,
então o seletor é aberto pelo backend — que é quem escreve os arquivos.

Implementação COM via ctypes puro (sem dependências externas):
funciona em execução normal e no bundle PyInstaller — tkinter é
excluído do .spec (ver excludes em ai-lyrics.spec) e pywin32 não é
dependência do projeto.

Em plataformas não-Windows, pick_folder() levanta RuntimeError.

Layout dos vtables usados (shobjidl_core.h):
  IUnknown        : 0 QueryInterface, 1 AddRef, 2 Release
  IModalWindow    : 3 Show
  IFileDialog     : 4..26 (SetFileTypes, ..., SetFilter)
  IFileOpenDialog : 27 GetResults, 28 GetSelectedItems
  IShellItem      : 3 BindToHandler, 4 GetParent, 5 GetDisplayName,
                    6 GetAttributes, 7 Compare
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes.wintypes import DWORD, HWND, LPCWSTR

logger = logging.getLogger(__name__)

# Constantes COM/Win32.
COINIT_APARTMENTTHREADED = 0x2
COINIT_DISABLE_OLE1DDE = 0x4
CLSCTX_ALL = 0x17
FOS_PICKFOLDERS = 0x20
SIGDN_FILESYSPATH = 0x80058000
S_OK = 0
S_FALSE = 1
RPC_E_CHANGED_MODE = 0x80010106
E_CANCELLED = -2147023673  # 0x800704C7 = HRESULT_FROM_WIN32(ERROR_CANCELLED)


class GUID(ctypes.Structure):
    """GUID COM binário (formato de registro, não string)."""

    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(text: str) -> GUID:
    """Converte 'XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX' para GUID binário."""
    h = text.replace("-", "")
    g = GUID()
    g.Data1 = int(h[0:8], 16)
    g.Data2 = int(h[8:12], 16)
    g.Data3 = int(h[12:16], 16)
    for i, b in enumerate(bytes.fromhex(h[16:32])):
        g.Data4[i] = b
    return g


CLSID_FILE_OPEN_DIALOG = _guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
IID_IFILE_OPEN_DIALOG = _guid("D57C7288-D4AD-4768-BE02-9D969532D960")
IID_ISHELL_ITEM = _guid("43826D1E-E718-42EE-BC55-A1E261C37BFE")

# Índices dos métodos nos vtables (ver docstring do módulo).
_V_RELEASE = 2
_V_SHOW = 3
_V_SET_OPTIONS = 9
_V_GET_OPTIONS = 10
_V_SET_FOLDER = 12
_V_SET_TITLE = 17
_V_GET_RESULT = 20
_V_GET_DISPLAY_NAME = 5  # IShellItem


def _method(p_obj, index: int, restype, *argtypes):
    """Resolve o método `index` da vtable COM apontada por `p_obj`."""
    vtbl = ctypes.cast(p_obj, ctypes.POINTER(ctypes.c_void_p)).contents
    table = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(table[index])


def _release(p_obj) -> None:
    """IUnknown::Release — libera a referência COM."""
    if p_obj:
        _method(p_obj, _V_RELEASE, ctypes.c_ulong)(p_obj)


def _fmt(api: str, hr: int) -> str:
    return f"{api} falhou: HRESULT 0x{hr & 0xFFFFFFFF:08X}"


def pick_folder(initial_dir: str = "", title: str = "Selecionar pasta") -> str | None:
    """Abre o seletor nativo de pastas do Windows (IFileOpenDialog).

    Args:
        initial_dir: pasta inicial do seletor ("" usa a pasta padrão).
        title: título da janela do seletor.

    Returns:
        Caminho absoluto da pasta escolhida, ou None se o usuário
        cancelou o diálogo.

    Raises:
        RuntimeError: plataforma não-Windows ou falha COM.
    """
    if sys.platform != "win32":
        raise RuntimeError("Seletor nativo de pastas só está disponível no Windows.")

    ole32 = ctypes.OleDLL("ole32")
    shell32 = ctypes.windll.shell32
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoCreateInstance.restype = ctypes.c_long
    shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
    ole32.CoTaskMemFree.restype = None

    hr = ole32.CoInitializeEx(
        None, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE
    )
    coinit = hr in (S_OK, S_FALSE)
    if not coinit and hr != RPC_E_CHANGED_MODE:
        raise RuntimeError(_fmt("CoInitializeEx", hr))

    dlg = ctypes.c_void_p()
    try:
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_FILE_OPEN_DIALOG),
            None,
            CLSCTX_ALL,
            ctypes.byref(IID_IFILE_OPEN_DIALOG),
            ctypes.byref(dlg),
        )
        if hr < 0 or not dlg.value:
            raise RuntimeError(_fmt("CoCreateInstance(IFileOpenDialog)", hr))

        opts = DWORD(0)
        hr = _method(dlg, _V_GET_OPTIONS, ctypes.c_long, ctypes.POINTER(DWORD))(
            dlg, ctypes.byref(opts)
        )
        if hr < 0:
            raise RuntimeError(_fmt("IFileOpenDialog::GetOptions", hr))
        hr = _method(dlg, _V_SET_OPTIONS, ctypes.c_long, DWORD)(
            dlg, DWORD(opts.value | FOS_PICKFOLDERS)
        )
        if hr < 0:
            raise RuntimeError(_fmt("IFileOpenDialog::SetOptions", hr))

        if title:
            _method(dlg, _V_SET_TITLE, ctypes.c_long, LPCWSTR)(dlg, title)

        # Pasta inicial — SetFolder exige um IShellItem da pasta.
        if initial_dir:
            folder = ctypes.c_void_p()
            hr = shell32.SHCreateItemFromParsingName(
                initial_dir, None, ctypes.byref(IID_ISHELL_ITEM), ctypes.byref(folder)
            )
            if hr >= 0 and folder.value:
                _method(dlg, _V_SET_FOLDER, ctypes.c_long, ctypes.c_void_p)(
                    dlg, folder
                )
                _release(folder)

        # Janela-pai = janela em foreground (o browser que disparou a
        # chamada): torna o seletor modal e garante que ele apareça na
        # frente em vez de atrás do browser maximizado.
        hwnd_parent = ctypes.windll.user32.GetForegroundWindow()
        hr = _method(dlg, _V_SHOW, ctypes.c_long, HWND)(dlg, hwnd_parent)
        if hr == E_CANCELLED:
            return None
        if hr < 0:
            raise RuntimeError(_fmt("IFileOpenDialog::Show", hr))

        item = ctypes.c_void_p()
        hr = _method(dlg, _V_GET_RESULT, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))(
            dlg, ctypes.byref(item)
        )
        if hr < 0 or not item.value:
            raise RuntimeError(_fmt("IFileOpenDialog::GetResult", hr))
        try:
            p_str = ctypes.c_void_p()
            hr = _method(
                item,
                _V_GET_DISPLAY_NAME,
                ctypes.c_long,
                ctypes.c_uint,
                ctypes.POINTER(ctypes.c_void_p),
            )(item, SIGDN_FILESYSPATH, ctypes.byref(p_str))
            if hr < 0 or not p_str.value:
                raise RuntimeError(_fmt("IShellItem::GetDisplayName", hr))
            try:
                path = ctypes.cast(p_str, LPCWSTR).value
            finally:
                ole32.CoTaskMemFree(p_str)
            logger.info("Pasta selecionada no seletor nativo: %s", path)
            return path
        finally:
            _release(item)
    finally:
        if dlg.value:
            _release(dlg)
        if coinit:
            ole32.CoUninitialize()
