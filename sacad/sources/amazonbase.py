""" Base class for Amazon cover sources. """

from sacad.sources.base import CoverSource


class AmazonBaseCoverSource(CoverSource):

    """Base class for Amazon cover sources."""

    def __init__(self, *args, base_domain, **kwargs):
        super().__init__(
            *args,
            allow_cookies=True,
            min_delay_between_accesses=2,
            jitter_range_ms=(0, 3000),
            rate_limited_domains=(base_domain,),
            **kwargs,
        )
        self.base_domain = base_domain

    def processQueryString(self, s):
        """See CoverSource.processQueryString."""
        return __class__.unaccentuate(__class__.unpunctuate(s.lower()))

    def isBlocked(self, html):
        """Return True if Amazon source has blocked our IP (temporarily), and is sending a captcha."""
        blocked_titles = ("Robot Check", "Bot Check", "Amazon CAPTCHA")
        title = html.find("head/title")
        assert title is not None
        return title.text in blocked_titles
