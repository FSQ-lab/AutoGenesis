"""Windows stdin readiness without an abandoned blocking reader thread."""

import os

import anyio


class _WindowsAPI:
    def __init__(self, fd):
        import ctypes
        import msvcrt
        from ctypes import wintypes

        self.ctypes = ctypes
        self.msvcrt = msvcrt
        self.fd = fd
        msvcrt.setmode(fd, os.O_BINARY)
        # Borrow the CRT handle; neither this adapter nor cancellation closes it.
        self.handle = wintypes.HANDLE(msvcrt.get_osfhandle(fd))
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.GetFileType.argtypes = [wintypes.HANDLE]
        self.kernel.GetFileType.restype = wintypes.DWORD
        self.kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.GetConsoleMode.restype = wintypes.BOOL
        self.kernel.PeekNamedPipe.argtypes = [
            wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel.PeekNamedPipe.restype = wintypes.BOOL
        file_type = self.kernel.GetFileType(self.handle)
        mode = wintypes.DWORD()
        if file_type == 3:  # FILE_TYPE_PIPE, including anonymous subprocess pipes
            self.kind = "pipe"
        elif file_type == 1:  # FILE_TYPE_DISK: finite redirected file reads
            self.kind = "file"
        elif file_type == 2 and self.kernel.GetConsoleMode(self.handle, ctypes.byref(mode)):
            self.kind = "console"
        else:
            raise OSError("Unsupported Windows stdin; use a pipe, file, or console.")

    def available(self):
        from ctypes import wintypes
        count = wintypes.DWORD()
        if self.kernel.PeekNamedPipe(self.handle, None, 0, None, self.ctypes.byref(count), None):
            return count.value
        error = self.ctypes.get_last_error()
        if error in {109, 232, 233}:  # broken pipe / no data / pipe not connected
            return None
        raise OSError(error, "Windows stdin readiness check failed.")

    def read(self, size):
        return os.read(self.fd, size)

    def key_ready(self):
        return self.msvcrt.kbhit()

    def read_key(self):
        return self.msvcrt.getwch()


class WindowsStdin:
    """The sole pipe consumer reads only bytes reported available by the kernel.

    Idle waits are async cancellation checkpoints. No stdin worker survives
    SIGINT, and a broken pipe is EOF even when the writer closed without data.
    Consoles use character readiness instead of a blocking line-mode read.
    """

    def __init__(self, fd, *, api=None):
        self.api = _WindowsAPI(fd) if api is None else api
        self.console_eof = False
        self.ignore_keycode = False

    async def read(self, size):
        if self.api.kind == "file":
            return self.api.read(size)
        if self.api.kind == "console":
            return await self._console_line()
        while True:
            count = self.api.available()
            if count is None:
                return b""
            if count:
                return self.api.read(min(size, count))
            await anyio.sleep(0.01)

    async def _console_line(self):
        characters = []
        while not self.console_eof:
            if not self.api.key_ready():
                await anyio.sleep(0.01)
                continue
            character = self.api.read_key()
            if self.ignore_keycode:
                self.ignore_keycode = False
                continue
            code = ord(character)
            if code in {0, 224}:  # extended key prefix; ignore its next keycode
                self.ignore_keycode = True
            elif code == 26:  # Ctrl+Z: console EOF
                self.console_eof = True
            elif code in {10, 13}:
                characters.append(chr(10))
                break
            elif code == 8:
                if characters:
                    last = characters.pop()
                    if 0xDC00 <= ord(last) <= 0xDFFF and characters and 0xD800 <= ord(characters[-1]) <= 0xDBFF:
                        characters.pop()
            else:
                characters.append(character)
        # getwch may deliver UTF-16 surrogate pairs as separate characters.
        return "".join(characters).encode("utf-16-le", "surrogatepass").decode("utf-16-le").encode("utf-8")
