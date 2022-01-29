""" Code to help using the logging module with tqdm progress bars. """

import contextlib
import logging
import threading

logging_handlers_lock = threading.Lock()


class TqdmLoggingHandler(logging.Handler):

    """Logging handler sending messages to the tqdm write method (avoids overlap)."""

    def __init__(self, tqdm, *args, **kwargs):
        self.tqdm = tqdm
        super().__init__(*args, **kwargs)

    def emit(self, record):
        """See logging.Handler.emit."""
        msg = self.format(record)
        self.tqdm.write(msg)


@contextlib.contextmanager
def redirect_logging(tqdm_obj, logger=logging.getLogger()):
    """Redirect logging to a TqdmLoggingHandler object and then restore the original logging behavior."""
    with logging_handlers_lock:
        # remove current handlers
        prev_handlers = []
        for handler in logger.handlers.copy():
            prev_handlers.append(handler)
            logger.removeHandler(handler)

        # add tqdm handler
        tqdm_handler = TqdmLoggingHandler(tqdm_obj)
        if prev_handlers[-1].formatter is not None:
            tqdm_handler.setFormatter(prev_handlers[-1].formatter)
        logger.addHandler(tqdm_handler)

    try:
        yield
    finally:
        # restore handlers
        with logging_handlers_lock:
            logger.removeHandler(tqdm_handler)
            for handler in prev_handlers:
                logger.addHandler(handler)
