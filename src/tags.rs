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
pub fn read_metadata(file_paths: &[PathBuf], probe_embedded_cover: bool) -> Option<Tags> {
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
