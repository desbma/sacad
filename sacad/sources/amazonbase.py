from sacad.sources.base import CoverSource



class AmazonBaseCoverSource(CoverSource):

  """ Base class for Amazon cover sources. """

  def __init__(self, *args, base_domain, **kwargs):
    super().__init__(*args,
                     allow_cookies=True,
                     min_delay_between_accesses=2 / 3,
                     jitter_range_ms=(0, 600),
                     rate_limited_domains=(base_domain,),
                     **kwargs)
    self.current_ua = self.ua.firefox
    self.base_domain = base_domain

  def processQueryString(self, s):
    """ See CoverSource.processQueryString. """
    return __class__.unaccentuate(__class__.unpunctuate(s.lower()))

  def updateHttpHeaders(self, headers):
    """ See CoverSource.updateHttpHeaders. """
    # mimic Firefox headers
    headers["User-Agent"] = self.current_ua
    headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    headers["Accept-Language"] = "en-US,en;q=0.9"
    headers["DNT"] = "1"
    headers["Connection"] = "Keep-Alive"
    headers["Upgrade-Insecure-Requests"] = "1"
    headers["Cache-Control"] = "max-age=0"
    headers["TE"] = "Trailers"

  def isBlocked(self, html):
    """ Return True if Amazon source has blocked our IP (temporarily), and is sending a captcha. """
    blocked_titles = ("Robot Check", "Bot Check", "Amazon CAPTCHA")
    title = html.find("head/title")
    assert(title is not None)
    return title.text in blocked_titles
