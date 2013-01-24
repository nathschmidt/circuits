"""
.. codeauthor: mnl
"""

from threading import Event

from .handlers import handler
from .components import BaseComponent
import sys
from circuits.core.handlers import reprhandler


class FallBackGenerator(BaseComponent):

    def __init__(self, *args, **kwargs):
        super(FallBackGenerator, self).__init__(*args, **kwargs)
        self._continue = Event()

    @handler("generate_events", priority=-100, filter=True)
    def _on_generate_events(self, event):
        """
        Fall back handler for the :class:`~.events.GenerateEvents` event.

        When the queue is empty a GenerateEvents event is fired, here
        we sleep for as long as possible to avoid using extra cpu cycles.

        A poller would overwrite with with a higher priority filter, e.g.
        @handler("generate_events", priority=0, filter=True)
        and provide a different way to idle when the queue is empty.
        """
        with event.lock:
            if event.time_left == 0:
                return True
            self._continue.clear()

        if event.time_left > 0:
            # If we get here, there is no component with work to be
            # done and no new event. But some component has requested
            # to be checked again after a certain timeout.
            self._continue.wait(event.time_left)
            # Either time is over or _continue has been set, which
            # implies resume has been called, which means that
            # reduce_time_left(0) has been called. So calling this
            # here is OK in any case.
            event.reduce_time_left(0)
            return True

        while event.time_left < 0:
            # If we get here, there was no work left to do when creating
            # the GenerateEvents event and there is no other handler that
            # is prepared to supply new events within a limited time. The
            # application will continue only if some other Thread fires
            # an event.
            #
            # Python ignores signals when waiting without timeout.
            self._continue.wait(10000)

        return True

    def resume(self):
        """
        Implements the resume method as required from components that
        handle :class:`~.events.GenerateEvents`.
        """
        self._continue.set()


class FallBackErrorHandler(BaseComponent):
    """
    If ther is no handler for error events in the component hierarchy, this
    component's handler is added automatically. It simply prints
    the error information on stderr. 
    """
    
    @handler("error", channel="*")
    def _on_error(self, error_type, value, traceback, handler=None):
        s = []

        if handler is None:
            handler = ""
        else:
            handler = reprhandler(handler)

        msg = "ERROR %s (%s): %s\n" % (handler, error_type, value)
        s.append(msg)
        s.extend(traceback)
        s.append("\n")
        sys.stderr.write("".join(s))
