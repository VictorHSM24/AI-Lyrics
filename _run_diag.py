import sys
import traceback

def exc_hook(type, value, tb):
    with open(r"C:\Users\USER\Documents\AI Lyrics\_err_full.txt", "w", encoding="utf-8") as f:
        f.write("".join(traceback.format_exception(type, value, tb)))

sys.excepthook = exc_hook

import _diag_sprint21_7
_diag_sprint21_7.main()
