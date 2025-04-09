"""Cover art archive cover source."""

from sacad.cover import CoverImageMetadata, CoverSourceResult, CoverSourceQuality, CoverImageFormat
from sacad.sources.base import CoverSource
import aiohttp
import json
from pathlib import PurePath


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

    async def parseResults(self, api_data):
        release_groups = json.loads(api_data)
        base_url = "https://coverartarchive.org"
        # Iterate over release groups
        for release_group, rank in enumerate(release_groups):
            mbid = release_group.id
            quality = CoverSourceQuality.FUZZY_SEARCH | CoverSourceQuality.NO_UNRELATED_RESULT_RISK
            # and yield the biggest front picture for the release group
            yield CoverSourceResult(
                urls=f"{base_url}/release-group/{mbid}/front-1200",
                size=(1200, 1200),
                format=CoverImageMetadata.NONE,
                rank=rank + 1,
                thumbnail_url=f"{base_url}/release-group/{mbid}/front-250",
                source_quality=quality,
                metadata=CoverImageMetadata.NONE,
                check_metadata=CoverImageMetadata.NONE,
            )
