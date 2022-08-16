""" Deezer cover source. """

import collections
import json
import operator

from sacad.cover import CoverImageFormat, CoverImageMetadata, CoverSourceQuality, CoverSourceResult
from sacad.sources.base import CoverSource


class DeezerCoverSourceResult(CoverSourceResult):

    """Deezer search cover result."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            source_quality=CoverSourceQuality.EXACT_SEARCH | CoverSourceQuality.NO_UNRELATED_RESULT_RISK,
            **kwargs,
        )


class DeezerCoverSource(CoverSource):

    """
    Cover source using the official Deezer API.

    https://developers.deezer.com/api/
    """

    BASE_URL = "https://api.deezer.com/search"
    COVER_SIZES = {
        "cover_small": (56, 56),
        "cover": (120, 120),
        "cover_medium": (250, 250),
        "cover_big": (500, 500),
        "cover_xl": (1000, 1000),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, min_delay_between_accesses=0.1, **kwargs)

    def getSearchUrl(self, album, artist):
        """See CoverSource.getSearchUrl."""
        # build request url
        search_params = collections.OrderedDict()
        search_params["artist"] = artist
        search_params["album"] = album
        url_params = collections.OrderedDict()
        # url_params["strict"] = "on"
        url_params["order"] = "RANKING"
        url_params["q"] = " ".join(f'{k}:"{v}"' for k, v in search_params.items())
        return __class__.assembleUrl(__class__.BASE_URL, url_params)

    def processQueryString(self, s):
        """See CoverSource.processQueryString."""
        # API search is fuzzy, not need to alter query
        return s

    async def parseResults(self, api_data):
        """See CoverSource.parseResults."""
        results = []

        # get unique albums
        json_data = json.loads(api_data)
        albums = []
        for e in json_data["data"]:
            album = e["album"]
            album_id = album["id"]
            if album_id in map(operator.itemgetter("id"), albums):
                continue
            albums.append(album)

        for rank, album in enumerate(albums, 1):
            for key, size in __class__.COVER_SIZES.items():
                img_url = album[key]
                thumbnail_url = album["cover_small"]
                results.append(
                    DeezerCoverSourceResult(
                        img_url,
                        size,
                        CoverImageFormat.JPEG,
                        thumbnail_url=thumbnail_url,
                        source=self,
                        rank=rank,
                        check_metadata=CoverImageMetadata.NONE,
                    )
                )

        return results
