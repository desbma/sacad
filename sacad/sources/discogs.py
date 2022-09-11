""" Discogs cover source. """

import collections
import json

from sacad import __version__
from sacad.cover import CoverImageFormat, CoverImageMetadata, CoverSourceQuality, CoverSourceResult
from sacad.sources.base import CoverSource

FUZZY_MODE = False


class DiscogsCoverSourceResult(CoverSourceResult):

    """Discogs search cover result."""

    def __init__(self, *args, **kwargs):
        quality = CoverSourceQuality.NO_UNRELATED_RESULT_RISK
        if FUZZY_MODE:
            quality |= CoverSourceQuality.FUZZY_SEARCH
        else:
            quality |= CoverSourceQuality.EXACT_SEARCH
        super().__init__(*args, source_quality=quality, **kwargs)


class DiscogsCoverSource(CoverSource):

    """
    Cover source using the official API.

    See https://www.discogs.com/developers
    """

    BASE_URL = "https://api.discogs.com"
    API_KEY = "cGWMOYjQNdWYKXDaxVnR"
    API_SECRET = "NCyWcKHWLAvAreyjDdvVogBzVnzPEEDf"  # not that secret in fact

    def __init__(self, *args, **kwargs):
        # https://www.discogs.com/developers#page:home,header:home-rate-limiting
        super().__init__(*args, min_delay_between_accesses=1, **kwargs)

    def getSearchUrl(self, album, artist):
        """See CoverSource.getSearchUrl."""
        url_params = collections.OrderedDict()
        if FUZZY_MODE:
            url_params["q"] = f"{artist} - {album}"
        else:
            url_params["artist"] = artist
            url_params["release_title"] = album
        url_params["type"] = "release"
        return __class__.assembleUrl(f"{__class__.BASE_URL}/database/search", url_params)

    def updateHttpHeaders(self, headers):
        """See CoverSource.updateHttpHeaders."""
        headers["User-Agent"] = f"sacad/{__version__}"
        headers["Accept"] = "application/vnd.discogs.v2.discogs+json"
        headers["Authorization"] = f"Discogs key={__class__.API_KEY}, secret={__class__.API_SECRET}"

    async def parseResults(self, api_data):
        """See CoverSource.parseResults."""
        json_data = json.loads(api_data)

        results = []
        for rank, release in enumerate(json_data["results"], 1):
            thumbnail_url = release["thumb"]
            img_url = release["cover_image"]
            url_tokens = img_url.split("/")
            url_tokens.reverse()
            try:
                img_width = int(next(t for t in url_tokens if t.startswith("w:")).split(":", 1)[-1])
                img_height = int(next(t for t in url_tokens if t.startswith("h:")).split(":", 1)[-1])
            except StopIteration:
                continue
            result = DiscogsCoverSourceResult(
                img_url,
                (img_width, img_height),
                CoverImageFormat.JPEG,
                thumbnail_url=thumbnail_url,
                source=self,
                rank=rank,
                check_metadata=CoverImageMetadata.NONE,
            )
            results.append(result)

        return results
