"""Cover art archive cover source."""

from sacad import __version__
from sacad.cover import CoverImageFormat, CoverImageMetadata, CoverSourceResult, CoverSourceQuality
from sacad.sources.base import CoverSource
import aiohttp
import json


class CoverArtArchiveSource(CoverSource):
    """
    Cover source using the Cover Art Archive official API.

    The documentation of the API is available at
    https://musicbrainz.org/doc/Cover_Art_Archive/API

    """

    # The cover art archive is tied with Musicbrainz.
    # Therefore, in order to get a cover, one must first get a release
    # identifier or release group identifier.
    # To get the release (or release group) id, one can either read from
    # the tags (which isn't allowed for now in sacad), or one can ask the
    # musicbrainz database for identifiers from the album and artist name.
    # See https://musicbrainz.org/doc/MusicBrainz_API for the API of
    # musicbrainz.
    BASE_URL = "https://musicbrainz.org/ws/2"
    API_KEY = ""
    API_SECRET = ""

    def getSearchUrl(self, album, artist):
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
                        size=None,
                        format=CoverImageFormat.NONE,
                        rank=rank,
                        thumbnail_url=x.thumbnails.small,
                        source_quality=CoverSourceQuality.EXACT_SEARCH,
                        metadata=CoverImageMetadata.NONE,
                        check_metadata=1,
                    )
