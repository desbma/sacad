from sacad.sources.base import CoverSource



class AmazonBaseCoverSource(CoverSource):

  """ Base class for Amazon cover sources. """

  def __init__(self, *args, **kwargs):
    super().__init__(*args,
                     allow_cookies=True,
                     min_delay_between_accesses=2 / 3,
                     jitter_range_ms=(0, 500),
                     **kwargs)

  def processQueryString(self, s):
    """ See CoverSource.processQueryString. """
    return __class__.unaccentuate(__class__.unpunctuate(s.lower()))

  def updateHttpHeaders(self, headers):
    """ See CoverSource.updateHttpHeaders. """
    headers["User-Agent"] = self.ua.random
