//! Audio metadata handling

use std::{
    fs,
    path::{Path, PathBuf},
};

use anyhow::Context as _;
use lofty::{
    file::{AudioFile as _, TaggedFileExt as _},
    picture, tag,
};

/// File tags
#[derive(Debug)]
pub struct Tags {
    /// Artist tag
    pub artist: String,
    /// Album tag
    pub album: String,
    /// If requested, whether file has embedded cover or not
    pub has_embedded_cover: Option<bool>,
}

const ARTIST_KEYS: [tag::ItemKey; 2] = [tag::ItemKey::TrackArtist, tag::ItemKey::AlbumArtist];
const ALBUM_KEYS: [tag::ItemKey; 1] = [tag::ItemKey::AlbumTitle];

fn extract_tag<'a>(tags: &'a tag::Tag, keys: &'_ [tag::ItemKey]) -> Option<&'a str> {
    let mut value = None;
    for key in keys {
        value = value.or_else(|| tags.get_string(key));
    }
    value
}

// Return the first file tag type that already has artist and album set
fn usable_tag_type(file: &lofty::file::TaggedFile) -> Option<tag::TagType> {
    for tags in file.primary_tag().into_iter().chain(file.tags()) {
        if extract_tag(tags, &ARTIST_KEYS).is_some() && extract_tag(tags, &ALBUM_KEYS).is_some() {
            return Some(tags.tag_type());
        }
    }
    None
}

/// Read artist/album tags from a bunch of audio files from the same album, and optionally if it has embedded cover.
/// Return early as soon has a single file with both tags has been found
#[must_use]
pub fn read_metadata<P>(file_paths: &[P], probe_embedded_cover: bool) -> Option<Tags>
where
    P: AsRef<Path>,
{
    for file_path in file_paths {
        let Ok(file) = lofty::read_from_path(file_path) else {
            continue;
        };
        if let Some(tag_type) = usable_tag_type(&file) {
            let tags = file.tag(tag_type)?;
            let has_embedded_cover = probe_embedded_cover.then(|| {
                tags.pictures()
                    .iter()
                    .any(|p| p.pic_type() == picture::PictureType::CoverFront)
            });
            return Some(Tags {
                artist: extract_tag(tags, &ARTIST_KEYS)?.to_owned(),
                album: extract_tag(tags, &ALBUM_KEYS)?.to_owned(),
                has_embedded_cover,
            });
        }
    }
    None
}

/// Embed front cover into all given files
pub fn embed_cover(img_path: &Path, audio_filepaths: Vec<PathBuf>) -> anyhow::Result<()> {
    let mut img_file = fs::File::open(img_path)
        .with_context(|| format!("Failed to read image from {img_path:?}"))?;
    let mut picture =
        picture::Picture::from_reader(&mut img_file).context("Failed to load image")?;
    picture.set_pic_type(picture::PictureType::CoverFront);

    for audio_filepath in audio_filepaths {
        let mut file = lofty::read_from_path(&audio_filepath)
            .with_context(|| format!("Failed to load tags from {audio_filepath:?}"))?;
        if let Some(tag_type) = usable_tag_type(&file) {
            let tags = file
                .tag_mut(tag_type)
                .ok_or_else(|| anyhow::anyhow!("Tags have disappeared from {audio_filepath:?}"))?;
            tags.remove_picture_type(picture::PictureType::CoverFront);
            tags.push_picture(picture.clone());
            file.save_to_path(&audio_filepath, lofty::config::WriteOptions::default())
                .with_context(|| format!("Failed to write tags to {audio_filepath:?}"))?;
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use std::{
        io::Write as _,
        path::PathBuf,
        process::{Command, Stdio},
        sync::LazyLock,
    };

    use super::*;

    fn generate_test_png() -> Vec<u8> {
        let output = Command::new("ffmpeg")
            .args([
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=100x100:d=1",
                "-frames:v",
                "1",
                "-c:v",
                "png",
                "-f",
                "image2pipe",
                "pipe:1",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .output()
            .unwrap();
        assert!(output.status.success());

        output.stdout
    }

    static TEST_COVER_PNG: LazyLock<Vec<u8>> = LazyLock::new(generate_test_png);

    fn generate_audio_file(
        extension: &str,
        artist: Option<&str>,
        album_artist: Option<&str>,
        album: Option<&str>,
        png_cover: Option<&[u8]>,
    ) -> tempfile::NamedTempFile {
        let audio_file = tempfile::Builder::new()
            .suffix(&format!(".{extension}"))
            .tempfile()
            .unwrap();

        let cover_file = png_cover.map(|data| {
            let mut f = tempfile::Builder::new().suffix(".png").tempfile().unwrap();
            f.write_all(data).unwrap();
            f
        });

        let mut cmd = Command::new("ffmpeg");

        cmd.args(["-f", "lavfi", "-i", "sine=frequency=440:duration=2"]);

        if let Some(cover_file) = &cover_file {
            cmd.arg("-i");
            cmd.arg(cover_file.path());
            cmd.args([
                "-map",
                "0:a",
                "-map",
                "1:v",
                "-c:v",
                "copy",
                "-metadata:s:v",
                "title=Album cover",
                "-metadata:s:v",
                "comment=Cover (front)",
                "-disposition:v",
                "attached_pic",
            ]);
        }

        if let Some(artist) = artist {
            cmd.arg("-metadata");
            cmd.arg(format!("artist={artist}"));
        }

        if let Some(album_artist) = album_artist {
            cmd.arg("-metadata");
            cmd.arg(format!("album_artist={album_artist}"));
        }

        if let Some(album) = album {
            cmd.arg("-metadata");
            cmd.arg(format!("album={album}"));
        }

        cmd.arg("-y");
        cmd.arg(audio_file.path());

        let status = cmd
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .unwrap();
        assert!(status.success());

        audio_file
    }

    macro_rules! ffmpeg_test {
        ($item:item) => {
            #[cfg_attr(
                not(feature = "tests-ffmpeg"),
                ignore = "tests-ffmpeg feature is not set"
            )]
            #[test]
            $item
        };
    }

    ffmpeg_test! {
        fn ogg_vorbis_with_vorbis_comments() {
            let file = generate_audio_file("ogg", Some("Test Artist"), None, Some("Test Album"), None);
            let tags = read_metadata(&[file], false).unwrap();
            assert_eq!(tags.artist, "Test Artist");
            assert_eq!(tags.album, "Test Album");
            assert!(tags.has_embedded_cover.is_none());
        }
    }

    ffmpeg_test! {
        fn mp3_with_id3v2() {
            let file = generate_audio_file("mp3", Some("MP3 Artist"), None, Some("MP3 Album"), None);
            let tags = read_metadata(&[file], false).unwrap();
            assert_eq!(tags.artist, "MP3 Artist");
            assert_eq!(tags.album, "MP3 Album");
        }
    }

    ffmpeg_test! {
        fn mp3_with_embedded_cover() {
            let file = generate_audio_file(
                "mp3",
                Some("MP3 Cover Artist"),
                None,
                Some("MP3 Cover Album"),
                Some(&TEST_COVER_PNG),
            );
            let tags = read_metadata(&[file], true).unwrap();
            assert_eq!(tags.has_embedded_cover, Some(true));
        }
    }

    ffmpeg_test! {
        fn flac_with_vorbis_comments() {
            let file = generate_audio_file("flac", Some("FLAC Artist"), None, Some("FLAC Album"), None);
            let tags = read_metadata(&[file], false).unwrap();
            assert_eq!(tags.artist, "FLAC Artist");
            assert_eq!(tags.album, "FLAC Album");
        }
    }

    ffmpeg_test! {
        fn flac_with_embedded_cover() {
            let file = generate_audio_file(
                "flac",
                Some("FLAC Cover Artist"),
                None,
                Some("FLAC Cover Album"),
                Some(&TEST_COVER_PNG),
            );
            let tags = read_metadata(&[file], true).unwrap();
            assert_eq!(tags.has_embedded_cover, Some(true));
        }
    }

    ffmpeg_test! {
        fn wav_with_riff_info() {
            let file = generate_audio_file("wav", Some("WAV Artist"), None, Some("WAV Album"), None);
            let tags = read_metadata(&[file], false).unwrap();
            assert_eq!(tags.artist, "WAV Artist");
            assert_eq!(tags.album, "WAV Album");
        }
    }

    ffmpeg_test! {
        fn file_without_tags() {
            let file = generate_audio_file("ogg", None, None, None, None);
            let result = read_metadata(&[file], false);
            assert!(result.is_none());
        }
    }

    ffmpeg_test! {
        fn file_with_only_artist_tag() {
            let file = generate_audio_file("ogg", Some("Only Artist"), None, None, None);
            let result = read_metadata(&[file], false);
            assert!(result.is_none());
        }
    }

    ffmpeg_test! {
        fn file_with_only_album_tag() {
            let file = generate_audio_file("ogg", None, None, Some("Only Album"), None);
            let result = read_metadata(&[file], false);
            assert!(result.is_none());
        }
    }

    ffmpeg_test! {
        fn multiple_files_first_valid() {
            let file1 =
                generate_audio_file("ogg", Some("First Artist"), None, Some("First Album"), None);
            let file2 = generate_audio_file(
                "ogg",
                Some("Second Artist"),
                None,
                Some("Second Album"),
                None,
            );
            let tags = read_metadata(&[file1, file2], false).unwrap();
            assert_eq!(tags.artist, "First Artist");
            assert_eq!(tags.album, "First Album");
        }
    }

    ffmpeg_test! {
        fn multiple_files_first_invalid_second_valid() {
            let file1 = generate_audio_file("ogg", None, None, None, None);
            let file2 = generate_audio_file(
                "ogg",
                Some("Second Artist"),
                None,
                Some("Second Album"),
                None,
            );
            let tags = read_metadata(&[file1, file2], false).unwrap();
            assert_eq!(tags.artist, "Second Artist");
            assert_eq!(tags.album, "Second Album");
        }
    }

    ffmpeg_test! {
        fn nonexistent_file() {
            let result = read_metadata(&[PathBuf::from("/nonexistent/path/file.mp3")], false);
            assert!(result.is_none());
        }
    }

    ffmpeg_test! {
        fn empty_file_list() {
            let result = read_metadata::<PathBuf>(&[], false);
            assert!(result.is_none());
        }
    }

    ffmpeg_test! {
        fn corrupt_file() {
            let mut corrupt_file = tempfile::Builder::new().suffix(".mp3").tempfile().unwrap();
            corrupt_file
                .write_all(b"This is not a valid audio file")
                .unwrap();
            let result = read_metadata(&[corrupt_file.path().to_path_buf()], false);
            assert!(result.is_none());
        }
    }

    ffmpeg_test! {
        fn no_embedded_cover_probe() {
            let file = generate_audio_file(
                "mp3",
                Some("No Cover Artist"),
                None,
                Some("No Cover Album"),
                None,
            );
            let tags = read_metadata(&[file], true).unwrap();
            assert_eq!(tags.has_embedded_cover, Some(false));
        }
    }

    ffmpeg_test! {
        fn album_artist_fallback() {
            let file = generate_audio_file("ogg", None, Some("Album Artist"), Some("Test Album"), None);
            let tags = read_metadata(&[file], false).unwrap();
            assert_eq!(tags.artist, "Album Artist");
            assert_eq!(tags.album, "Test Album");
        }
    }

    ffmpeg_test! {
        fn track_artist_preferred_over_album_artist() {
            let file = generate_audio_file(
                "ogg",
                Some("Track Artist"),
                Some("Album Artist"),
                Some("Test Album"),
                None,
            );
            let tags = read_metadata(&[file], false).unwrap();
            assert_eq!(tags.artist, "Track Artist");
        }
    }
}
