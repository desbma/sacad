import contextlib
import os
import tempfile


@contextlib.contextmanager
def mkstemp(*args, **kwargs):
  """
  Context manager similar to tempfile.NamedTemporaryFile except the file is not deleted on close, and only the filepath
  is returned
  .. warnings:: Unlike tempfile.mkstemp, this is not secure
  """
  fd, filename = tempfile.mkstemp(*args, **kwargs)
  os.close(fd)
  try:
    yield filename
  finally:
    os.remove(filename)
