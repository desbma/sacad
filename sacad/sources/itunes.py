""" Itunes cover source. """

import collections
import json

from sacad.cover import SUPPORTED_IMG_FORMATS as EXTENSION_FORMAT
from sacad.cover import CoverImageFormat, CoverImageMetadata, CoverSourceQuality, CoverSourceResult
from sacad.sources.base import CoverSource


class ItunesCoverSourceResult(CoverSourceResult):

    """Itunes search cover result."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            source_quality=CoverSourceQuality.NO_UNRELATED_RESULT_RISK | CoverSourceQuality.EXACT_SEARCH,
            **kwargs,
        )


class ItunesCoverSource(CoverSource):

    """Itunes cover source."""

    SEARCH_URL = "https://itunes.apple.com/search"

    def __init__(self, *args, **kwargs):
        # https://stackoverflow.com/questions/12596300/itunes-search-api-rate-limit
        super().__init__(*args, min_delay_between_accesses=3, **kwargs)

    def getSearchUrl(self, album, artist):
        """See CoverSource.getSearchUrl."""
        url_params = collections.OrderedDict()
        url_params["media"] = "music"
        url_params["entity"] = "album"
        url_params["term"] = f"{artist} {album}"
        return __class__.assembleUrl(__class__.SEARCH_URL, url_params)

    async def parseResults(self, api_data):
        """See CoverSource.parseResults."""
        json_data = json.loads(api_data)

        results = []
        for rank, result in enumerate(json_data["results"], 1):
            thumbnail_url = result["artworkUrl60"]
            base_img_url = result["artworkUrl60"].rsplit("/", 1)[0]
            url_found = False
            for img_size in (5000, 1200, 600):
                for img_format in (CoverImageFormat.PNG, CoverImageFormat.JPEG):
                    suffix = "-100.jpg" if (img_format is CoverImageFormat.JPEG) else ".png"
                    img_url = f"{base_img_url}/{img_size}x{img_size}{suffix}"
                    if await self.probeUrl(img_url):
                        url_found = True
                        break
                if url_found:
                    break
            else:
                img_url = result["artworkUrl100"]
                img_format = EXTENSION_FORMAT[img_url.rsplit(".", 1)[-1]]
                img_size = 100
            result = ItunesCoverSourceResult(
                img_url,
                (img_size, img_size),
                img_format,
                thumbnail_url=thumbnail_url,
                source=self,
                rank=rank,
                check_metadata=CoverImageMetadata.NONE,
            )
            results.append(result)

        return results
