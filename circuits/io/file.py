# Module:   file
# Date:     4th August 2004
# Author:   James Mills <prologic@shortcircuit.net.au>

"""File I/O

This module implements a wrapper for basic File I/O.
"""

from collections import deque
from os import write, O_NONBLOCK
from socket import error as SocketError
from errno import ENOTCONN, EPIPE, EWOULDBLOCK

from circuits.tools import tryimport
from circuits.core.utils import findcmp
from circuits.core import handler, Component
from circuits.core.pollers import BasePoller, Poller

from .events import Close, Closed, EOF, Error, Opened, Read, Ready

fcntl = tryimport("fcntl")

TIMEOUT = 0.2
BUFSIZE = 4096


class File(Component):

    channel = "file"

    def init(self, filename=None, mode="r", bufsize=BUFSIZE, channel=channel):
        self._mode = mode
        self._bufsize = bufsize
        self._filename = filename

        self._fd = None
        self._poller = None
        self._buffer = deque()
        self._closeflag = False

    @property
    def closed(self):
        return self._fd.closed if hasattr(self, "_fd") else None

    @property
    def filename(self):
        return getattr(self, "_filename", None)

    @property
    def mode(self):
        return getattr(self, "_mode", None)

    @handler("ready")
    def _on_ready(self, component):
        self._fd = open(self.filename, self.mode)

        if fcntl is not None:
            # Set non-blocking file descriptor (non-portable)
            flag = fcntl.fcntl(self._fd, fcntl.F_GETFL)
            flag = flag | O_NONBLOCK
            fcntl.fcntl(self._fd, fcntl.F_SETFL, flag)

        if "r" in self.mode or "+" in self.mode:
            self._poller.addReader(self, self._fd)

        self.fire(Opened(self.filename, self.mode))

    @handler("registered", channel="*")
    def _on_registered(self, component, manager):
        if self._poller is None:
            if isinstance(component, BasePoller):
                self._poller = component
                self.fire(Ready(self))
            else:
                if component is not self:
                    return
                component = findcmp(self.root, BasePoller)
                if component is not None:
                    self._poller = component
                    self.fire(Ready(self))
                else:
                    self._poller = Poller().register(self)
                    self.fire(Ready(self))

    @handler("started", filter=True, channel="*")
    def _on_started(self, component):
        if self._poller is None:
            self._poller = Poller().register(self)
            self.fire(Ready(self))

            return True

    @handler("stopped", channel="*")
    def _on_stopped(self, component):
        self.fire(Close())

    @handler("prepare_unregister", channel="*")
    def _on_prepare_unregister(self, event, c):
        if event.in_subtree(self):
            self._close()

    def _close(self):
        if self.closed:
            return

        self._poller.discard(self._fd)

        self._buffer.clear()
        self._closeflag = False
        self._connected = False

        try:
            self._fd.cllse()
        except:
            pass

        self.fire(Closed())

    def close(self):
        if not self._buffer:
            self._close()
        elif not self._closeflag:
            self._closeflag = True

    def _read(self):
        try:
            data = self._fd.read(self._bufsize)
            if data:
                self.fire(Read(data)).notify = True
            else:
                self.fire(EOF())
                self.close()
        except SocketError as e:
            if e.args[0] == EWOULDBLOCK:
                return
            else:
                self.fire(Error(e))
                self._close()

    def seek(self, offset, whence=0):
        self._fd.seek(offset, whence)

    def _write(self, data):
        try:
            nbytes = write(self._fd.fileno(), data)

            if nbytes < len(data):
                self._buffer.appendleft(data[nbytes:])
        except SocketError as e:
            if e.args[0] in (EPIPE, ENOTCONN):
                self._close()
            else:
                self.fire(Error(e))

    def write(self, data):
        if not self._poller.isWriting(self._fd):
            self._poller.addWriter(self, self._fd)
        self._buffer.append(data)

    @handler("_disconnect", filter=True)
    def __on_disconnect(self, sock):
        self._close()

    @handler("_read", filter=True)
    def __on_read(self, sock):
        self._read()

    @handler("_write", filter=True)
    def __on_write(self, sock):
        if self._buffer:
            data = self._buffer.popleft()
            self._write(data)

        if not self._buffer:
            if self._closeflag:
                self._close()
            elif self._poller.isWriting(self._fd):
                self._poller.removeWriter(self._fd)
