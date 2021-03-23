""" Additions to the tempfile module. """

import contextlib
import os
import tempfile


@contextlib.contextmanager
def mkstemp(*args, **kwargs):
    """
    Safely generate a temporary file path.

    Context manager similar to tempfile.NamedTemporaryFile except the file is not deleted on close, and only the
    filepath is returned
    """
    fd, filename = tempfile.mkstemp(*args, **kwargs)
    os.close(fd)
    try:
        yield filename
    finally:
        os.remove(filename)
