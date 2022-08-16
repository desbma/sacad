""" Sacad album cover. """

import asyncio
import enum
import imghdr
import io
import itertools
import logging
import math
import mimetypes
import operator
import os
import pickle
import shutil
import urllib.parse

import appdirs
import bitarray

try:
    from bitarray import bitdiff
except ImportError:
    from bitarray.util import count_xor as bitdiff

import PIL.Image
import PIL.ImageFile
import PIL.ImageFilter
import web_cache

from sacad import mkstemp_ctx

PIL.ImageFile.LOAD_TRUNCATED_IMAGES = True

CoverImageFormat = enum.Enum("CoverImageFormat", ("JPEG", "PNG"))


class CoverSourceQuality(enum.IntFlag):

    """Flags to describe cover source quality."""

    # whether or not the search query matching is fuzzy (does a typo return results ?)
    FUZZY_SEARCH = 0
    EXACT_SEARCH = 1 << 1
    # whether or not the source will return complete crap instead of no results when it has not found a real match
    # this seems similar to the previous flags but is different
    UNRELATED_RESULT_RISK = 0
    NO_UNRELATED_RESULT_RISK = 1 << 2

    def isReference(self) -> bool:
        """
        Return True if the source if of 'reference' quality.

        'Reference' means a result can only be the correct cover (but can be wrong size/format).
        """
        mask = self.EXACT_SEARCH | self.NO_UNRELATED_RESULT_RISK
        return (self.value & mask) == mask


class CoverImageMetadata(enum.IntFlag):

    """Flags to describe image metadata."""

    NONE = 0
    FORMAT = 1
    SIZE = 2
    ALL = 3


HAS_JPEGOPTIM = shutil.which("jpegoptim") is not None
HAS_OPTIPNG = shutil.which("optipng") is not None
SUPPORTED_IMG_FORMATS = {"jpg": CoverImageFormat.JPEG, "jpeg": CoverImageFormat.JPEG, "png": CoverImageFormat.PNG}
FORMAT_EXTENSIONS = {CoverImageFormat.JPEG: "jpg", CoverImageFormat.PNG: "png"}


def is_square(x):
    """Return True if integer x is a perfect square, False otherwise."""
    return math.sqrt(x).is_integer()


class CoverSourceResult:

    """Cover image returned by a source, candidate to be downloaded."""

    METADATA_PEEK_SIZE_INCREMENT = 2**12
    MAX_FILE_METADATA_PEEK_SIZE = 20 * METADATA_PEEK_SIZE_INCREMENT
    IMG_SIG_SIZE = 16

    def __init__(
        self,
        urls,
        size,
        format,
        *,
        thumbnail_url,
        source,
        source_quality,
        rank=None,
        check_metadata=CoverImageMetadata.NONE,
    ):
        # noqa: D205,D213,D400,D415
        """
        Args:
          urls: Cover image file URL. Can be a tuple of URLs of images to be joined
          size: Cover size as a (with, height) tuple
          format: Cover image format as a CoverImageFormat enum, or None if unknown
          thumbnail_url: Cover thumbnail image file URL, or None if not available
          source: Cover source object that produced this result
          source_quality: Quality of the cover's source as a CoverSourceQuality enum value
          rank: Integer ranking of the cover in the other results from the same source, or None if not available
          check_metadata: If != 0, hint that the format and/or size parameters are not reliable and must be double
          checked
        """
        if not isinstance(urls, str):
            self.urls = urls
        else:
            self.urls = (urls,)
        self.size = size
        assert (format is None) or (format in CoverImageFormat)
        self.format = format
        self.thumbnail_url = thumbnail_url
        self.thumbnail_sig = None
        self.source = source
        self.source_quality = source_quality
        self.rank = rank
        assert (format is not None) or ((check_metadata & CoverImageMetadata.FORMAT) != 0)
        assert (size is not None) or ((check_metadata & CoverImageMetadata.SIZE) != 0)
        self.check_metadata = check_metadata
        self.reliable_metadata = True
        self.is_similar_to_reference = False
        self.is_only_reference = False
        if not hasattr(__class__, "image_cache"):
            cache_filepath = os.path.join(
                appdirs.user_cache_dir(appname="sacad", appauthor=False), "sacad-cache.sqlite"
            )
            os.makedirs(os.path.dirname(cache_filepath), exist_ok=True)
            __class__.image_cache = web_cache.WebCache(
                cache_filepath,
                "cover_image_data",
                caching_strategy=web_cache.CachingStrategy.LRU,
                expiration=60 * 60 * 24 * 365,
            )  # 1 year
            __class__.metadata_cache = web_cache.WebCache(
                cache_filepath,
                "cover_metadata",
                caching_strategy=web_cache.CachingStrategy.LRU,
                expiration=60 * 60 * 24 * 365,
            )  # 1 year
            for cache, cache_name in zip(
                (__class__.image_cache, __class__.metadata_cache), ("cover_image_data", "cover_metadata")
            ):
                purged_count = cache.purge()
                logging.getLogger("Cache").debug(
                    f"{purged_count} obsolete entries have been removed from cache {cache_name!r}"
                )
                row_count = len(cache)
                logging.getLogger("Cache").debug(f"Cache {cache_name!r} contains {row_count} entries")

    def __str__(self):
        s = f"{self.__class__.__name__} {self.urls[0]!r}"
        if len(self.urls) > 1:
            s += f" [x{len(self.urls)}]"
        return s

    async def get(self, target_format, target_size, size_tolerance_prct, out_filepath, *, preserve_format=False):
        """Download cover and process it."""
        images_data = []
        for i, url in enumerate(self.urls):
            # download
            logging.getLogger("Cover").info(f"Downloading cover {url!r} (part {i + 1}/{len(self.urls)})...")
            headers = {}
            self.source.updateHttpHeaders(headers)

            async def pre_cache_callback(img_data):
                return await __class__.crunch(img_data, self.format)

            store_in_cache_callback, image_data = await self.source.http.query(
                url, headers=headers, verify=False, cache=__class__.image_cache, pre_cache_callback=pre_cache_callback
            )

            # store immediately in cache
            await store_in_cache_callback()

            # append for multi images
            images_data.append(image_data)

        need_format_change = self.format != target_format
        need_size_change = (max(self.size) > target_size) and (
            abs(max(self.size) - target_size) > target_size * size_tolerance_prct / 100
        )
        need_join = len(images_data) > 1
        if (need_format_change and (not preserve_format)) or need_join or need_size_change:
            # post process
            image_data = self.postProcess(
                images_data, target_format if need_format_change else None, target_size if need_size_change else None
            )

            # crunch image again
            image_data = await __class__.crunch(image_data, target_format)

            format_changed = need_format_change
        else:
            format_changed = False

        # write it
        if need_format_change and (not format_changed):
            assert preserve_format
            out_filepath = f"{os.path.splitext(out_filepath)[0]}.{FORMAT_EXTENSIONS[self.format]}"
        with open(out_filepath, "wb") as file:
            file.write(image_data)

    def postProcess(self, images_data, new_format, new_size):
        """
        Convert image binary data.

        Convert image binary data to a target format and/or size (None if no conversion needed), and return the
        processed data.
        """
        if len(images_data) == 1:
            in_bytes = io.BytesIO(images_data[0])
            img = PIL.Image.open(in_bytes)
            if img.mode != "RGB":
                img = img.convert("RGB")

        else:
            # images need to be joined before further processing
            logging.getLogger("Cover").info(f"Joining {len(images_data)} images...")
            # TODO find a way to do this losslessly for JPEG
            new_img = PIL.Image.new("RGB", self.size)
            assert is_square(len(images_data))
            sq = int(math.sqrt(len(images_data)))

            images_data_it = iter(images_data)
            img_sizes = {}
            for x in range(sq):
                for y in range(sq):
                    current_image_data = next(images_data_it)
                    img_stream = io.BytesIO(current_image_data)
                    img = PIL.Image.open(img_stream)
                    img_sizes[(x, y)] = img.size
                    box = [0, 0]
                    if x > 0:
                        for px in range(x):
                            box[0] += img_sizes[(px, y)][0]
                    if y > 0:
                        for py in range(y):
                            box[1] += img_sizes[(x, py)][1]
                    box.extend((box[0] + img.size[0], box[1] + img.size[1]))
                    new_img.paste(img, box=tuple(box))
            img = new_img

        out_bytes = io.BytesIO()
        if new_size is not None:
            logging.getLogger("Cover").info(f"Resizing from {self.size[0]}x{self.size[1]} to {new_size}x{new_size}...")
            img = img.resize((new_size, new_size), PIL.Image.LANCZOS)
            # apply unsharp filter to remove resize blur (equivalent to (images/graphics)magick -unsharp 1.5x1+0.7+0.02)
            # we don't use PIL.ImageFilter.SHARPEN or PIL.ImageEnhance.Sharpness because we want precise control over
            # parameters
            unsharper = PIL.ImageFilter.UnsharpMask(radius=1.5, percent=70, threshold=5)
            img = img.filter(unsharper)
        if new_format is not None:
            logging.getLogger("Cover").info(f"Converting to {new_format.name.upper()}...")
            target_format = new_format
        else:
            target_format = self.format
        img.save(out_bytes, format=target_format.name, quality=90, optimize=True)
        return out_bytes.getvalue()

    async def updateImageMetadata(self):  # noqa: C901
        """Download image file(s) partially to get its real metadata, or get it from cache."""
        assert self.needMetadataUpdate()

        width_sum, height_sum = 0, 0

        # only download metadata for the needed images to get full size
        idxs = []
        assert is_square(len(self.urls))
        sq = int(math.sqrt(len(self.urls)))
        for x in range(sq):
            for y in range(sq):
                if x == y:
                    idxs.append((x * sq + y, x, y))

        for idx, x, y in idxs:
            url = self.urls[idx]
            format, width, height = None, None, None

            try:
                format, width, height = pickle.loads(__class__.metadata_cache[url])
            except KeyError:
                # cache miss
                pass
            except Exception as e:
                logging.getLogger("Cover").warning(
                    f"Unable to load metadata for URL {url!r} from cache: {e.__class__.__qualname__} {e}"
                )
            else:
                # cache hit
                logging.getLogger("Cover").debug(f"Got metadata for URL {url!r} from cache")
                if format is not None:
                    self.setFormatMetadata(format)

            if self.needMetadataUpdate(CoverImageMetadata.FORMAT) or (
                self.needMetadataUpdate(CoverImageMetadata.SIZE) and ((width is None) or (height is None))
            ):
                # download
                logging.getLogger("Cover").debug(f"Downloading file header for URL {url!r}...")
                try:
                    headers = {}
                    self.source.updateHttpHeaders(headers)
                    response = await self.source.http.fastStreamedQuery(url, headers=headers, verify=False)
                    try:
                        if self.needMetadataUpdate(CoverImageMetadata.FORMAT):
                            # try to get format from response
                            format = __class__.guessImageFormatFromHttpResponse(response)
                            if format is not None:
                                self.setFormatMetadata(format)

                        if self.needMetadataUpdate():
                            # try to get metadata from HTTP data
                            metadata = await __class__.guessImageMetadataFromHttpData(response)
                            if metadata is not None:
                                format, width, height = metadata
                                if format is not None:
                                    self.setFormatMetadata(format)

                    finally:
                        await response.release()

                except Exception as e:
                    logging.getLogger("Cover").warning(
                        f"Failed to get file metadata for URL {url!r} ({e.__class__.__qualname__} {e})"
                    )

                if self.needMetadataUpdate():  # did we fail to get needed metadata at this point?
                    if (self.format is None) or ((self.size is None) and ((width is None) or (height is None))):
                        # if we get here, file is probably not reachable, or not even an image
                        logging.getLogger("Cover").debug(
                            f"Unable to get file metadata from file or HTTP headers for URL {url!r}, "
                            "skipping this result"
                        )
                        return

                    if (self.format is not None) and ((self.size is not None) and (width is None) and (height is None)):
                        logging.getLogger("Cover").debug(
                            f"Unable to get file metadata from file or HTTP headers for URL {url!r}, "
                            "falling back to API data"
                        )
                        self.check_metadata = CoverImageMetadata.NONE
                        self.reliable_metadata = False
                        return

                # save it to cache
                __class__.metadata_cache[url] = pickle.dumps((format, width, height))

            # sum sizes
            if (width is not None) and (height is not None):
                width_sum += width
                height_sum += height

        if self.needMetadataUpdate(CoverImageMetadata.SIZE) and (width_sum > 0) and (height_sum > 0):
            self.setSizeMetadata((width_sum, height_sum))

    def needMetadataUpdate(self, what=CoverImageMetadata.ALL):
        """Return True if image metadata needs to be checked, False instead."""
        return (self.check_metadata & what) != 0

    def setFormatMetadata(self, format):
        """Set format image metadata to what has been reliably identified."""
        self.format = format
        self.check_metadata &= ~CoverImageMetadata.FORMAT

    def setSizeMetadata(self, size):
        """Set size image metadata to what has been reliably identified."""
        self.size = size
        self.check_metadata &= ~CoverImageMetadata.SIZE

    async def updateSignature(self):
        """Calculate a cover's "signature" using its thumbnail url."""
        assert self.thumbnail_sig is None

        if self.thumbnail_url is None:
            logging.getLogger("Cover").warning(f"No thumbnail available for {self}")
            return

        # download
        logging.getLogger("Cover").debug(f"Downloading cover thumbnail {self.thumbnail_url!r}...")
        headers = {}
        self.source.updateHttpHeaders(headers)

        async def pre_cache_callback(img_data):
            return await __class__.crunch(img_data, CoverImageFormat.JPEG, silent=True)

        try:
            store_in_cache_callback, image_data = await self.source.http.query(
                self.thumbnail_url, cache=__class__.image_cache, headers=headers, pre_cache_callback=pre_cache_callback
            )
        except Exception as e:
            logging.getLogger("Cover").warning(
                f"Download of {self.thumbnail_url!r} failed: {e.__class__.__qualname__} {e}"
            )
            return

        # compute sig
        logging.getLogger("Cover").debug(f"Computing signature of {self}...")
        try:
            self.thumbnail_sig = __class__.computeImgSignature(image_data)
        except Exception as e:
            logging.getLogger("Cover").warning(
                f"Failed to compute signature of '{self}': {e.__class__.__qualname__} {e}"
            )
        else:
            await store_in_cache_callback()

    @staticmethod
    def compare(first, second, *, target_size, size_tolerance_prct):
        """
        Compare cover relevance/quality.

        Return -1 if first is a worst match than second, 1 otherwise, or 0 if cover can't be discriminated.

        This code is responsible for comparing two cover results to identify the best one, and is used to sort all
        results.
        It is probably the most important piece of code of this tool.
        Covers with sizes under the target size (+- configured tolerance) are excluded before comparison.
        The following factors are used in order:
          1. Prefer approximately square covers
          2. Prefer covers similar to the reference cover
          3. Prefer size above target size
          4. If both below target size, prefer closest
          5. Prefer covers of most reliable source
          6. Prefer best ranked cover
          7. Prefer covers with reliable metadata
        If all previous factors do not allow sorting of two results (very unlikely):
          8. Prefer covers with less images to join
          9. Prefer covers having the target size
          10. Prefer PNG covers
          11. Prefer exactly square covers

        We don't overload the __lt__ operator because we need to pass the target_size parameter.

        """
        for c in (first, second):
            assert c.format is not None
            assert isinstance(c.size[0], int) and isinstance(c.size[1], int)

        # prefer square covers #1
        delta_ratio1 = abs(first.size[0] / first.size[1] - 1)
        delta_ratio2 = abs(second.size[0] / second.size[1] - 1)
        if abs(delta_ratio1 - delta_ratio2) > 0.15:
            return -1 if (delta_ratio1 > delta_ratio2) else 1

        # prefer similar to reference
        sr1 = first.is_similar_to_reference
        sr2 = second.is_similar_to_reference
        if sr1 and (not sr2):
            return 1
        if (not sr1) and sr2:
            return -1

        # prefer size above preferred
        delta_size1 = ((first.size[0] + first.size[1]) / 2) - target_size
        delta_size2 = ((second.size[0] + second.size[1]) / 2) - target_size
        if ((delta_size1 < 0) and (delta_size2 >= 0)) or (delta_size1 >= 0) and (delta_size2 < 0):
            return -1 if (delta_size1 < delta_size2) else 1

        # if both below target size, prefer closest
        if (delta_size1 < 0) and (delta_size2 < 0) and (delta_size1 != delta_size2):
            return -1 if (delta_size1 < delta_size2) else 1

        # prefer covers of most reliable source
        qs1 = first.source_quality.value
        qs2 = second.source_quality.value
        if qs1 != qs2:
            return -1 if (qs1 < qs2) else 1

        # prefer best ranked
        if (
            (first.rank is not None)
            and (second.rank is not None)
            and (first.__class__ is second.__class__)
            and (first.rank != second.rank)
        ):
            return -1 if (first.rank > second.rank) else 1

        # prefer reliable metadata
        if first.reliable_metadata != second.reliable_metadata:
            return 1 if first.reliable_metadata else -1

        # prefer covers with less images to join
        ic1 = len(first.urls)
        ic2 = len(second.urls)
        if ic1 != ic2:
            return -1 if (ic1 > ic2) else 1

        # prefer the preferred size
        if abs(delta_size1) != abs(delta_size2):
            return -1 if (abs(delta_size1) > abs(delta_size2)) else 1

        # prefer png
        if first.format != second.format:
            return -1 if (second.format is CoverImageFormat.PNG) else 1

        # prefer square covers #2
        if delta_ratio1 != delta_ratio2:
            return -1 if (delta_ratio1 > delta_ratio2) else 1

        # fuck, they are the same!
        return 0

    @staticmethod
    async def crunch(image_data, format, silent=False):
        """Crunch image data, and return the processed data, or orignal data if operation failed."""
        if ((format is CoverImageFormat.PNG) and (not HAS_OPTIPNG)) or (
            (format is CoverImageFormat.JPEG) and (not HAS_JPEGOPTIM)
        ):
            return image_data
        with mkstemp_ctx.mkstemp(suffix=f".{format.name.lower()}") as tmp_out_filepath:
            if not silent:
                logging.getLogger("Cover").info(f"Crunching {format.name.upper()} image...")
            with open(tmp_out_filepath, "wb") as tmp_out_file:
                tmp_out_file.write(image_data)
            size_before = len(image_data)
            if format is CoverImageFormat.PNG:
                cmd = ["optipng", "-quiet", "-o1"]
            elif format is CoverImageFormat.JPEG:
                cmd = ["jpegoptim", "-q", "--strip-all"]
            cmd.append(tmp_out_filepath)
            p = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await p.wait()
            if p.returncode != 0:
                if not silent:
                    logging.getLogger("Cover").warning("Crunching image failed")
                return image_data
            with open(tmp_out_filepath, "rb") as tmp_out_file:
                crunched_image_data = tmp_out_file.read()
            size_after = len(crunched_image_data)
            pct_saved = 100 * (size_before - size_after) / size_before
            if not silent:
                logging.getLogger("Cover").debug(f"Crunching image saved {pct_saved:.2f}% filesize")
        return crunched_image_data

    @staticmethod
    def guessImageMetadataFromData(img_data):
        """Identify an image format and size from its first bytes."""
        format, width, height = None, None, None
        img_stream = io.BytesIO(img_data)
        try:
            img = PIL.Image.open(img_stream)
        except (IOError, OSError, RuntimeError):  # PIL.UnidentifiedImageError inherits from OSError
            format = imghdr.what(None, h=img_data)
            format = SUPPORTED_IMG_FORMATS.get(format, None)
        else:
            format = img.format.lower()
            format = SUPPORTED_IMG_FORMATS.get(format, None)
            width, height = img.size
        return format, width, height

    @staticmethod
    async def guessImageMetadataFromHttpData(response):
        """Identify an image format and size from the beginning of its HTTP data."""
        metadata = None
        img_data = bytearray()

        while len(img_data) < CoverSourceResult.MAX_FILE_METADATA_PEEK_SIZE:
            new_img_data = await response.content.read(__class__.METADATA_PEEK_SIZE_INCREMENT)
            if not new_img_data:
                break
            img_data.extend(new_img_data)

            metadata = __class__.guessImageMetadataFromData(img_data)
            if (metadata is not None) and all(metadata):
                return metadata

        return metadata

    @staticmethod
    def guessImageFormatFromHttpResponse(response):
        """Guess file format from HTTP response, return format or None."""
        extensions = []

        # try to guess extension from response content-type header
        try:
            content_type = response.headers["Content-Type"]
        except KeyError:
            pass
        else:
            ext = mimetypes.guess_extension(content_type, strict=False)
            if ext is not None:
                extensions.append(ext)

        # try to extract extension from URL
        urls = list(response.history) + [response.url]
        for url in map(str, urls):
            ext = os.path.splitext(urllib.parse.urlsplit(url).path)[-1]
            if (ext is not None) and (ext not in extensions):
                extensions.append(ext)

        # now guess from the extensions
        for ext in extensions:
            try:
                return SUPPORTED_IMG_FORMATS[ext[1:]]
            except KeyError:
                pass

    @staticmethod
    async def preProcessForComparison(results, target_size, size_tolerance_prct):
        """Process results to prepare them for future comparison and sorting."""
        # find reference (=image most likely to match target cover ignoring factors like size and format)
        reference = None
        for result in results:
            if result.source_quality.isReference():
                if (reference is None) or (
                    CoverSourceResult.compare(
                        result, reference, target_size=target_size, size_tolerance_prct=size_tolerance_prct
                    )
                    > 0
                ):
                    reference = result

        # remove results that are only refs
        results = list(itertools.filterfalse(operator.attrgetter("is_only_reference"), results))

        # remove duplicates
        no_dup_results = []
        for result in results:
            is_dup = False
            for result_comp in results:
                if (
                    (result_comp is not result)
                    and (result_comp.urls == result.urls)
                    and (
                        __class__.compare(
                            result, result_comp, target_size=target_size, size_tolerance_prct=size_tolerance_prct
                        )
                        < 0
                    )
                ):
                    is_dup = True
                    break
            if not is_dup:
                no_dup_results.append(result)
        dup_count = len(results) - len(no_dup_results)
        if dup_count > 0:
            logging.getLogger("Cover").info(f"Removed {dup_count} duplicate results")
            results = no_dup_results

        if reference is not None:
            logging.getLogger("Cover").info(f"Reference is: {reference}")
            reference.is_similar_to_reference = True

            # calculate sigs
            futures = []
            for result in results:
                coroutine = result.updateSignature()
                future = asyncio.ensure_future(coroutine)
                futures.append(future)
            if reference.is_only_reference:
                assert reference not in results
                coroutine = reference.updateSignature()
                future = asyncio.ensure_future(coroutine)
                futures.append(future)
            if futures:
                await asyncio.wait(futures)
            for future in futures:
                future.result()  # raise pending exception if any

            # compare other results to reference
            for result in results:
                if (
                    (result is not reference)
                    and (result.thumbnail_sig is not None)
                    and (reference.thumbnail_sig is not None)
                ):
                    result.is_similar_to_reference = __class__.areImageSigsSimilar(
                        result.thumbnail_sig, reference.thumbnail_sig
                    )
                    if result.is_similar_to_reference:
                        logging.getLogger("Cover").debug(f"{result} is similar to reference")
                    else:
                        logging.getLogger("Cover").debug(f"{result} is NOT similar to reference")
        else:
            logging.getLogger("Cover").warning("No reference result found")

        return results

    @staticmethod
    def computeImgSignature(image_data):
        """
        Calculate an image signature.

        This is similar to ahash but uses 3 colors components
        See: https://github.com/JohannesBuchner/imagehash/blob/4.0/imagehash/__init__.py#L125

        """
        parser = PIL.ImageFile.Parser()
        parser.feed(image_data)
        img = parser.close()
        target_size = (__class__.IMG_SIG_SIZE, __class__.IMG_SIG_SIZE)
        img.thumbnail(target_size, PIL.Image.Resampling.BICUBIC)
        if img.size != target_size:
            logging.getLogger("Cover").debug(
                "Non square thumbnail after resize to %ux%u, unable to compute signature" % target_size
            )
            return None
        img = img.convert(mode="RGB")
        pixels = img.getdata()
        pixel_count = target_size[0] * target_size[1]
        color_count = 3
        r = bitarray.bitarray(pixel_count * color_count)
        r.setall(False)
        for ic in range(color_count):
            mean = sum(p[ic] for p in pixels) // pixel_count
            for ip, p in enumerate(pixels):
                if p[ic] > mean:
                    r[pixel_count * ic + ip] = True
        return r

    @staticmethod
    def areImageSigsSimilar(sig1, sig2):
        """Compare 2 image "signatures" and return True if they seem to come from a similar image, False otherwise."""
        return bitdiff(sig1, sig2) < 100


# silence third party module loggers
logging.getLogger("PIL").setLevel(logging.ERROR)
