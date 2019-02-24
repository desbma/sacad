""" Code to help using the logging module with tqdm progress bars. """

import contextlib
import logging


class TqdmLoggingHandler(logging.Handler):

  """ Logging handler sending messages to the tqdm write method (avoids overlap). """

  def __init__(self, tqdm, *args, **kwargs):
    self.tqdm = tqdm
    super().__init__(*args, **kwargs)

  def emit(self, record):
    msg = self.format(record)
    self.tqdm.write(msg)


@contextlib.contextmanager
def redirect_logging(tqdm_obj, logger=logging.getLogger()):
  """ Context manager to redirect logging to a TqdmLoggingHandler object and then restore the original. """
  # remove current handler
  assert(len(logger.handlers) == 1)
  prev_handler = logger.handlers[0]
  logger.removeHandler(prev_handler)

  # add tqdm handler
  tqdm_handler = TqdmLoggingHandler(tqdm_obj)
  if prev_handler.formatter is not None:
    tqdm_handler.setFormatter(prev_handler.formatter)
  logger.addHandler(tqdm_handler)

  try:
    yield
  finally:
    # restore handler
    logger.removeHandler(tqdm_handler)
    logger.addHandler(prev_handler)
