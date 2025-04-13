"""Cover art archive cover source."""

from sacad import __version__
from sacad.cover import CoverImageMetadata, CoverSourceResult, CoverSourceQuality
from sacad.sources.base import CoverSource
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

    def getSearchUrl(self, album, artist):
        return CoverSource.assembleUrl(
            f"{self.BASE_URL}/release-group", {"query": f"artist:{artist} AND album:{album}", "fmt": "json"}
        )

    def updateHttpHeaders(self, headers):
        headers["User-Agent"] = f"sacad/{__version__} (https://github.com/desbma/sacad)"

    async def parseResults(self, api_data, *, search_album, search_artist):
        response = json.loads(api_data)
        base_url = "https://coverartarchive.org"

        def f(rank, release_group):
            mbid = release_group["id"]
            quality = CoverSourceQuality.EXACT_SEARCH | CoverSourceQuality.NO_UNRELATED_RESULT_RISK
            # and yield the biggest front picture for the release group
            return CoverSourceResult(
                urls=f"{base_url}/release-group/{mbid}/front-1200",
                size=(1200, 1200),
                format=None,
                rank=rank + 1,
                thumbnail_url=f"{base_url}/release-group/{mbid}/front-250",
                source=self,
                source_quality=quality,
                check_metadata=CoverImageMetadata.FORMAT,
            )
        return (f(rank, rg) for (rank, rg) in enumerate(response["release-groups"]))
