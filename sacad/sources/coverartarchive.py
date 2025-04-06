"""Cover art archive cover source."""

from sacad import __version__
from sacad.cover import CoverImageFormat, CoverImageMetadata, CoverSourceResult, CoverSourceQuality
from sacad.sources.base import CoverSource
import aiohttp
import json


class CoverArtArchiveSource(CoverSource):
    #BASE_URL = "https://coverartarchive.org"
    BASE_URL = "https://musicbrainz.org/ws/2"
    API_KEY = ""
    API_SECRET = ""

    def getSearchUrl(self, album, artist):
        # For the cover art archive, one must first retrieve the
        # Musicbrainz ID of at least the release group and then use that
        # id to fetch the cover from the cover art archive
        # See https://musicbrainz.org/doc/Cover_Art_Archive/API
        # On how to retrieve the release group id, see
        # https://musicbrainz.org/doc/MusicBrainz_API
        return CoverSource.assembleUrl(
            f"{self.BASE_URL}/release-group", {"query": f"artist:{artist} AND album:{album}", "fmt": "json"}
        )

    def updateHttpHeaders(self, headers):
        headers["User-Agent"] = f"sacad/{__version__}"
        
    async def parseResults(self, api_data):
        release_group = json.loads(api_data)
        mbid = release_group.release_groups[0].id
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://coverartarchive.org/release-group/{mbid}/front") as resp:
                assert resp.status == 200
                cover_json = json.loads(resp.text)
                for rank, x in enumerate(cover_json.images, 1):
                    yield CoverSourceResult(
                        urls=x.image,
                        size = None,
                        format = CoverImageFormat.NONE,
                        rank=rank,
                        thumbnail_url = x.thumbnails.small, 
                        source_quality=CoverSourceQuality.EXACT_SEARCH,
                        metadata = CoverImageMetadata.NONE,
                        check_metadata = 1
                    )
